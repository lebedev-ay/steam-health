import { shiftDay, esc, sameRange, dayInRange, plural, wrapText, firstSentence, cutWords } from './util.js';
import { TYPES, PLATFORM_TYPES, BACKGROUND_COLOR,
         densityFilter, densityThreshold, eventFilterLabel,
         mainEventLabel, NO_EVENT_LABEL } from './events.js';
import { renderChangePointList } from './cplist.js';
import { focusVerdict } from './verdicts.js';

let lastData = null;
// выводы по переломам: день -> карточка из /api/verdicts. Отметка над ромбом ставится только у переломов, для которых вывод есть
let verdictsByDay = new Map();
let verdictClickBound = false;
// голоса по дням из /api/votes: доля «не рекомендую» в окнах вокруг перелома для анонса в подсказке
let votesByDay = new Map();
let cpMarkerIndices = [];
let cpBaseMarker = null;
let lastRenderedRange = null;
let lastFigure = null;
// накопленный диапазон незавершённого жеста; пока он есть, в layout лежит то, что нарисовано, а не то, что видит пользователь.
// После применения ещё ждём перерисовки Plotly - её приход снимает срок, а сам срок нужен, если relayout почему-то не придёт
let zoomTarget = null;
let zoomTimer = null;
let wheelSettledBy = 0;
let relayoutBound = false;
let legendBound = false;
let relayoutTimer = null;

// группа платформы в легенде: у полос Steam та же пара слоёв, что у игровых событий - маркер и покраска
const PLATFORM_GROUP = 'platform';

// кривые и ромбы переломов - это сами данные. Изоляция их не касается: спрятать «всё остальное» по клику на событии значило бы убрать с экрана то, ради чего график открыт
const DATA_GROUPS = new Set(['totals', 'base', 'value', 'cp']);

// задержка та же, что у Plotly по умолчанию: одиночное действие ждёт, не придёт ли второй щелчок
const LEGEND_DBLCLICK_MS = 300;

// промежуток между событиями внутри одного жеста доходит до 185 мс (замер на перетаскивании ползунка), поэтому порог взят с запасом
const RELAYOUT_DEBOUNCE_MS = 250;

// ниже этой ширины строки легенды переносятся и налезают на кнопки периода: замер дал перенос на второй ряд при 974 px и одну строку при 1230.
// Там раскладку верхней полосы отдаём Plotly - он сам отводит легенде место и сдвигает кнопки под неё
const LEGEND_AUTO_PX = 1100;

// зум колесом ведём сами: встроенный перерисовывает график на каждом щелчке, и пользователь видит состояния, которые уже неактуальны.
// Множитель шага и точка отсчёта взяты из исходника Plotly 2.35.2, чтобы жест ощущался прежним
const WHEEL_SETTLE_MS = 250;
const WHEEL_COMMIT_MS = 500;
// сутки: зерно данных дневное, уже некуда
const MIN_WINDOW_MS = 86400000;

// анонс перелома: шрифт основного текста страницы (16 px у body) и перенос по числу символов - Plotly сам строки не переносит.
// 38 символов при 16 px - это около 340 px, ширина подсказки держится в 360 px
const ANNOUNCE_FONT_PX = 16;
const ANNOUNCE_LINE_CHARS = 38;
const ANNOUNCE_EVENT_CHARS = 60;
const ANNOUNCE_SENTENCE_CHARS = 120;

// фон подсказки Plotly берёт из цвета маркера, и светлый текст на жёлтом анонсе или на бледно-сером фоне не читается. Цвет типа остаётся в самом маркере
const MARKER_HOVER = { bgcolor: '#262b33', bordercolor: '#3a4048', font: { color: '#c7d0d9' } };

// покраска колонок и треугольники - два слоя одного события, и прятаться они обязаны вместе.
// Plotly переключает только трассу, до shapes ему дела нет, а его собственный visible к тому же сбрасывается на каждой перерисовке
let hiddenGroups = new Set();
// тип, изолированный двойным кликом; hiddenGroups при этом не трогается и возвращается при снятии изоляции
let isolatedGroup = null;
let legendClickTimer = null;

