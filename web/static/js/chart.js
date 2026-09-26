import { DOWN, MOON, PLATFORM_TYPES, TIER_LABELS, UP, eventGroup, kindLabel } from './labels.js';
import { esc, shiftDay, truncate } from './util.js';

// цвета совпадают с токенами style.css: Plotly не читает CSS-переменные
const INK = '#e6e2d9', MUTED = '#736e7d', GRID = 'rgba(255,255,255,0.05)', SURFACE = '#141319';
const FONT = 'Onest, system-ui, sans-serif';
const MONO = 'JetBrains Mono, monospace';

// три полосы с общей осью дат: сверху дорожка событий, посередине доля позитива, снизу объём.
// Одна шкала на полосу - на общей объём и доля выглядели бы связанными, хотя их совмещение произвольно
const LANE = [0.88, 1], MAIN = [0.27, 0.84], VOLUME = [0, 0.18];

// плотность событий: засечка на каждые TICK_PX пикселей ширины и не ближе GAP_PX к более важной соседке,
// подпись - не чаще LABEL_PX, не больше LABELS и не у самого правого края, где она обрезалась бы
const TICK_PX = 30, GAP_PX = 7, LABEL_PX = 190, LABELS = 6, LABEL_EDGE_PX = 150;

// важность события для отбора: сезон и дополнение редки и заметны сами по себе, у патча - вес (длина патчноута к медиане),
// маркетинг и блоги - фон. Отклик в данных рядом поднимает любое событие: оно могло что-то сдвинуть
const TYPE_BASE = { season_start: 9, expansion: 9, patch: 2, beta: 1.5, press: 1.2, announce: 1,
                    marketing: 0.3, blog: 0.3, service: 0.2, unknown: 0.5 };
// С LLM-разметкой новостей основа - её уровень: масштаб события для игры по смыслу текста, а не по длине и заголовку
const TIER_BASE = { milestone: 60, major: 18, regular: 5, background: 0.6 };
const importance = e => (e.tier ? TIER_BASE[e.tier] : (TYPE_BASE[e.type] ?? 0.5) * (1 + Math.min(e.weight ?? 1, 10)))
  + (e.responsive ? 8 : 0);
const title = e => e.title_ru || e.title;

let data = null;
let lastSignature = '';

export function renderChart(gameData, { onPointClick, animate = false }) {
  data = gameData;
  lastSignature = '';
  draw(null);
  const chart = document.getElementById('chart');
  if (animate) drawIn(chart);

  chart.removeAllListeners?.('plotly_click');
  chart.removeAllListeners?.('plotly_relayout');
  chart.on('plotly_click', ev => {
    const pt = ev.points?.find(p => p.data.name === 'переломы');
    if (pt) onPointClick(String(pt.x).slice(0, 10));
  });
  // зум и сдвиг меняют видимый период - набор событий на дорожке пересчитывается под него
  let timer = null;
  chart.on('plotly_relayout', () => {
    clearTimeout(timer);
    timer = setTimeout(() => draw(chart.layout.xaxis.autorange ? null : chart.layout.xaxis.range), 150);
  });
}

// какие события видны: не больше бюджета по ширине, самые важные первыми; подписи - у самых важных, не внахлёст
function pickEvents(lo, hi, width) {
  const days = Math.max((Date.parse(hi) - Date.parse(lo)) / 864e5, 1);
  const inRange = data.events.filter(e => e.day >= lo && e.day <= hi);
  const budget = Math.max(Math.floor(width / TICK_PX), 8);
  const px = e => (Date.parse(e.day) - Date.parse(lo)) / 864e5 * width / days;

  // вехи - всегда, мимо бюджета и зазора: это события, ради которых игру и помнят. Остальное - жадно по важности,
  // засечка вплотную к уже взятой более важной сливалась бы с ней в одну
  const ranked = [...inRange].sort((a, b) => importance(b) - importance(a));
  const ticks = ranked.filter(e => e.tier === 'milestone');
  for (const e of ranked) {
    if (ticks.length >= budget) break;
    if (!ticks.includes(e) && ticks.every(t => Math.abs(px(t) - px(e)) >= GAP_PX)) ticks.push(e);
  }

  const labels = [];
  for (const e of ticks) {
    if (labels.length >= LABELS) break;
    if (importance(e) < 6 || px(e) > width - LABEL_EDGE_PX) continue;
    if (labels.every(l => Math.abs(px(l) - px(e)) >= LABEL_PX)) labels.push(e);
  }
  return { ticks, labels };
}

