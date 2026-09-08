import { shiftDay, esc, sameRange, dayInRange, plural } from './util.js';
import { TYPES, PLATFORM_TYPES, BACKGROUND_COLOR, platformEventLabel,
         densityFilter, eventFilterLabel } from './events.js';
import { renderChangePointList } from './cplist.js';

let lastData = null;
let cpMarkerIndices = [];
let cpBaseMarker = null;
let lastRenderedRange = null;
let relayoutBound = false;
let relayoutTimer = null;

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

// перерисовка по уже загруженным данным (range = null - вся история): зум и панорамирование пересчитывают слои событий без похода на сервер
export function renderChart(range) {
  const data = lastData;
  if (!data) return;

  const isDelta = document.getElementById('mode').value === 'delta';
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

  const cpIndex = {};
  days.forEach((d, i) => cpIndex[d] = i);

  const visibleEvents = data.events.filter(keepEvent);

  const byDay = {};
  visibleEvents.forEach(e => {
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

  const platformShapes = showPlatform ? platformEvents.map(e => ({
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
    marker: {
      size: 8,
      symbol: 'square',
      color: platformEvents.map(e => PLATFORM_TYPES[e.type]?.markerColor || BACKGROUND_COLOR),
      line: { color: '#14161a', width: 1 }
    },
    text: platformEvents.map(e =>
      `${PLATFORM_TYPES[e.type]?.label || e.type}<br>${esc(e.title)}`),
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
    // размер общий с миниатюрой rangeslider (Plotly не различает) - уменьшен, чтобы в ней не было каши
    marker: {
      size: 9, symbol: 'triangle-down',
      color: TYPES[type]?.color || BACKGROUND_COLOR,
      line: { color: '#14161a', width: 1 }
    },
    text: items.map(e => e.weight
      ? `${TYPES[type]?.label || type} ×${e.weight}<br>${esc(e.title)}`
      : `${TYPES[type]?.label || type}<br>${esc(e.title)}`),
    hovertemplate: '%{x}<br>%{text}<extra></extra>'
  }));

  // один ромб на перелом: разрешение внутри суток данными не подкреплено, зерно дневное. 
  // Цвет - по событию с наибольшим весом, остальные типы перечисляются в тултипе цветными строками
  const cpX = [], cpY = [], cpColor = [], cpSize = [], cpLine = [], cpText = [];
  cpMarkerIndices = [];

  cps.forEach(c => {
    const baseY = values[cpIndex[c.day]];
    const myIndices = [];
    cpMarkerIndices.push(myIndices);
    if (baseY === undefined || baseY === null) return;

    const dir = c.score < 0 ? 'спад' : 'рост';
    // ромб - точка на данных, и его собственное свойство это знак и величина сдвига. Тип причины виден по маркерам сверху и в тултипе, поэтому цвет здесь кодирует только направление и совпадает с таблицей
    const dirColor = c.score < 0 ? '#ff4d3d' : '#3ddc84';
    // уменьшен по той же причине, что треугольники выше -
    // общий размер с миниатюрой rangeslider
    const size = Math.min(7 + Math.abs(c.score) * 0.15, 11);

    const minorLine = c.events_minor.length
      ? `<br>и ещё ${c.events_minor.length} ` +
        `${plural(c.events_minor.length, 'событие', 'события', 'событий')}`
      : '';
    const platformLine = c.platform_event
      ? `<br><b>платформа:</b> ${esc(platformEventLabel(c.platform_event))}`
      : '';

    const kinds = [...new Set(c.events.map(e => e.type))];

    let body;

    if (kinds.length === 0) {
      body = c.events_minor.length
        ? `${c.events_minor.length} ` +
          `${plural(c.events_minor.length, 'фоновое событие', 'фоновых события', 'фоновых событий')}` +
          ' рядом'
        : 'событий рядом нет';
    } else {
      // цвет строки в тултипе Plotly задаётся только через span: фон и рамки он игнорирует, поэтому маркер типа - символом
      body = kinds.map(k => {
        const titles = c.events.filter(e => e.type === k)
          .map(e => esc(e.title)).join('<br>');
        const kc = TYPES[k]?.color || BACKGROUND_COLOR;
        return `<span style="color:${kc}">◆</span> ${TYPES[k]?.label || k}:` +
               `<br>${titles}`;
      }).join('<br>');
      body += minorLine;
    }

    cpX.push(c.day); cpY.push(baseY);
    cpColor.push(dirColor); cpSize.push(size); cpLine.push('#14161a');
    myIndices.push(cpX.length - 1);
    cpText.push(`<b>${dir} ${Math.abs(c.score)} п.п.</b><br>${body}${platformLine}`);
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
    showlegend: false,
    marker: {
      size: cpSize,
      symbol: 'diamond',
      color: cpColor,
      line: { color: cpLine, width: cpLineWidth }
    },
    text: cpText,
    // фон тултипа Plotly берёт из цвета маркера, и цветные строки внутри оказывались на цветном: коралловый на коралловом читался как пустая строка. Фон фиксирован, цвет типа остался в глифе
    hoverlabel: { bgcolor: '#262b33', bordercolor: '#3a4048', font: { color: '#c7d0d9' } },
    hovertemplate: '%{x|%d.%m.%Y}<br>%{text}<extra></extra>'
  };

  Plotly.react('sentiment', [
    {
      x: days, y: totals, type: 'bar', name: 'Отзывов',
      yaxis: 'y2',
      marker: { color: 'rgba(110,150,190,0.28)' },
      hovertemplate: '%{x}<br>Отзывов: %{y}<extra></extra>'
    },
    ...(isDelta ? [] : [{
      x: days, y: data.daily.map(d => d.base), mode: 'lines',
      name: 'База, медиана 90 дней',
      line: { color: '#8a95a3', width: 1.5, dash: 'dot' },
      hovertemplate: '%{x}<br>База: %{y}%<extra></extra>'
    }]),
    {
      x: days, y: values, mode: 'lines',
      name: isDelta ? 'Отклонение, п.п.' : 'Позитивных, %',
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
    margin: { t: 70, r: 60, b: 60, l: 60 },
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
        x: 0, xanchor: 'left', y: 1.20, yanchor: 'bottom',
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
    legend: { orientation: 'h', y: 1.06, bgcolor: 'rgba(0,0,0,0)' }
  // двойной клик выключен: на ряде в несколько лет случайное попадание выбрасывало
  // из выбранного окна. 'reset' здесь не помогает - при autorange: false Plotly не хранит
  // _rangeInitial и откатывается к автомасштабу. Полный сброс остался кнопкой «всё».
  // Колесо зумит; страница листается мимо графика, свободной высоты хватает
  }, { responsive: true, doubleClick: false, scrollZoom: true });

  // копия обязательна: переданный массив Plotly держит как свой xaxis.range и меняет на месте, так что ссылка на него всегда сравнивалась бы сама с собой
  lastRenderedRange = effectiveRange ? effectiveRange.slice() : null;

  // zoom, pan, rangeslider и кнопки периода приходят сюда одним plotly_relayout - перерисовываем только клиентские слои
  if (!relayoutBound) {
    relayoutBound = true;
    document.getElementById('sentiment').on('plotly_relayout', () => {
      clearTimeout(relayoutTimer);
      relayoutTimer = setTimeout(() => {
        const gd = document.getElementById('sentiment');
        const xr = gd.layout.xaxis.range;
        const newRange = xr ? [xr[0], xr[1]] : null;
        if (sameRange(newRange, lastRenderedRange)) return;
        renderChart(newRange);
      }, 120);
    });
  }
}

export function setData(body) {
  lastData = body;
}

export function getRange() {
  return lastRenderedRange;
}