function groupVisible(group) {
  if (DATA_GROUPS.has(group)) return !hiddenGroups.has(group);
  if (isolatedGroup) return group === isolatedGroup;
  return !hiddenGroups.has(group);
}

function toggleGroup(group) {
  if (hiddenGroups.has(group)) hiddenGroups.delete(group);
  else hiddenGroups.add(group);
}

function zoomPending() {
  return zoomTarget !== null || performance.now() < wheelSettledBy;
}

function previewLayers(chart) {
  return [chart.querySelector('.cartesianlayer .subplot.xy .overplot'),
          chart.querySelector('.layer-below .shapelayer')].filter(Boolean);
}

function clearPreview(chart) {
  previewLayers(chart).forEach(l => l.removeAttribute('transform'));
}

// отклик на щелчок - сдвиг и растяжение уже нарисованного: два setAttribute вместо полной отрисовки.
// Сетка и подписи осей остаются на месте до конца жеста, данные едут по ним
function drawPreview(chart, rect, drawn, target) {
  const svg = chart.querySelector('.main-svg').getBoundingClientRect();
  const left = rect.left - svg.left;
  const scale = (drawn[1] - drawn[0]) / (target[1] - target[0]);
  const shift = left + rect.width * (drawn[0] - target[0]) / (target[1] - target[0]) - left * scale;
  const tr = `translate(${shift},0) scale(${scale},1)`;
  previewLayers(chart).forEach(l => l.setAttribute('transform', tr));
}

function applyZoom(chart) {
  const target = zoomTarget;
  zoomTarget = null;
  wheelSettledBy = performance.now() + WHEEL_COMMIT_MS;
  clearPreview(chart);
  // строкой, а не числом: числовую границу Plotly так и оставляет числом, и Date.parse в sameRange на ней ломается
  Plotly.relayout(chart, {
    'xaxis.range': [new Date(target[0]).toISOString(), new Date(target[1]).toISOString()]
  });
}

function bindWheelZoom() {
  const chart = document.getElementById('sentiment');

  chart.addEventListener('wheel', e => {
    const drag = chart.querySelector('.nsewdrag');
    if (!drag) return;

    const rect = drag.getBoundingClientRect();
    // колесо вне области данных - над легендой, ползунком, полями: пусть страница листается как обычно
    if (e.clientX < rect.left || e.clientX > rect.right
        || e.clientY < rect.top || e.clientY > rect.bottom) return;

    e.preventDefault();

    const drawn = chart.layout.xaxis.range.map(v => new Date(v).getTime());
    const from = zoomTarget || drawn;
    const factor = Math.exp(-Math.min(Math.max(-e.deltaY, -20), 20) / 200);
    const anchor = from[0] + (from[1] - from[0]) * (e.clientX - rect.left) / rect.width;
    const k = Math.max((from[1] - from[0]) * factor, MIN_WINDOW_MS) / (from[1] - from[0]);
    zoomTarget = [anchor + (from[0] - anchor) * k, anchor + (from[1] - anchor) * k];

    drawPreview(chart, rect, drawn, zoomTarget);

    clearTimeout(zoomTimer);
    zoomTimer = setTimeout(() => applyZoom(chart), WHEEL_SETTLE_MS);
  }, { passive: false });

  // перетаскивание и рамка отсчитываются от того, что нарисовано: незавершённый зум применяем сразу
  chart.addEventListener('mousedown', () => {
    if (zoomTarget === null) return;
    clearTimeout(zoomTimer);
    applyZoom(chart);
  }, true);
}

function rangeDays(range) {
  return Math.abs(new Date(range[1]) - new Date(range[0])) / 86400000;
}

// от диапазона фигура зависит только через порог плотности: сам набор событий, покраска и трассы от границ окна не меняются.
// Всё, что вошло сюда, требует полной перерисовки; при совпадении подписи хватает строки состояния и таблицы
function isNarrow() {
  const w = document.getElementById('sentiment').clientWidth;
  return w > 0 && w < LEGEND_AUTO_PX;
}

function figureSignature(windowDays) {
  return [densityThreshold(windowDays),
          isNarrow(),
          document.getElementById('mode').value,
          document.getElementById('showPlatform').checked,
          isolatedGroup,
          [...hiddenGroups].sort().join(',')].join('|');
}

