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

// те же типы, что SIGNIFICANT_TYPES в web/app.py - крупные
// независимо от веса при адаптивной плотности (ниже)
const MAJOR_TYPES = new Set(['patch', 'season_start', 'expansion']);

// события платформы не привязаны к игре: bandColor - приглушённая
// полоса-фон, markerColor - тот же оттенок для маркера, насыщеннее
const PLATFORM_TYPES = {
  sale:   { bandColor: '#9c916f', markerColor: '#d4b106', label: 'распродажа Steam' },
  awards: { bandColor: '#8b8298', markerColor: '#9b6fd6', label: 'Steam Awards' },
  fest:   { bandColor: '#6f8f96', markerColor: '#4fc3d9', label: 'Steam Fest' }
};

// короткое имя события из заголовка заметки: в тултипе нужен
// "Steam Summer Sale", а не весь пресс-заголовок
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

function truncate(s, n) {
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

// на широком диапазоне мелкие события прячем, иначе сливаются
// в сплошную полосу; на узком (< 60 дней) показываем всё
function densityThreshold(days) {
  if (days > 365) return 5;
  if (days >= 180) return 2;
  if (days >= 60) return 1;
  return 0;
}

function densityFilter(days) {
  const limit = densityThreshold(days);
  if (!limit) return () => true;
  return e => (e.weight ?? 0) >= limit || MAJOR_TYPES.has(e.type);
}

// фильтров два, и подпись обязана описывать оба: порог из формы
// сервер применяет ко всем событиям без исключений, порог плотности
// применяется на клиенте, и патчи, сезоны и дополнения его обходят
function eventFilterLabel(days, minWeight) {
  const limit = densityThreshold(days);
  if (!minWeight && !limit) return 'показаны все события';
  if (!minWeight) return `показаны события с весом ≥ ${limit} или патч/сезон/дополнение`;
  if (limit > minWeight) {
    return `показаны события с весом ≥ ${limit}, ` +
           `патчи, сезоны и дополнения - от ${minWeight}`;
  }
  return `показаны события с весом ≥ ${minWeight}`;
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

// подсветка по наведению на строку таблицы: restyle нужных точек
// вместо перерисовки всего графика
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

// Plotly отдаёт границу оси то с временем, то без - сравниваем
// по первым 10 символам, ISO-дата сравнивается как строка
function dayInRange(day, range) {
  if (!range) return true;
  const lo = String(range[0]).slice(0, 10);
  const hi = String(range[1]).slice(0, 10);
  return day >= lo && day <= hi;
}

// cps приходит ПОЛНЫМ списком, не отфильтрованным: data-idx строки
// должен остаться индексом в нём же, по нему ищется ромб на графике
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
      'нет - расширьте диапазон или сбросьте зум двойным кликом</div>';
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

// перерисовка по уже загруженным данным (range = null - вся история):
// зум и панорамирование пересчитывают слои событий без похода на сервер
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
  const minWeight = parseFloat(document.getElementById('minWeight').value) || 0;

  const visibleCpCount = cps.filter(c => dayInRange(c.day, effectiveRange)).length;
  const cpCountText = visibleCpCount === cps.length
    ? `переломов: ${cps.length}`
    : `переломов: ${visibleCpCount} из ${cps.length}`;

  document.getElementById('info').textContent =
    `окно ${data.window} дн., медиана ${data.median_volume} отзывов/день, ` +
    `${cpCountText}; ${eventFilterLabel(windowDays, minWeight)}`;

  renderChangePointList(cps, effectiveRange);

  const cpIndex = {};
  days.forEach((d, i) => cpIndex[d] = i);

  // события по дням - только те, что проходят фильтр плотности
  const visibleEvents = data.events.filter(keepEvent);

  const byDay = {};
  visibleEvents.forEach(e => {
    (byDay[e.day] = byDay[e.day] || []).push(e);
  });

  // фоновые полосы игровых событий - по дню публикации
  const eventShapes = Object.entries(byDay).map(([day, items]) => ({
    type: 'rect',
    x0: day, x1: shiftDay(day, 1),
    yref: 'paper', y0: 0, y1: 1,
    fillcolor: TYPES[items[0].type]?.color || '#6b7684',
    opacity: 0.14,
    line: { width: 0 },
    layer: 'below'
  }));

  // полоса шириной в окно поиска (±3 дня), дата приблизительная.
  // Плотностью не фильтруем: их 80 на 12 лет, в кашу не сливаются
  const platformEvents = data.platform_events || [];
  const showPlatform = document.getElementById('showPlatform').checked;

  const platformShapes = showPlatform ? platformEvents.map(e => ({
    type: 'rect',
    x0: shiftDay(e.date, -3), x1: shiftDay(e.date, 4),
    yref: 'paper', y0: 0, y1: 1,
    fillcolor: PLATFORM_TYPES[e.type]?.bandColor || '#6b7684',
    opacity: 0.05,
    line: { width: 0 },
    layer: 'below'  // под данными - фон, не поверх линии
  })) : [];

  // shapes в Plotly не дают тултип, поэтому дата рядом ещё и точкой:
  // квадрат ниже треугольников игровых событий
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

  // тонкие стебли от маркера перелома вниз к оси - точнее видно дату
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

  // отдельная серия на каждый тип - даёт кликабельную легенду
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
    // размер общий с миниатюрой rangeslider (Plotly не различает) -
    // уменьшен, чтобы в ней не было каши
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

  // один ромб на перелом: разрешение внутри суток данными не
  // подкреплено, зерно дневное. Цвет - по событию с наибольшим весом,
  // остальные типы перечисляются в тултипе цветными строками
  const cpX = [], cpY = [], cpColor = [], cpSize = [], cpLine = [], cpText = [];
  cpMarkerIndices = [];

  cps.forEach(c => {
    const baseY = values[cpIndex[c.day]];
    const myIndices = [];
    cpMarkerIndices.push(myIndices);
    if (baseY === undefined || baseY === null) return;

    const dir = c.score < 0 ? 'спад' : 'рост';
    const edge = c.score < 0 ? '#ff4d3d' : '#3ddc84';
    // уменьшен по той же причине, что треугольники выше -
    // общий размер с миниатюрой rangeslider
    const size = Math.min(7 + Math.abs(c.score) * 0.15, 11);

    const minorLine = c.events_minor.length
      ? `<br>и ещё ${c.events_minor.length} событий`
      : '';
    const platformLine = c.platform_event
      ? `<br><b>платформа:</b> ${platformEventLabel(c.platform_event)}`
      : '';

    const kinds = [...new Set(c.events.map(e => e.type))];

    let color = '#3a4048';
    let body;

    if (kinds.length === 0) {
      body = c.events_minor.length
        ? `${c.events_minor.length} фоновых событий рядом`
        : 'событий рядом нет';
    } else {
      const strongest = c.events.reduce(
        (a, e) => (e.weight ?? 0) > (a.weight ?? 0) ? e : a, c.events[0]);
      color = TYPES[strongest.type]?.color || '#6b7684';

      // цвет строки в тултипе Plotly задаётся только через span:
      // фон и рамки он игнорирует, поэтому маркер типа - символом
      body = kinds.map(k => {
        const titles = c.events.filter(e => e.type === k)
          .map(e => e.title).join('<br>');
        const kc = TYPES[k]?.color || '#6b7684';
        return `<span style="color:${kc}">◆ ${TYPES[k]?.label || k}:</span>` +
               `<br>${titles}`;
      }).join('<br>');
      body += minorLine;
    }

    cpX.push(c.day); cpY.push(baseY);
    cpColor.push(color); cpSize.push(size); cpLine.push(edge);
    myIndices.push(cpX.length - 1);
    cpText.push(`<b>${dir} ${c.score} п.п.</b><br>${body}${platformLine}`);
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
      // толще и контрастнее, чтобы читалась поверх маркеров
      // в миниатюре rangeslider (см. комментарий у него ниже)
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
      // rangeslider зеркалит все трейсы общей оси, исключить трейс
      // точечно Plotly не даёт - отсюда размеры маркеров и линии выше
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

  // копией, а не ссылкой: переданный массив Plotly держит как свой
  // xaxis.range и меняет на месте, поэтому сравнение с ним в
  // обработчике ниже всегда давало равенство и гасило перерисовку
  lastRenderedRange = effectiveRange ? effectiveRange.slice() : null;

  // zoom, pan, rangeslider и кнопки периода приходят сюда одним
  // plotly_relayout - перерисовываем только клиентские слои
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

  const res = await fetch(`/api/data?app_id=${appId}&smoothing=${smoothing}` +
    `&min_weight=${minWeight}&sensitivity=${sensitivity}`);

  lastData = await res.json();
  renderChart(null);
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

// токен есть, только если задан в окружении сервера - без него
// форма работает как раньше, заголовок не отправляется
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

    // PENDING / STARTED - задача в очереди, прогресса ещё нет
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
      // сбор уже идёт у другой игры - подписываемся на её прогресс
      // тем же pollTask, чтобы видеть реальный ход
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
