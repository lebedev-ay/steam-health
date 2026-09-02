const TYPES = {
  patch:        { color: '#ff6b5b', label: 'патчи' },
  season_start: { color: '#b07de8', label: 'сезоны' },
  expansion:    { color: '#ffb03a', label: 'дополнения' },
  beta:         { color: '#4aa3e0', label: 'бета' },
  marketing:    { color: '#8a95a3', label: 'маркетинг' },
  press:        { color: '#2dbd9e', label: 'пресса' },
  blog:         { color: '#7d8a99', label: 'блоги' },
  service:      { color: '#5a6472', label: 'служебное' },
  announce:     { color: '#c9a227', label: 'анонсы' },
  unknown:      { color: '#6b7684', label: 'прочее' }
};

// те же типы, что SIGNIFICANT_TYPES в web/app.py — считаются
// крупными независимо от веса при адаптивной плотности (ниже)
const MAJOR_TYPES = new Set(['patch', 'season_start', 'expansion']);

// платформенные события (appid 753): не привязаны к конкретной
// игре, показываются широкой полосой, а не маркером на кривой
// приглушённые: почти серые, с лёгким оттенком — фон, не главное
// bandColor — приглушённая полоса-фон; markerColor — тот же оттенок,
// но насыщеннее, для отдельного трейса с маркерами (see below)
const PLATFORM_TYPES = {
  sale:   { bandColor: '#9c916f', markerColor: '#d4b106', label: 'распродажа Steam' },
  awards: { bandColor: '#8b8298', markerColor: '#9b6fd6', label: 'Steam Awards' },
  fest:   { bandColor: '#6f8f96', markerColor: '#4fc3d9', label: 'Steam Fest' }
};

// вытаскивает короткое имя события из полного заголовка заметки —
// в тултипе нужен "Steam Summer Sale", а не весь пресс-заголовок
function platformEventLabel(e) {
  if (e.type === 'awards') return 'Steam Awards';

  if (e.type === 'sale') {
    const m = e.title.match(
      /\b(summer|winter|spring|autumn|fall|holiday|black friday|halloween|lunar new year|chinese new year|christmas)\s+(?:steam\s+)?sale\b/i);
    const season = m ? m[1].replace(/\b\w/g, c => c.toUpperCase()) : null;
    return season ? `Steam ${season} Sale` : 'Steam Sale';
  }

  if (e.type === 'fest') {
    const m = e.title.match(/\b(\w+)\s+fest\b/i);
    const name = m ? m[1].replace(/\b\w/g, c => c.toUpperCase()) : null;
    return name ? `${name} Fest` : 'Steam Fest';
  }

  return e.title;
}