function cpTraceIndex() {
  // трасс с этим именем две: одна ради свотча легенды, вторая с точками
  return document.getElementById('sentiment').data
    .findIndex(t => t.name === 'Переломы' && t.showlegend === false);
}

// подсветка по наведению на строку таблицы: restyle нужных точек вместо перерисовки всего графика
function highlightChangePoint(cpIdx) {
  if (!cpBaseMarker) return;
  const idxs = cpMarkerIndices[cpIdx] || [];
  if (!idxs.length) return;

  const size = cpBaseMarker.size.slice();
  const lineWidth = cpBaseMarker.lineWidth.slice();
  idxs.forEach(i => { size[i] = cpBaseMarker.size[i] + 6; lineWidth[i] = 5; });

  Plotly.restyle('sentiment',
    { 'marker.size': [size], 'marker.line.width': [lineWidth] }, [cpTraceIndex()]);
}

function unhighlightChangePoint() {
  if (!cpBaseMarker) return;
  Plotly.restyle('sentiment',
    { 'marker.size': [cpBaseMarker.size], 'marker.line.width': [cpBaseMarker.lineWidth] },
    [cpTraceIndex()]);
}

// подсказка ромба - анонс, не больше пяти пунктов: дата, доля «не рекомендую», событие, начало вывода и приглашение к нему.
// Направление и величина сдвига есть в таблице переломов и в подсказке не повторяются
function announce(c, verdict) {
  const lines = [`<b>${new Date(c.day + 'T00:00:00').toLocaleDateString('ru-RU')}</b>`];

  // у перелома с выводом доли берутся из вывода, чтобы подсказка и карточка не расходились в округлении
  const before = verdict ? verdict.negative_before : votesShare(shiftDay(c.day, -7), c.day);
  const after = verdict ? verdict.negative_after : votesShare(c.day, shiftDay(c.day, 7));
  if (before !== null && after !== null) lines.push(`не рекомендуют: ${before}% → ${after}%`);

  const event = cutWords(mainEventLabel(c, Infinity), ANNOUNCE_EVENT_CHARS);
  if (event !== NO_EVENT_LABEL) lines.push(event);

  if (verdict && verdict.checked) lines.push(firstSentence(verdict.what_happened, ANNOUNCE_SENTENCE_CHARS));
  if (verdict) lines.push('<i>Нажмите - подробнее</i>');

  return lines.map((line, i) => i === 0 || line.startsWith('<i>') ? line : wrapText(line, ANNOUNCE_LINE_CHARS)).join('<br>');
}

// доля отзывов «не рекомендую» за [from, to) в целых процентах; окна те же, что в выводе
function votesShare(from, to) {
  let total = 0, negative = 0;
  for (let d = from; d < to; d = shiftDay(d, 1)) {
    const v = votesByDay.get(d);
    if (v) { total += v.total; negative += v.negative; }
  }
  return total ? Math.round(100 * negative / total) : null;
}

