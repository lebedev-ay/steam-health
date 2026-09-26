import { PLATFORM_TYPES, UP, DOWN, eventType } from './labels.js';
import { esc, shiftDay, truncate } from './util.js';

// цвета совпадают с токенами style.css: Plotly не читает CSS-переменные
const INK = '#e8ebee', MUTED = '#8b929b', GRID = '#2a2e33', SURFACE = '#1a1d21';

// две панели с общей осью дат: сверху доля позитива, снизу объём. Одна ось Y на панель - на общей шкале объём и доля
// выглядели бы связанными, хотя их совмещение произвольно
const TOP = [0.3, 1], BOTTOM = [0, 0.22];

// маркеры событий - на скрытой оси 0..1 поверх верхней панели: так они всегда у верхнего края, как бы ни шла кривая
const EVENTS_Y = 0.97, PLATFORM_Y = 0.03;

export function renderChart(data, { onPointClick }) {
  const days = data.daily.map(d => d.day);
  const pctByDay = new Map(data.daily.map(d => [d.day, d.pct]));

  const eventTraces = Object.entries(groupBy(data.events, e => e.type)).map(([type, items]) => ({
    x: items.map(e => e.day), y: items.map(() => EVENTS_Y), yaxis: 'y3',
    type: 'scatter', mode: 'markers', name: eventType(type).label,
    marker: { symbol: 'triangle-down', size: 11, color: eventType(type).color, line: { color: SURFACE, width: 2 } },
    text: items.map(e => esc(truncate(e.title, 70)) + (e.weight ? ` · вес ${e.weight}` : '')),
    hovertemplate: '%{text}<extra>' + eventType(type).label + '</extra>'
  }));

  const platform = data.platform_events;
  const platformTrace = {
    x: platform.map(e => e.day), y: platform.map(() => PLATFORM_Y), yaxis: 'y3',
    type: 'scatter', mode: 'markers', name: 'события Steam',
    marker: { symbol: 'square', size: 9, color: MUTED, line: { color: SURFACE, width: 2 } },
    text: platform.map(e => `${PLATFORM_TYPES[e.type] || 'Steam'}: ${esc(truncate(e.title, 60))}`),
    hovertemplate: '%{text}<extra></extra>'
  };

  const cps = data.change_points.filter(c => pctByDay.get(c.day) != null);
  const cpTrace = {
    x: cps.map(c => c.day), y: cps.map(c => pctByDay.get(c.day)),
    type: 'scatter', mode: 'markers', name: 'переломы', showlegend: false,
    // залитый ромб - по перелому есть проверенный разбор отзывов, контур - нет
    marker: {
      symbol: cps.map(c => c.verdict?.checked ? 'diamond' : 'diamond-open'),
      size: 14, color: cps.map(c => c.score < 0 ? DOWN : UP), line: { color: cps.map(c => c.score < 0 ? DOWN : UP), width: 2 }
    },
    text: cps.map(c => `${c.score < 0 ? '▼' : '▲'} ${Math.abs(c.score)} п.п.` +
      (c.positive_before != null ? ` · позитив ${c.positive_before}% → ${c.positive_after}%` : '')),
    hovertemplate: '%{text}<extra>перелом</extra>'
  };

  // цвет ромба - направление; в легенде нужен нейтральный свотч, а не цвет первого попавшегося перелома
  const cpLegend = {
    x: [null], y: [null], type: 'scatter', mode: 'markers', name: 'переломы', hoverinfo: 'skip',
    marker: { symbol: 'diamond', size: 12, color: MUTED }
  };

  const traces = [
    {
      x: days, y: data.daily.map(d => d.base), type: 'scatter', mode: 'lines', name: 'обычный уровень',
      line: { color: MUTED, width: 1.5 }, hovertemplate: '%{y}%<extra>обычный уровень</extra>'
    },
    {
      x: days, y: data.daily.map(d => d.pct), type: 'scatter', mode: 'lines', name: 'позитивных, %',
      line: { color: INK, width: 2 }, connectgaps: false, hovertemplate: '<b>%{y}%</b><extra>позитивных</extra>'
    },
    cpTrace,
    cpLegend,
    ...eventTraces,
    ...(platform.length ? [platformTrace] : []),
    {
      x: days, y: data.daily.map(d => d.total), type: 'bar', yaxis: 'y2', name: 'отзывов в день',
      marker: { color: 'rgba(139,146,155,0.45)' }, showlegend: false,
      hovertemplate: '%{y}<extra>отзывов</extra>'
    }
  ];

  // полоса ±3 дня у события платформы: дата у них приблизительная, по публикации заметки
  const shapes = platform.map(e => ({
    type: 'rect', xref: 'x', yref: 'paper', x0: shiftDay(e.day, -3), x1: shiftDay(e.day, 4), y0: TOP[0], y1: TOP[1],
    fillcolor: MUTED, opacity: 0.07, line: { width: 0 }, layer: 'below'
  }));

  const axis = { gridcolor: GRID, zeroline: false, color: MUTED, fixedrange: true };
  const chart = document.getElementById('chart');
  Plotly.react(chart, traces, {
    height: 480,
    margin: { t: 8, r: 16, b: 32, l: 44 },
    paper_bgcolor: SURFACE, plot_bgcolor: SURFACE,
    font: { color: INK, family: 'system-ui, -apple-system, "Segoe UI", sans-serif', size: 12 },
    showlegend: true,
    legend: { orientation: 'h', y: -0.1, font: { color: MUTED } },
    hovermode: 'x unified',
    hoverlabel: { bgcolor: '#22262b', bordercolor: GRID, font: { color: INK } },
    dragmode: 'pan',
    shapes,
    xaxis: {
      anchor: 'y2', gridcolor: GRID, color: MUTED, hoverformat: '%d.%m.%Y', type: 'date',
      rangeselector: {
        x: 0, y: 1.0, yanchor: 'bottom', bgcolor: '#22262b', activecolor: '#3a3f45', font: { color: INK },
        buttons: [
          { count: 3, label: '3 мес', step: 'month', stepmode: 'backward' },
          { count: 6, label: '6 мес', step: 'month', stepmode: 'backward' },
          { count: 1, label: 'год', step: 'year', stepmode: 'backward' },
          { step: 'all', label: 'всё' }
        ]
      }
    },
    yaxis: { ...axis, domain: TOP, ticksuffix: '%', title: { text: '' } },
    yaxis2: { ...axis, domain: BOTTOM, nticks: 3, title: { text: 'отзывов', font: { size: 11, color: MUTED } } },
    yaxis3: { domain: TOP, range: [0, 1], visible: false, fixedrange: true, overlaying: 'y' }
  }, { responsive: true, displayModeBar: false, scrollZoom: true, doubleClick: 'reset' });

  chart.removeAllListeners?.('plotly_click');
  chart.on('plotly_click', ev => {
    const pt = ev.points?.find(p => p.data.name === 'переломы');
    if (pt) onPointClick(String(pt.x).slice(0, 10));
  });
}

// приблизить график к перелому: месяц до и месяц после
export function zoomTo(day) {
  Plotly.relayout('chart', { 'xaxis.range': [shiftDay(day, -45), shiftDay(day, 45)] });
}

function groupBy(items, key) {
  const out = {};
  items.forEach(item => (out[key(item)] = out[key(item)] || []).push(item));
  return out;
}