function shiftDay(day, n) {
  const d = new Date(day);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function shiftHours(day, h) {
  const d = new Date(day + 'T00:00:00');
  d.setHours(d.getHours() + h);
  return d.toISOString().slice(0, 19);
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

// адаптивная плотность событий: на широком диапазоне (месяцы, годы)
// мелкие события прячем, иначе они сливаются в сплошную полосу —
// на узком диапазоне (< 60 дней) показываем всё
function densityFilter(days) {
  const w = e => e.weight ?? 0;
  if (days > 365) return e => w(e) >= 5 || MAJOR_TYPES.has(e.type);
  if (days >= 180) return e => w(e) >= 2 || MAJOR_TYPES.has(e.type);
  if (days >= 60) return e => w(e) >= 1 || MAJOR_TYPES.has(e.type);
  return () => true;
}

function densityLabel(days) {
  if (days > 365) return 'показаны значимые события (вес ≥ 5 или патч/сезон/дополнение)';
  if (days >= 180) return 'показаны значимые события (вес ≥ 2 или патч/сезон/дополнение)';
  if (days >= 60) return 'показаны события с весом ≥ 1 или патч/сезон/дополнение';
  return 'показаны все события';
}

let lastData = null;
let cpMarkerIndices = [];
let cpBaseMarker = null;
let lastRenderedRange = null;
let relayoutBound = false;
let relayoutTimer = null;

function cpTraceIndex() {
  return document.getElementById('sentiment').data.findIndex(t => t.name === 'Переломы');
}

// подсветка маркера при наведении на строку таблицы переломов:
// временно укрупняем size/line.width у нужных точек через restyle,
// без перерисовки всего графика
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

function mainEventLabel(c) {
  if (c.events.length) {
    return `${TYPES[c.events[0].type]?.label || c.events[0].type}: ${truncate(c.events[0].title, 70)}`;
  }
  if (c.platform_event) {
    return `платформа: ${platformEventLabel(c.platform_event)}`;
  }
  if (c.events_minor.length) {
    return `${c.events_minor.length} фоновых событий`;
  }
  return '—';
}

// границы оси Plotly отдаёт то "2025-05-01", то "2025-05-01
// 12:00:00.5" — берём только календарную дату (первые 10 символов,
// ISO YYYY-MM-DD сравнивается как строка корректно) и сравниваем
// с ней c.day, у которого времени не бывает. Включительно с обеих
// сторон: день считается видимым, если хоть частично попал в диапазон
function dayInRange(day, range) {
  if (!range) return true;
  const lo = String(range[0]).slice(0, 10);
  const hi = String(range[1]).slice(0, 10);
  return day >= lo && day <= hi;
}

// список переломов под графиком: клик — зум ±30 дней, наведение —
// подсветка маркера (см. highlightChangePoint). cps — ПОЛНЫЙ список
// (не только видимые) — data-idx у строки обязан остаться индексом
// в нём же, потому что по этому индексу cpMarkerIndices в renderChart
// находит нужный ромб на графике. Отфильтровать cps перед вызовом
// и передать сюда урезанный массив — значит разъехаться с индексами
function renderChangePointList(cps, range) {
  const el = document.getElementById('cpList');

  if (!cps.length) {
    el.innerHTML = '<div class="cp-empty">переломов не найдено</div>';
    return;
  }

  const visible = cps
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => dayInRange(c.day, range));

  if (!visible.length) {
    el.innerHTML = '<div class="cp-empty">в видимом диапазоне переломов ' +
      'нет — расширьте диапазон или сбросьте зум двойным кликом</div>';
    return;
  }

  const rows = visible.map(({ c, i }) => {
    const dir = c.score < 0 ? 'спад' : 'рост';
    const dirClass = c.score < 0 ? 'cp-down' : 'cp-up';
    const dateStr = new Date(c.day + 'T00:00:00').toLocaleDateString('ru-RU');
    return `<tr class="cp-row" data-idx="${i}">
      <td>${dateStr}</td>
      <td class="${dirClass}">${dir}</td>
      <td class="${dirClass}">${Math.abs(c.score)} п.п.</td>
      <td>${mainEventLabel(c)}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `<table>
    <thead><tr><th>Дата</th><th>Напр.</th><th>Величина</th><th>Главное событие</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;

  el.querySelectorAll('.cp-row').forEach(row => {
    const idx = +row.dataset.idx;
    const c = cps[idx];
    row.addEventListener('click', () => {
      Plotly.relayout('sentiment', {
        'xaxis.range': [shiftDay(c.day, -30), shiftDay(c.day, 30)]
      });
    });
    row.addEventListener('mouseenter', () => highlightChangePoint(idx));
    row.addEventListener('mouseleave', unhighlightChangePoint);
  });
}

// таблица влияния событий — про весь собранный период, не про
// видимый диапазон (в отличие от таблицы переломов), поэтому
// строится один раз в load(), не в renderChart. Клик — тот же
// зум ±30 дней, что и у строки перелома
function renderEventImpact(events) {
  const el = document.getElementById('eventImpact');

  if (!events.length) {
    el.innerHTML = '<div class="cp-empty">заметных сдвигов не нашлось — ' +
      'либо у игры не было резких скачков настроения (это нормально), ' +
      'либо не набралось событий с двумя полными окнами и достаточным ' +
      'объёмом отзывов (мало патчей или история собрана недавно)</div>';
    return;
  }

  const rows = events.map(e => {
    const dirClass = e.shift < 0 ? 'cp-down' : 'cp-up';
    const dateStr = new Date(e.day + 'T00:00:00').toLocaleDateString('ru-RU');
    const sign = e.shift > 0 ? '+' : '';
    return `<tr class="cp-row" data-day="${e.day}">
      <td>${dateStr}</td>
      <td>${TYPES[e.type]?.label || e.type}</td>
      <td>${truncate(e.title, 60)}</td>
      <td>${e.before_pct}%</td>
      <td>${e.after_pct}%</td>
      <td class="${dirClass}">${sign}${e.shift} п.п.</td>
    </tr>`;
  }).join('');

  el.innerHTML = `<table>
    <thead><tr>
      <th>Дата</th><th>Тип</th><th>Заголовок</th>
      <th>Позитив до</th><th>Позитив после</th><th>Сдвиг</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;

  el.querySelectorAll('.cp-row').forEach(row => {
    const day = row.dataset.day;
    row.addEventListener('click', () => {
      Plotly.relayout('sentiment', {
        'xaxis.range': [shiftDay(day, -30), shiftDay(day, 30)]
      });
    });
  });
}

// рисует/перерисовывает график для уже загруженных данных (lastData).
// range — видимый диапазон оси X (null = вся история). Вызывается
// и при первой загрузке, и при зуме/панорамировании — без похода
// на сервер, только пересчёт клиентских слоёв событий
function renderChart(range) {
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

  const effectiveRange = range || (days.length ? [days[0], days[days.length - 1]] : undefined);
  const windowDays = effectiveRange
    ? Math.abs(new Date(effectiveRange[1]) - new Date(effectiveRange[0])) / 86400000
    : Infinity;
  const keepEvent = densityFilter(windowDays);

  const visibleCpCount = cps.filter(c => dayInRange(c.day, effectiveRange)).length;
  const cpCountText = visibleCpCount === cps.length
    ? `переломов: ${cps.length}`
    : `переломов: ${visibleCpCount} из ${cps.length}`;

  document.getElementById('info').textContent =
    `окно ${data.window} дн., медиана ${data.median_volume} отзывов/день, ` +
    `${cpCountText}; ${densityLabel(windowDays)}`;

  renderChangePointList(cps, effectiveRange);

  const cpIndex = {};
  days.forEach((d, i) => cpIndex[d] = i);

  // события по дням — только те, что проходят фильтр плотности
  const visibleEvents = data.events.filter(keepEvent);

  const byDay = {};
  visibleEvents.forEach(e => {
    (byDay[e.day] = byDay[e.day] || []).push(e);
  });

  // фоновые полосы игровых событий — по дню публикации
  const eventShapes = Object.entries(byDay).map(([day, items]) => ({
    type: 'rect',
    x0: day, x1: shiftDay(day, 1),
    yref: 'paper', y0: 0, y1: 1,
    fillcolor: TYPES[items[0].type]?.color || '#6b7684',
    opacity: 0.14,
    line: { width: 0 },
    layer: 'below'
  }));

  // платформенные события — широкие полосы шириной в окно поиска
  // (±3 дня), дата в базе приблизительная, см. docs/decisions.md.
  // Плотностью не фильтруются: их всего 80 на 12 лет по всем играм,
  // сплошной полосой не сливаются даже на полном диапазоне
  const platformEvents = data.platform_events || [];
  const showPlatform = document.getElementById('showPlatform').checked;

  const platformShapes = showPlatform ? platformEvents.map(e => ({
    type: 'rect',
    x0: shiftDay(e.date, -3), x1: shiftDay(e.date, 4),
    yref: 'paper', y0: 0, y1: 1,
    fillcolor: PLATFORM_TYPES[e.type]?.bandColor || '#6b7684',
    opacity: 0.05,
    line: { width: 0 },
    layer: 'below'  // под данными — фон, не поверх линии
  })) : [];

  // маркеры платформенных событий: полосы (shapes) в Plotly не
  // дают тултип, поэтому дата рядом ещё и точкой — квадрат ниже
  // треугольников игровых событий (те на topY), насыщеннее полосы
  const platformMarkerY = topY - Math.max((topY - floorY) * 0.10, 1);

  const platformMarkerTrace = {
    x: platformEvents.map(e => e.date),
    y: platformEvents.map(() => platformMarkerY),
    mode: 'markers',
    name: 'события Steam',
    marker: {
      size: 8,
      symbol: 'square',
      color: platformEvents.map(e => PLATFORM_TYPES[e.type]?.markerColor || '#6b7684'),
      line: { color: '#14161a', width: 1 }
    },
    text: platformEvents.map(e =>
      `${PLATFORM_TYPES[e.type]?.label || e.type}<br>${e.title}`),
    hovertemplate: '%{x|%d.%m.%Y}<br>%{text}<extra></extra>'
  };

  // тонкие стебли от маркера перелома вниз к оси — точнее видно дату
  const cpStems = cps
    .filter(c => values[cpIndex[c.day]] !== undefined && values[cpIndex[c.day]] !== null)
    .map(c => ({
      type: 'line',
      xref: 'x', x0: c.day, x1: c.day,
      yref: 'y', y0: floorY, y1: values[cpIndex[c.day]],
      line: { color: '#5a6472', width: 1, dash: 'dot' },
      layer: 'above'
    }));

  const shapes = [...eventShapes, ...platformShapes, ...cpStems];

  // отдельная серия на каждый тип — даёт кликабельную легенду
  const byType = {};
  visibleEvents.forEach(e => {
    (byType[e.type] = byType[e.type] || []).push(e);
  });

  const eventTraces = Object.entries(byType).map(([type, items]) => ({
    x: items.map(e => e.day),
    y: items.map(() => topY),
    mode: 'markers',
    name: TYPES[type]?.label || type,
    legendgroup: type,
    // размер маркера общий для основного графика и миниатюры
    // rangeslider (Plotly не различает) — уменьшен, чтобы в ней
    // не было каши; линия настроения там компенсирует толщиной
    marker: {
      size: 7, symbol: 'triangle-down',
      color: TYPES[type]?.color || '#6b7684',
      line: { color: '#14161a', width: 1 }
    },
    text: items.map(e => e.weight
      ? `${TYPES[type]?.label || type} ×${e.weight}<br>${e.title}`
      : `${TYPES[type]?.label || type}<br>${e.title}`),
    hovertemplate: '%{x}<br>%{text}<extra></extra>'
  }));

  // точки перелома: по ромбу на каждый тип значимого события рядом.
  // фоновые события (events_minor) в перечисление не идут — только
  // счётчиком. cpMarkerIndices — какие индексы в cpX/cpY относятся
  // к какой точке перелома, нужно для подсветки из списка
  const cpX = [], cpY = [], cpColor = [], cpSize = [], cpLine = [], cpText = [];
  cpMarkerIndices = [];

  cps.forEach(c => {
    const baseY = values[cpIndex[c.day]];
    const myIndices = [];
    cpMarkerIndices.push(myIndices);
    if (baseY === undefined || baseY === null) return;

    const dir = c.score < 0 ? 'спад' : 'рост';
    const edge = c.score < 0 ? '#ff4d3d' : '#3ddc84';
    // уменьшен по той же причине, что маркеры-треугольники выше —
    // общий размер с миниатюрой rangeslider
    const size = Math.min(7 + Math.abs(c.score) * 0.15, 11);

    const minorLine = c.events_minor.length
      ? `<br>и ещё ${c.events_minor.length} событий`
      : '';
    const platformLine = c.platform_event
      ? `<br><b>платформа:</b> ${platformEventLabel(c.platform_event)}`
      : '';

    const kinds = [...new Set(c.events.map(e => e.type))];

    if (kinds.length === 0) {
      cpX.push(c.day); cpY.push(baseY);
      cpColor.push('#3a4048'); cpSize.push(size);
      cpLine.push(edge);
      myIndices.push(cpX.length - 1);
      const head = c.events_minor.length
        ? `${c.events_minor.length} фоновых событий рядом`
        : 'событий рядом нет';
      cpText.push(`<b>${dir} ${c.score} п.п.</b><br>${head}${platformLine}`);
      return;
    }

    // несколько ромбов, разнесённых по времени внутри суток
    const step = 24 / (kinds.length + 1);
    kinds.forEach((k, i) => {
      cpX.push(shiftHours(c.day, Math.round(step * (i + 1))));
      cpY.push(baseY);
      cpColor.push(TYPES[k]?.color || '#6b7684');
      cpSize.push(size);
      cpLine.push(edge);
      myIndices.push(cpX.length - 1);
      const titles = c.events.filter(e => e.type === k)
        .map(e => e.title).join('<br>');
      cpText.push(
        `<b>${dir} ${c.score} п.п.</b><br>` +
        `${TYPES[k]?.label || k}:<br>${titles}${minorLine}${platformLine}`);
    });
  });

  const cpLineWidth = cpX.map(() => 2.5);
  cpBaseMarker = { size: cpSize.slice(), lineWidth: cpLineWidth.slice() };

  const changePoints = {
    x: cpX, y: cpY,
    mode: 'markers',
    name: 'Переломы',
    marker: {
      size: cpSize,
      symbol: 'diamond',
      color: cpColor,
      line: { color: cpLine, width: cpLineWidth }
    },
    text: cpText,
    hovertemplate: '%{x|%d.%m.%Y}<br>%{text}<extra></extra>'
  };

  Plotly.react('sentiment', [
    {
      x: days, y: totals, type: 'bar', name: 'Отзывов',
      yaxis: 'y2',
      marker: { color: 'rgba(110,150,190,0.28)' },
      hovertemplate: '%{x}<br>Отзывов: %{y}<extra></extra>'
    },
    {
      x: days, y: values, mode: 'lines',
      name: isDelta ? 'Отклонение, п.п.' : 'Позитивных, %',
      // толще и контрастнее — чтобы читалась поверх маркеров
      // в миниатюре rangeslider (см. комментарий у rangeslider ниже)
      line: { color: '#f0f4f8', width: 3.5, shape: 'spline', smoothing: 0.4 },
      customdata: totals,
      hovertemplate: isDelta
        ? '%{x}<br>Отклонение: %{y} п.п.<br>Отзывов: %{customdata}<extra></extra>'
        : '%{x}<br>Позитив: %{y}%<br>Отзывов: %{customdata}<extra></extra>'
    },
    ...eventTraces,
    ...(showPlatform ? [platformMarkerTrace] : []),
    changePoints
  ], {
    title: {
      text: isDelta
        ? 'Отклонение настроения от обычного уровня'
        : 'Настроение и объём отзывов',
      font: { size: 17 }
    },
    shapes: shapes,
    height: 640,
    paper_bgcolor: '#262b33',
    plot_bgcolor: '#1e232a',
    font: { color: '#c7d0d9' },
    margin: { t: 110, r: 60, b: 60, l: 60 },
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
      // rangeslider зеркалит в миниатюре все трейсы общей оси —
      // Plotly не даёт исключить трейс из неё точечно. Компромисс:
      // маркеры событий/переломов уменьшены (см. их size выше),
      // линия настроения — потолще и контрастнее (см. её trace),
      // чтобы читалась поверх. Кнопки периода рядом — не мешают,
      // дублируют часть навигации, но это ускоряет частые переходы
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
    hovermode: 'closest',
    legend: { orientation: 'h', y: 1.10, bgcolor: 'rgba(0,0,0,0)' }
  }, { responsive: true });

  lastRenderedRange = effectiveRange;

  // подписка один раз: zoom/pan/rangeslider/кнопки периода/сброс
  // двойным кликом — всё приходит сюда как plotly_relayout
  // с новым xaxis.range. Перерисовываем только клиентские слои
  // событий, без похода на сервер (см. renderChart выше)
  if (!relayoutBound) {
    relayoutBound = true;
    document.getElementById('sentiment').on('plotly_relayout', () => {
      clearTimeout(relayoutTimer);
      relayoutTimer = setTimeout(() => {
        const gd = document.getElementById('sentiment');
        const xr = gd.layout.xaxis.range;
        const newRange = xr ? [xr[0], xr[1]] : null;
        if (JSON.stringify(newRange) === JSON.stringify(lastRenderedRange)) return;
        renderChart(newRange);
      }, 120);
    });
  }
}

async function load() {
  const appId = document.getElementById('game').value;
  const smoothing = document.getElementById('smoothing').value;
  const sensitivity = document.getElementById('sensitivity').value;
  const minWeight = document.getElementById('minWeight').value;

  const [dataRes, impactRes] = await Promise.all([
    fetch(`/api/data?app_id=${appId}&smoothing=${smoothing}` +
      `&min_weight=${minWeight}&sensitivity=${sensitivity}`),
    fetch(`/api/event_impact?app_id=${appId}`)
  ]);
  const data = await dataRes.json();
  const impact = await impactRes.json();

  lastData = data;
  renderChart(null);
  renderEventImpact(impact.events || []);
}

const CONTROL_IDS = ['game', 'smoothing', 'sensitivity', 'minWeight', 'mode', 'showPlatform'];

function setControlsDisabled(disabled) {
  CONTROL_IDS.forEach(id => { document.getElementById(id).disabled = disabled; });
}

async function loadSafe() {
  const overlay = document.getElementById('loadingOverlay');
  const errorBox = document.getElementById('errorBox');
  const chart = document.getElementById('sentiment');

  setControlsDisabled(true);
  errorBox.style.display = 'none';
  chart.style.display = '';
  overlay.style.display = 'flex';

  try {
    await load();
  } catch (e) {
    chart.style.display = 'none';
    errorBox.textContent = 'Не удалось загрузить данные: ' + e.message;
    errorBox.style.display = 'flex';
  } finally {
    overlay.style.display = 'none';
    setControlsDisabled(false);
  }
}

CONTROL_IDS.forEach(id => document.getElementById(id).addEventListener('change', loadSafe));
loadSafe();

// --- фоновый сбор данных по игре ---

const COLLECT_STORAGE_KEY = 'steamHealthCollectTask';

// токен есть только если он задан в окружении сервера - без него
// форма работает как раньше, заголовок просто не отправляется
const COLLECT_TOKEN =
  document.querySelector('meta[name="collect-token"]')?.content || '';

function setCollectRunning(running) {
  document.getElementById('collectBtn').disabled = running;
  document.getElementById('collectAppId').disabled = running;
  document.getElementById('collectMode').disabled = running;
}

function showCollectProgress(text, kind) {
  const el = document.getElementById('collectProgress');
  el.innerHTML = (kind === 'busy' ? '<span class="spinner-sm"></span>' : '') + text;
  el.style.color = kind === 'error' ? '#ff6b5b' : (kind === 'ok' ? '#3ddc84' : '#8a95a3');
}

async function refreshGamesList(appId) {
  const res = await fetch('/api/games');
  const list = await res.json();
  const select = document.getElementById('game');
  const current = select.value;

  select.innerHTML = list
    .map(g => `<option value="${g.app_id}">${g.game_name}${g.collection_status === 'partial' ? ' (данные неполные)' : ''}</option>`)
    .join('');

  const wanted = appId != null ? String(appId) : current;
  if ([...select.options].some(o => o.value === wanted)) {
    select.value = wanted;
  }

  // зовётся только после успешного сбора: данные собранной игры
  // изменились, поэтому график перерисовываем всегда
  if (select.options.length) loadSafe();
}

function pollTask(taskId) {
  setCollectRunning(true);

  const tick = async () => {
    let body;
    try {
      const res = await fetch(`/api/task/${taskId}`);
      body = await res.json();
    } catch (e) {
      showCollectProgress('нет связи с сервером, пробую ещё раз…', 'busy');
      setTimeout(tick, 2000);
      return;
    }

    if (body.state === 'PROGRESS' && body.meta) {
      const m = body.meta;
      const extra = m.progress ? ` (${m.progress})` : '';
      showCollectProgress(`шаг ${m.step}/${m.total}: ${m.message}${extra}`, 'busy');
      setTimeout(tick, 2000);
      return;
    }

    if (body.state === 'SUCCESS') {
      showCollectProgress(`готово: ${body.result?.name || 'игра собрана'}`, 'ok');
      setCollectRunning(false);
      localStorage.removeItem(COLLECT_STORAGE_KEY);
      refreshGamesList(body.result?.app_id);
      return;
    }

    if (body.state === 'FAILURE') {
      showCollectProgress(`ошибка: ${body.error || 'сбор не удался'}`, 'error');
      setCollectRunning(false);
      localStorage.removeItem(COLLECT_STORAGE_KEY);
      return;
    }

    // PENDING / STARTED — задача в очереди, прогресса ещё нет
    showCollectProgress('задача поставлена в очередь…', 'busy');
    setTimeout(tick, 2000);
  };

  tick();
}

document.getElementById('collectBtn').addEventListener('click', async () => {
  const rawId = document.getElementById('collectAppId').value.trim();
  const mode = document.getElementById('collectMode').value;
  if (!rawId) return;

  setCollectRunning(true);
  showCollectProgress('запускаю…', 'busy');

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (COLLECT_TOKEN) headers['X-Collect-Token'] = COLLECT_TOKEN;

    const res = await fetch('/api/collect', {
      method: 'POST',
      headers,
      body: JSON.stringify({ app_id: rawId, mode })
    });
    const body = await res.json();

    if (res.status === 409) {
      // сбор уже идёт (у другой игры) — подписываемся на прогресс
      // занятой задачи тем же pollTask, чтобы видеть реальный ход
      showCollectProgress('сейчас идёт сбор другой игры, слежу за прогрессом…', 'busy');
      pollTask(body.busy_task_id);
      return;
    }

    if (!res.ok) {
      showCollectProgress(`ошибка: ${body.error || res.status}`, 'error');
      setCollectRunning(false);
      return;
    }

    localStorage.setItem(COLLECT_STORAGE_KEY, JSON.stringify({ taskId: body.task_id }));
    pollTask(body.task_id);
  } catch (e) {
    showCollectProgress('не удалось запустить сбор: ' + e.message, 'error');
    setCollectRunning(false);
  }
});

document.getElementById('collectAppId').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') document.getElementById('collectBtn').click();
});

// переживает случайную перезагрузку страницы во время сбора
(() => {
  const saved = localStorage.getItem(COLLECT_STORAGE_KEY);
  if (!saved) return;
  try {
    const { taskId } = JSON.parse(saved);
    if (taskId) pollTask(taskId);
  } catch (e) {}
})();