// перерисовка по уже загруженным данным (range = null - вся история): зум и панорамирование пересчитывают слои событий без похода на сервер
export function renderChart(range) {
  const data = lastData;
  if (!data) return;

  const isDelta = document.getElementById('mode').value === 'delta';
  const narrow = isNarrow();
  const cps = data.change_points || [];

  const days = data.daily.map(d => d.day);
  const values = data.daily.map(d => isDelta ? d.delta : d.pct);
  const totals = data.daily.map(d => d.total);

  const clean = values.filter(v => v !== null && v !== undefined);
  const topY = clean.length ? Math.max(...clean) : 100;
  const floorY = clean.length ? Math.min(0, ...clean) : 0;

  // маркеры событий - полосой над данными: на уровне максимума кривой они сливались с её пиками
  const span = Math.max(topY - floorY, 1);
  const eventMarkerY = topY + span * 0.09;

  const effectiveRange = range || (days.length ? [days[0], days[days.length - 1]] : undefined);
  const windowDays = effectiveRange
    ? Math.abs(new Date(effectiveRange[1]) - new Date(effectiveRange[0])) / 86400000
    : Infinity;
  const keepEvent = densityFilter(windowDays);
  const minWeight = parseFloat(document.getElementById('minWeight').value) || 0;

  const visibleCpCount = cps.filter(c => dayInRange(c.day, effectiveRange)).length;
  const cpCountText = visibleCpCount === cps.length
    ? `переломов: ${cps.length}`
    : `${plural(visibleCpCount, 'показан', 'показано', 'показано')} ${visibleCpCount} ` +
      `${plural(visibleCpCount, 'перелом', 'перелома', 'переломов')} из ${cps.length}`;

  document.getElementById('info').textContent =
    `окно ${data.window} дн., медиана ${data.median_volume} ` +
    `${plural(data.median_volume, 'отзыв', 'отзыва', 'отзывов')} в день, ` +
    `${cpCountText}; ${eventFilterLabel(windowDays, minWeight)}`;

  renderChangePointList(cps, effectiveRange, {
    note: data.change_points_note,
    onSelect: c => Plotly.relayout('sentiment', {
      'xaxis.range': [shiftDay(c.day, -30), shiftDay(c.day, 30)]
    }),
    onHover: highlightChangePoint,
    onLeave: unhighlightChangePoint
  });

  // копия обязательна: переданный массив Plotly держит как свой xaxis.range и меняет на месте, так что ссылка на него всегда сравнивалась бы сама с собой
  lastRenderedRange = effectiveRange ? effectiveRange.slice() : null;

  // при том же пороге плотности фигура не меняется вовсе: ось Plotly уже подвинул сам, а строка состояния и таблица обновлены выше
  const figure = figureSignature(windowDays);
  if (figure === lastFigure) return;
  lastFigure = figure;

  const cpIndex = {};
  days.forEach((d, i) => cpIndex[d] = i);

  const visibleEvents = data.events.filter(keepEvent);
  const shadedEvents = visibleEvents.filter(e => groupVisible(e.type));

  const byDay = {};
  shadedEvents.forEach(e => {
    (byDay[e.day] = byDay[e.day] || []).push(e);
  });

  const eventShapes = Object.entries(byDay).map(([day, items]) => ({
    type: 'rect',
    x0: day, x1: shiftDay(day, 1),
    yref: 'paper', y0: 0, y1: 1,
    fillcolor: TYPES[items[0].type]?.color || BACKGROUND_COLOR,
    opacity: 0.14,
    line: { width: 0 },
    layer: 'below'
  }));

  // полоса шириной в окно поиска (±3 дня), дата приблизительная. Плотностью не фильтруем: их 80 на 12 лет, в кашу не сливаются
  const platformEvents = data.platform_events || [];
  const showPlatform = document.getElementById('showPlatform').checked;
  // галочка убирает слой целиком, легенда - только прячет, оставляя строку для возврата
  const platformHidden = !groupVisible(PLATFORM_GROUP);

  const platformShapes = showPlatform && !platformHidden ? platformEvents.map(e => ({
    type: 'rect',
    x0: shiftDay(e.date, -3), x1: shiftDay(e.date, 4),
    yref: 'paper', y0: 0, y1: 1,
    fillcolor: PLATFORM_TYPES[e.type]?.bandColor || BACKGROUND_COLOR,
    opacity: 0.05,
    line: { width: 0 },
    layer: 'below'  // под данными - фон, не поверх линии
  })) : [];

  // shapes в Plotly не дают тултип, поэтому дата рядом ещё и точкой: квадрат ниже треугольников игровых событий
  const platformMarkerY = topY + span * 0.03;

  const platformMarkerTrace = {
    x: platformEvents.map(e => e.date),
    y: platformEvents.map(() => platformMarkerY),
    mode: 'markers',
    name: 'события Steam',
    legendgroup: PLATFORM_GROUP,
    visible: platformHidden ? 'legendonly' : true,
    marker: {
      size: 8,
      symbol: 'square',
      color: platformEvents.map(e => PLATFORM_TYPES[e.type]?.markerColor || BACKGROUND_COLOR),
      line: { color: '#14161a', width: 1 }
    },
    text: platformEvents.map(e =>
      `${PLATFORM_TYPES[e.type]?.label || e.type}<br>${esc(e.title)}`),
    hoverlabel: { ...MARKER_HOVER },
    hovertemplate: '%{x|%d.%m.%Y}<br>%{text}<extra></extra>'
  };

  const shapes = [...eventShapes, ...platformShapes];

  // отдельная серия на каждый тип - даёт кликабельную легенду
  const byType = {};
  visibleEvents.forEach(e => {
    (byType[e.type] = byType[e.type] || []).push(e);
  });

  const eventTraces = Object.entries(byType).map(([type, items]) => ({
    x: items.map(e => e.day),
    y: items.map(() => eventMarkerY),
    mode: 'markers',
    name: TYPES[type]?.label || type,
    legendgroup: type,
    visible: groupVisible(type) ? true : 'legendonly',
    // размер общий с миниатюрой rangeslider (Plotly не различает) - уменьшен, чтобы в ней не было каши
    marker: {
      size: 9, symbol: 'triangle-down',
      color: TYPES[type]?.color || BACKGROUND_COLOR,
      line: { color: '#14161a', width: 1 }
    },
    text: items.map(e => e.weight
      ? `${TYPES[type]?.label || type} ×${e.weight}<br>${esc(e.title)}`
      : `${TYPES[type]?.label || type}<br>${esc(e.title)}`),
    hoverlabel: { ...MARKER_HOVER },
    hovertemplate: '%{x}<br>%{text}<extra></extra>'
  }));

  // один ромб на перелом: разрешение внутри суток данными не подкреплено, зерно дневное. 
  // Цвет - по событию с наибольшим весом, остальные типы перечисляются в тултипе цветными строками
  const cpX = [], cpY = [], cpColor = [], cpSize = [], cpLine = [], cpText = [], cpSymbol = [];
  cpMarkerIndices = [];

  cps.forEach(c => {
    const baseY = values[cpIndex[c.day]];
    const myIndices = [];
    cpMarkerIndices.push(myIndices);
    if (baseY === undefined || baseY === null) return;

    // ромб - точка на данных, и его собственное свойство это знак и величина сдвига. Цвет кодирует только направление и совпадает с таблицей
    const dirColor = c.score < 0 ? '#ff4d3d' : '#3ddc84';
    // уменьшен по той же причине, что треугольники выше -
    // общий размер с миниатюрой rangeslider
    const size = Math.min(7 + Math.abs(c.score) * 0.15, 11);
    // ромб с выводом залит, без вывода - контур: так видно, по каким переломам есть текст под графиком, без отдельного слоя точек
    const verdict = verdictsByDay.get(c.day);

    cpX.push(c.day); cpY.push(baseY);
    cpColor.push(dirColor); cpSize.push(size); cpLine.push('#14161a');
    cpSymbol.push(verdict ? 'diamond' : 'diamond-open');
    myIndices.push(cpX.length - 1);
    cpText.push(announce(c, verdict));
  });

  const cpLineWidth = cpX.map(() => 2.5);
  cpBaseMarker = { size: cpSize.slice(), lineWidth: cpLineWidth.slice() };

  // свотч легенды Plotly берёт из первой точки, а цвет ромба означает направление: в легенде оказывалось направление первого попавшегося перелома. Пустая трасса даёт нейтральный свотч, обе в одной группе - клик по строке по-прежнему прячет ромбы
  const changePointsLegend = {
    // точка из null: трассу совсем без точек Plotly считает невидимой и строки в легенде не рисует
    x: [null], y: [null],
    mode: 'markers',
    name: 'Переломы',
    legendgroup: 'cp',
    visible: groupVisible('cp') ? true : 'legendonly',
    marker: {
      size: 9, symbol: 'diamond', color: '#c7d0d9',
      line: { color: '#14161a', width: 1 }
    },
    hoverinfo: 'skip'
  };

  const changePoints = {
    x: cpX, y: cpY,
    mode: 'markers',
    name: 'Переломы',
    legendgroup: 'cp',
    visible: groupVisible('cp') ? true : 'legendonly',
    showlegend: false,
    marker: {
      size: cpSize,
      symbol: cpSymbol,
      color: cpColor,
      line: { color: cpLine, width: cpLineWidth }
    },
    text: cpText,
    // анонс читается как абзац: слева, основным шрифтом страницы
    hoverlabel: { ...MARKER_HOVER, align: 'left', font: { ...MARKER_HOVER.font, size: ANNOUNCE_FONT_PX } },
    hovertemplate: '%{text}<extra></extra>'
  };

  Plotly.react('sentiment', [
    {
      x: days, y: totals, type: 'bar', name: 'Отзывов',
      yaxis: 'y2',
      legendgroup: 'totals',
      visible: groupVisible('totals') ? true : 'legendonly',
      marker: { color: 'rgba(110,150,190,0.28)' },
      hovertemplate: '%{x}<br>Отзывов: %{y}<extra></extra>'
    },
    ...(isDelta ? [] : [{
      x: days, y: data.daily.map(d => d.base), mode: 'lines',
      name: 'База, медиана 90 дней',
      legendgroup: 'base',
      visible: groupVisible('base') ? true : 'legendonly',
      line: { color: '#8a95a3', width: 1.5, dash: 'dot' },
      hovertemplate: '%{x}<br>База: %{y}%<extra></extra>'
    }]),
    {
      x: days, y: values, mode: 'lines',
      name: isDelta ? 'Отклонение, п.п.' : 'Позитивных, %',
      legendgroup: 'value',
      visible: groupVisible('value') ? true : 'legendonly',
      // толще и контрастнее, чтобы читалась поверх маркеров в миниатюре rangeslider (см. комментарий у него ниже)
      line: { color: '#f0f4f8', width: 3.5, shape: 'spline', smoothing: 0.4 },
      customdata: totals,
      hovertemplate: isDelta
        ? '%{x}<br>Отклонение: %{y} п.п.<br>Отзывов: %{customdata}<extra></extra>'
        : '%{x}<br>Позитив: %{y}%<br>Отзывов: %{customdata}<extra></extra>'
    },
    ...eventTraces,
    ...(showPlatform ? [platformMarkerTrace] : []),
    changePointsLegend,
    changePoints
  ], {
    shapes: shapes,
    height: 640,
    paper_bgcolor: '#262b33',
    plot_bgcolor: '#1e232a',
    font: { color: '#c7d0d9' },
    // на широком экране верхняя полоса размечена вручную; на узком её считает Plotly, иначе легенда ложится на кнопки и на сам график
    margin: narrow ? { r: 60, b: 60, l: 60 } : { t: 70, r: 60, b: 60, l: 60 },
    yaxis: {
      title: isDelta ? 'Отклонение, п.п.' : 'Позитивных, %',
      gridcolor: '#333a44',
      zeroline: isDelta,
      zerolinecolor: '#6b7684',
      zerolinewidth: 1.5
    },
    yaxis2: {
      title: 'Отзывов в день', side: 'right',
      overlaying: 'y', showgrid: false
    },
    xaxis: {
      gridcolor: '#333a44',
      // rangeslider зеркалит все трейсы общей оси, исключить трейс точечно Plotly не даёт - отсюда размеры маркеров и линии выше
      rangeslider: { visible: true, bgcolor: '#1e232a', bordercolor: '#333a44' },
      rangeselector: {
        buttons: [
          { count: 1, label: 'месяц', step: 'month', stepmode: 'backward' },
          { count: 3, label: '3 месяца', step: 'month', stepmode: 'backward' },
          { count: 1, label: 'год', step: 'year', stepmode: 'backward' },
          { step: 'all', label: 'всё' }
        ],
        ...(narrow ? {} : { x: 0, xanchor: 'left', y: 1.20, yanchor: 'bottom' }),
        bgcolor: '#262b33', activecolor: '#3a4048', bordercolor: '#3a4048',
        borderwidth: 1,
        font: { color: '#c7d0d9', size: 12 }
      },
      autorange: false,
      range: effectiveRange
    },
    // левой кнопкой окно едет по датам, сохраняя ширину. Зум остался колесом, кнопками периода и rangeslider, а выделение рамкой - кнопкой Zoom в панели Plotly
    dragmode: 'pan',
    hovermode: 'closest',
    legend: narrow
      ? { orientation: 'h', bgcolor: 'rgba(0,0,0,0)' }
      : { orientation: 'h', y: 1.06, bgcolor: 'rgba(0,0,0,0)' }
  // двойной клик выключен: на ряде в несколько лет случайное попадание выбрасывало
  // из выбранного окна. 'reset' здесь не помогает - при autorange: false Plotly не хранит
  // _rangeInitial и откатывается к автомасштабу. Полный сброс остался кнопкой «всё».
  // Встроенный зум колесом выключен: им управляет bindWheelZoom выше. Страница по-прежнему листается мимо графика, свободной высоты хватает
  }, { responsive: true, doubleClick: false, scrollZoom: false });

  if (!verdictClickBound) {
    verdictClickBound = true;
    document.getElementById('sentiment').on('plotly_click', ev => {
      const pt = ev.points && ev.points[0];
      if (!pt || pt.data.name !== 'Переломы') return;
      const day = String(pt.x).slice(0, 10);
      if (verdictsByDay.has(day)) focusVerdict(day);
    });
  }

  if (!legendBound) {
    legendBound = true;
    // Plotly шлёт legendclick и на первом щелчке двойного, поэтому одиночное действие откладывается: иначе двойной клик успевал бы сначала переключить группу, а перерисовка - подменить строку легенды под курсором
    document.getElementById('sentiment').on('plotly_legendclick', ev => {
      const group = ev.data[ev.curveNumber].legendgroup;
      if (!group) return true;

      clearTimeout(legendClickTimer);
      legendClickTimer = setTimeout(() => {
        // клик по любой строке событий выходит из изоляции: серая строка от щелчка обязана вернуться, а не остаться серой
        if (isolatedGroup && !DATA_GROUPS.has(group)) isolatedGroup = null;
        else toggleGroup(group);
        renderChart(lastRenderedRange);
      }, LEGEND_DBLCLICK_MS);
      return false;
    });

    document.getElementById('sentiment').on('plotly_legenddoubleclick', ev => {
      const group = ev.data[ev.curveNumber].legendgroup;
      if (!group) return true;

      clearTimeout(legendClickTimer);
      // у кривой изолировать нечего, поэтому двойной клик по ней - тот же одиночный
      if (DATA_GROUPS.has(group)) toggleGroup(group);
      else isolatedGroup = isolatedGroup === group ? null : group;

      renderChart(lastRenderedRange);
      return false;
    });
  }

  // zoom, pan, rangeslider и кнопки периода приходят сюда одним plotly_relayout - перерисовываем только клиентские слои
  if (!relayoutBound) {
    relayoutBound = true;
    bindWheelZoom();
    document.getElementById('sentiment').on('plotly_relayout', () => {
      // Plotly записал ось в layout, ждать его больше нечего
      wheelSettledBy = 0;
      const gd = document.getElementById('sentiment');
      const xr = gd.layout.xaxis.range;
      const newRange = xr ? [xr[0], xr[1]] : null;
      // сюда же приходит изменение размера окна: диапазон тот же, но подпись могла смениться шириной
      const sameFigure = newRange && figureSignature(rangeDays(newRange)) === lastFigure;
      if (sameFigure && sameRange(newRange, lastRenderedRange)) return;

      clearTimeout(relayoutTimer);
      // пока фигура прежняя, обновить нужно только строку состояния и таблицу - это доли миллисекунды, ждать нечего.
      // Смена порога плотности или ширины перестраивает её целиком, и это лучше отложить до конца жеста
      if (sameFigure) {
        renderChart(newRange);
        return;
      }

      relayoutTimer = setTimeout(function apply() {
        // сборка с диапазоном из layout вернула бы экран к нему и откатила начатый зум: пока жест идёт или
        // пока Plotly не записал ось, там лежит значение до жеста
        if (zoomPending()) {
          relayoutTimer = setTimeout(apply, RELAYOUT_DEBOUNCE_MS);
          return;
        }
        const now = gd.layout.xaxis.range;
        renderChart(now ? [now[0], now[1]] : null);
      }, RELAYOUT_DEBOUNCE_MS);
    });
  }

}

export function setVotes(list) {
  votesByDay = new Map(list.map(v => [v.day, v]));
}

export function setVerdicts(list) {
  verdictsByDay = new Map(list.map(v => [v.day, v]));
}

export function setData(body) {
  lastData = body;
  // данные другие, фигуру надо построить заново, какой бы ни была подпись
  lastFigure = null;
}

export function getRange() {
  return lastRenderedRange;
}