function draw(range) {
  const chart = document.getElementById('chart');
  const width = Math.max(chart.clientWidth - 60, 300);
  const [lo, hi] = range ? range.map(v => String(v).slice(0, 10)) : [data.daily[0].day, data.daily.at(-1).day];
  const { ticks, labels } = pickEvents(lo, hi, width);
  const signature = ticks.map(e => e.day + e.title).join('|') + '#' + labels.map(e => e.day).join('|');
  if (signature === lastSignature) return;
  lastSignature = signature;

  const days = data.daily.map(d => d.day);
  const pct = data.daily.map(d => d.pct);
  const pctByDay = new Map(data.daily.map(d => [d.day, d.pct]));

  // дорожка событий: засечки по группам, высота - важность. Отдельная трасса на группу даёт легенду с переключением.
  // Анонс будущего - бледнее: событие ещё не случилось, на кривую оно влиять не могло
  const byGroup = {};
  ticks.forEach(e => (byGroup[eventGroup(e).key] = byGroup[eventGroup(e).key] || []).push(e));
  const eventTraces = Object.values(byGroup).map(items => {
    const group = eventGroup(items[0]);
    return {
      x: items.map(e => e.day), y: items.map(() => 0.42), yaxis: 'y3',
      type: 'scatter', mode: 'markers', name: group.label, legendgroup: group.key,
      opacity: 1,
      marker: {
        symbol: 'line-ns', size: items.map(e => 10 + Math.min(importance(e), 26) * 0.72),
        line: { color: items.map(e => e.future ? `${group.color}80` : group.color), width: items.map(e => e.tier === 'milestone' ? 3 : 2.2) }
      },
      text: items.map(e => [
        esc(truncate(title(e), 80)),
        e.tier ? `${TIER_LABELS[e.tier]}, ${kindLabel(e.kind)}${e.future ? ', анонс' : ''}` : (e.weight ? `вес ${e.weight}` : null),
        e.title_ru ? `<span style="color:#736e7d">${esc(truncate(e.title, 70))}</span>` : null,
        e.responsive ? 'рядом отклик в отзывах' : null
      ].filter(Boolean).join('<br>')),
      hovertemplate: '%{text}<extra></extra>'
    };
  });

  const platform = data.platform_events.filter(e => e.day >= lo && e.day <= hi);
  const platformTrace = {
    x: platform.map(e => e.day), y: platform.map(() => 0.42), yaxis: 'y3',
    type: 'scatter', mode: 'markers', name: 'события Steam',
    marker: { symbol: 'line-ns', size: 12, line: { color: 'rgba(236,230,214,0.35)', width: 1.5 } },
    text: platform.map(e => `${PLATFORM_TYPES[e.type] || 'Steam'}: ${esc(truncate(e.title, 60))}`),
    hovertemplate: '%{text}<extra></extra>'
  };

  const cps = data.change_points.filter(c => pctByDay.get(c.day) != null);
  const colorOf = c => c.score < 0 ? DOWN : UP;
  const cpTrace = {
    x: cps.map(c => c.day), y: cps.map(c => pctByDay.get(c.day)),
    type: 'scatter', mode: 'markers', name: 'переломы', showlegend: false,
    // залитый ромб - по перелому есть проверенный разбор отзывов, контур - нет; кольцо цвета фона отделяет ромб от линии
    marker: {
      symbol: cps.map(c => c.verdict?.checked ? 'diamond' : 'diamond-open'),
      size: 13, color: cps.map(colorOf), line: { color: cps.map(c => c.verdict?.checked ? SURFACE : colorOf(c)), width: 2 }
    },
    text: cps.map(c => `${c.score < 0 ? '▼' : '▲'} ${Math.abs(c.score)} п.п.` +
      (c.positive_before != null ? ` · за неделю ${c.positive_before}% → ${c.positive_after}%` : '')),
    hovertemplate: '%{text}<extra>перелом</extra>'
  };
  const cpLegend = {
    x: [null], y: [null], type: 'scatter', mode: 'markers', name: 'переломы', hoverinfo: 'skip',
    marker: { symbol: 'diamond', size: 11, color: INK }
  };

  const traces = [
    {
      x: days, y: data.daily.map(d => d.base), type: 'scatter', mode: 'lines', name: 'норма игры',
      line: { color: '#7d7596', width: 1.2 }, hovertemplate: '%{y}<extra>норма</extra>'
    },
    {
      // uid даёт трассе постоянный класс в SVG: по нему находится линия для прорисовки
      uid: 'pulse', x: days, y: pct, type: 'scatter', mode: 'lines', name: 'позитивных, %',
      line: { color: MOON, width: 1.8, shape: 'spline', smoothing: 0.4 },
      hovertemplate: '<b>%{y}</b><extra>позитивных</extra>'
    },
    cpTrace,
    cpLegend,
    ...eventTraces,
    ...(platform.length ? [platformTrace] : []),
    {
      x: days, y: data.daily.map(d => d.total), type: 'bar', yaxis: 'y2', name: 'отзывов в день', showlegend: false,
      marker: { color: 'rgba(236,230,214,0.2)' }, hovertemplate: '%{y}<extra>отзывов</extra>'
    }
  ];

  // у подписанных событий - тонкая направляющая через основную полосу: видно, куда пришлось событие на кривой
  const guides = labels.map(e => ({
    type: 'line', xref: 'x', yref: 'paper', x0: e.day, x1: e.day, y0: MAIN[0], y1: LANE[0] + 0.03,
    line: { color: eventGroup(e).color, width: 1 }, opacity: e.tier === 'milestone' ? 0.5 : 0.3, layer: 'below'
  }));
  // события платформы - бледная полоса ±3 дня: дата у них приблизительная, по публикации заметки
  const bands = platform.map(e => ({
    type: 'rect', xref: 'x', yref: 'paper', x0: shiftDay(e.day, -3), x1: shiftDay(e.day, 4), y0: MAIN[0], y1: MAIN[1],
    fillcolor: '#ffffff', opacity: 0.022, line: { width: 0 }, layer: 'below'
  }));
  const laneLine = { type: 'line', xref: 'paper', yref: 'paper', x0: 0, x1: 1, y0: LANE[0] + 0.012, y1: LANE[0] + 0.012,
                     line: { color: 'rgba(255,255,255,0.08)', width: 1 } };
  const annotations = labels.map(e => ({
    x: e.day, xref: 'x', y: LANE[1], yref: 'paper', yanchor: 'top', xanchor: 'left', xshift: 5, showarrow: false,
    text: esc(truncate(title(e), 28)), font: { size: 10, color: INK, family: FONT }, opacity: e.tier === 'milestone' ? 0.95 : 0.7
  }));

  const axis = { gridcolor: GRID, zeroline: false, color: MUTED, fixedrange: true, tickfont: { family: MONO, size: 11 } };
  Plotly.react(chart, traces, {
    height: 520,
    // зум сохраняется между перерисовками дорожки событий: react с тем же uirevision не сбрасывает ось
    uirevision: data.game.app_id,
    margin: { t: 34, r: 12, b: 30, l: 46 },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: INK, family: FONT, size: 12 },
    legend: { orientation: 'h', y: -0.1, font: { color: MUTED } },
    hovermode: 'x unified',
    hoverlabel: { bgcolor: '#1a1920', bordercolor: 'rgba(255,255,255,0.14)', font: { color: INK, family: FONT } },
    dragmode: 'pan',
    shapes: [laneLine, ...bands, ...guides],
    annotations,
    xaxis: {
      anchor: 'y2', gridcolor: GRID, color: MUTED, hoverformat: '%d.%m.%Y', type: 'date', tickfont: { family: MONO, size: 11 },
      spikecolor: 'rgba(236,230,214,0.35)', spikethickness: 1, spikedash: 'solid',
      rangeselector: {
        x: 0, y: 1.02, yanchor: 'bottom', bgcolor: '#1a1920', activecolor: '#2c2b35', bordercolor: 'rgba(255,255,255,0.1)',
        borderwidth: 1, font: { color: INK, size: 11 },
        buttons: [
          { count: 3, label: '3 мес', step: 'month', stepmode: 'backward' },
          { count: 6, label: '6 мес', step: 'month', stepmode: 'backward' },
          { count: 1, label: 'год', step: 'year', stepmode: 'backward' },
          { step: 'all', label: 'всё' }
        ]
      }
    },
    yaxis: { ...axis, domain: MAIN, ticksuffix: '%' },
    yaxis2: { ...axis, domain: VOLUME, nticks: 3, title: { text: 'отзывов', font: { size: 11, color: MUTED } } },
    yaxis3: { domain: LANE, range: [0, 1], visible: false, fixedrange: true }
  }, { responsive: true, displayModeBar: false, scrollZoom: true, doubleClick: 'reset' });
}

// приблизить график ко дню: полтора месяца до и после
export function zoomTo(day) {
  Plotly.relayout('chart', { 'xaxis.range': [shiftDay(day, -45), shiftDay(day, 45)] });
}

// линия пульса прорисовывается слева направо - только при открытии игры, не при каждом зуме.
// После анимации стили снимаются: следующую перерисовку Plotly делает сам, и чужой dasharray ему бы мешал
function drawIn(chart) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const path = chart.querySelector('.tracepulse .js-line');
  if (!path || !path.getTotalLength) return;
  const length = path.getTotalLength();
  path.style.strokeDasharray = `${length}`;
  path.style.strokeDashoffset = `${length}`;
  path.getBoundingClientRect();
  path.style.transition = 'stroke-dashoffset 1.6s cubic-bezier(.2,.8,.2,1)';
  path.style.strokeDashoffset = '0';
  path.addEventListener('transitionend', () => {
    path.style.removeProperty('stroke-dasharray');
    path.style.removeProperty('stroke-dashoffset');
    path.style.removeProperty('transition');
  }, { once: true });
}
