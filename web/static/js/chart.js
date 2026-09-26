import { ARCANE, DOWN, PLATFORM_TYPES, UP, eventType } from './labels.js';
import { esc, shiftDay, truncate } from './util.js';

// цвета совпадают с токенами style.css: Plotly не читает CSS-переменные
const INK = '#f1eefb', MUTED = '#7f7893', GRID = 'rgba(255,255,255,0.06)', SURFACE = '#14121d';
const FONT = 'Onest, system-ui, sans-serif';

// две панели с общей осью дат: сверху доля позитива, снизу объём. Одна шкала на панель - на общей объём и доля
// выглядели бы связанными, хотя их совмещение произвольно
const TOP = [0.3, 1], BOTTOM = [0, 0.2];

// маркеры событий - на скрытой оси 0..1 поверх верхней панели: так они всегда у верхнего края, как бы ни шла кривая
const EVENTS_Y = 0.97, PLATFORM_Y = 0.03;

export function renderChart(data, { onPointClick }) {
  const days = data.daily.map(d => d.day);
  const pct = data.daily.map(d => d.pct);
  const pctByDay = new Map(data.daily.map(d => [d.day, d.pct]));

  const byType = {};
  data.events.forEach(e => (byType[e.type] = byType[e.type] || []).push(e));
  const eventTraces = Object.entries(byType).map(([type, items]) => ({
    x: items.map(e => e.day), y: items.map(() => EVENTS_Y), yaxis: 'y3',
    type: 'scatter', mode: 'markers', name: eventType(type).label,
    marker: { symbol: 'triangle-down', size: 12, color: eventType(type).color, line: { color: SURFACE, width: 2 } },
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
  const colorOf = c => c.score < 0 ? DOWN : UP;
  const cpTrace = {
    x: cps.map(c => c.day), y: cps.map(c => pctByDay.get(c.day)),
    type: 'scatter', mode: 'markers', name: 'переломы', showlegend: false,
    // залитый ромб - по перелому есть проверенный разбор отзывов, контур - нет
    marker: {
      symbol: cps.map(c => c.verdict?.checked ? 'diamond' : 'diamond-open'),
      // у залитого ромба - кольцо цвета фона, чтобы зелёный ромб не сливался с зелёной линией
      size: 16, color: cps.map(colorOf), line: { color: cps.map(c => c.verdict?.checked ? SURFACE : colorOf(c)), width: 2.5 }
    },
    text: cps.map(c => `${c.score < 0 ? '▼' : '▲'} ${Math.abs(c.score)} п.п.` +
      (c.positive_before != null ? ` · за неделю ${c.positive_before}% → ${c.positive_after}%` : '')),
    hovertemplate: '%{text}<extra>перелом</extra>'
  };
  // цвет ромба - направление; в легенде нужен нейтральный свотч, а не цвет первого попавшегося перелома
  const cpLegend = {
    x: [null], y: [null], type: 'scatter', mode: 'markers', name: 'переломы', hoverinfo: 'skip',
    marker: { symbol: 'diamond', size: 12, color: INK }
  };

  const traces = [
    {
      x: days, y: data.daily.map(d => d.base), type: 'scatter', mode: 'lines', name: 'норма игры',
      line: { color: ARCANE, width: 1.5 }, opacity: 0.8, hovertemplate: '%{y}<extra>норма</extra>'
    },
    // свечение под основной линией - широкий полупрозрачный след того же ряда, без подсказки и легенды
    {
      x: days, y: pct, type: 'scatter', mode: 'lines', showlegend: false, hoverinfo: 'skip',
      line: { color: 'rgba(141,255,79,0.16)', width: 9, shape: 'spline', smoothing: 0.5 }
    },
    {
      x: days, y: pct, type: 'scatter', mode: 'lines', name: 'позитивных, %',
      line: { color: UP, width: 2.2, shape: 'spline', smoothing: 0.5 },
      hovertemplate: '<b>%{y}</b><extra>позитивных</extra>'
    },
    cpTrace,
    cpLegend,
    ...eventTraces,
    ...(platform.length ? [platformTrace] : []),
    {
      x: days, y: data.daily.map(d => d.total), type: 'bar', yaxis: 'y2', name: 'отзывов в день', showlegend: false,
      marker: { color: 'rgba(184,107,255,0.42)' }, hovertemplate: '%{y}<extra>отзывов</extra>'
    }
  ];

  // полоса ±3 дня у события платформы: дата у них приблизительная, по публикации заметки
  const shapes = platform.map(e => ({
    type: 'rect', xref: 'x', yref: 'paper', x0: shiftDay(e.day, -3), x1: shiftDay(e.day, 4), y0: TOP[0], y1: TOP[1],
    fillcolor: '#ffffff', opacity: 0.025, line: { width: 0 }, layer: 'below'
  }));

  const axis = { gridcolor: GRID, zeroline: false, color: MUTED, fixedrange: true, tickfont: { family: 'JetBrains Mono, monospace', size: 11 } };
  const chart = document.getElementById('chart');
  Plotly.react(chart, traces, {
    height: 500,
    margin: { t: 10, r: 12, b: 30, l: 46 },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: INK, family: FONT, size: 12 },
    legend: { orientation: 'h', y: -0.1, font: { color: MUTED } },
    hovermode: 'x unified',
    hoverlabel: { bgcolor: '#1b1826', bordercolor: 'rgba(184,107,255,0.5)', font: { color: INK, family: FONT } },
    dragmode: 'pan',
    shapes,
    xaxis: {
      anchor: 'y2', gridcolor: GRID, color: MUTED, hoverformat: '%d.%m.%Y', type: 'date',
      tickfont: { family: 'JetBrains Mono, monospace', size: 11 },
      spikecolor: 'rgba(184,107,255,0.6)', spikethickness: 1, spikedash: 'solid',
      rangeselector: {
        x: 0, y: 1.0, yanchor: 'bottom', bgcolor: '#1b1826', activecolor: '#2e2942', bordercolor: 'rgba(255,255,255,0.1)',
        borderwidth: 1, font: { color: INK, size: 11 },
        buttons: [
          { count: 3, label: '3 мес', step: 'month', stepmode: 'backward' },
          { count: 6, label: '6 мес', step: 'month', stepmode: 'backward' },
          { count: 1, label: 'год', step: 'year', stepmode: 'backward' },
          { step: 'all', label: 'всё' }
        ]
      }
    },
    yaxis: { ...axis, domain: TOP, ticksuffix: '%' },
    yaxis2: { ...axis, domain: BOTTOM, nticks: 3, title: { text: 'отзывов', font: { size: 11, color: MUTED } } },
    yaxis3: { domain: TOP, range: [0, 1], visible: false, fixedrange: true, overlaying: 'y' }
  }, { responsive: true, displayModeBar: false, scrollZoom: true, doubleClick: 'reset' });

  chart.removeAllListeners?.('plotly_click');
  chart.on('plotly_click', ev => {
    const pt = ev.points?.find(p => p.data.name === 'переломы');
    if (pt) onPointClick(String(pt.x).slice(0, 10));
  });
}

// приблизить график ко дню: полтора месяца до и после
export function zoomTo(day) {
  Plotly.relayout('chart', { 'xaxis.range': [shiftDay(day, -45), shiftDay(day, 45)] });
}
