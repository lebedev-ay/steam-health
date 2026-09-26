// элемент с классом и текстом; текст ставится через textContent - заголовки новостей и отзывы пишет кто угодно
export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

export const $ = id => document.getElementById(id);

// экранирование для строк, которые собираются в разметку: подсказки Plotly и SVG
export function esc(s) {
  return String(s).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

export function plural(n, one, few, many) {
  const tail = Math.abs(n) % 100;
  if (tail > 10 && tail < 20) return many;
  const last = tail % 10;
  if (last === 1) return one;
  if (last > 1 && last < 5) return few;
  return many;
}

export const num = n => Number(n).toLocaleString('ru-RU');
export const pct = (part, total) => total ? Math.round(100 * part / total) : null;
export const reviewsWord = n => plural(n, 'отзыв', 'отзыва', 'отзывов');

export function ruDate(day, opts = {}) {
  return new Date(day + 'T00:00:00').toLocaleDateString('ru-RU', opts);
}
export const longDate = day => ruDate(day, { day: 'numeric', month: 'long', year: 'numeric' });

export function shiftDay(day, n) {
  const d = new Date(day + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function truncate(s, n) {
  s = String(s);
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

export function hours(minutes) {
  if (minutes == null) return null;
  const h = minutes / 60;
  return h < 10 ? `${h.toFixed(1).replace('.', ',')} ч` : `${num(Math.round(h))} ч`;
}

// изменение в процентных пунктах: знак стрелкой, цвет классом - цвет никогда не единственный носитель смысла
export function delta(value, suffix = ' п.п.') {
  const node = el('span', `delta ${value > 0 ? 'up' : value < 0 ? 'down' : 'flat'}`);
  node.textContent = value > 0 ? `▲ ${value}${suffix}` : value < 0 ? `▼ ${Math.abs(value)}${suffix}` : `= 0${suffix}`;
  return node;
}

// число плавно набирается от нуля: при смене игры видно, что данные новые
export function countUp(node, value, format = v => String(Math.round(v))) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches || !Number.isFinite(value)) {
    node.textContent = format(value);
    return;
  }
  const start = performance.now();
  const step = now => {
    const t = Math.min((now - start) / 700, 1);
    node.textContent = format(value * (1 - Math.pow(1 - t, 3)));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// --- маленькие SVG: спарклайн и шкала здоровья. Plotly для них тяжёл, а данных - десятки точек ---

const SVG = 'http://www.w3.org/2000/svg';
let gradientId = 0;

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG, tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}

// линия с заливкой до низа; пропуски (null) разрывают линию, а не тянут её к нулю
export function sparkline(values, color, { lo = null, hi = null } = {}) {
  // ширина в координатах близка к настоящей: растяжение по горизонтали небольшое, и линия не искажается
  const box = svg('svg', { class: 'spark', viewBox: '0 0 300 40', preserveAspectRatio: 'none', 'aria-hidden': 'true' });
  const known = values.filter(v => v != null);
  if (known.length < 2) return box;
  const min = lo ?? Math.min(...known), max = hi ?? Math.max(...known);
  const x = i => (i / (values.length - 1)) * 300;
  const y = v => 37 - ((v - min) / (max - min || 1)) * 32;
  const points = values.map((v, i) => v == null ? null : [x(i), y(v)]);
  const line = points.map((p, i) => p ? `${points[i - 1] ? 'L' : 'M'}${p[0].toFixed(2)},${p[1].toFixed(2)}` : '').join('');
  const id = `sg${++gradientId}`;
  const defs = svg('defs');
  const grad = svg('linearGradient', { id, x1: 0, y1: 0, x2: 0, y2: 1 });
  grad.append(svg('stop', { offset: 0, 'stop-color': color, 'stop-opacity': 0.18 }),
              svg('stop', { offset: 1, 'stop-color': color, 'stop-opacity': 0 }));
  defs.append(grad);
  const first = points.find(Boolean), last = [...points].reverse().find(Boolean);
  // pathLength=1 - линия прорисовывается слева направо одной CSS-анимацией, какой бы длины она ни была
  box.append(defs,
    svg('path', { class: 'area', d: `${line}L${last[0]},40L${first[0]},40Z`, fill: `url(#${id})`, stroke: 'none' }),
    svg('path', { class: 'line', pathLength: 1, d: line, fill: 'none', stroke: color, 'stroke-width': 1.6,
                  'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  return box;
}

// кольцо «здоровья»: доля положительных за 30 дней, дуга в 270 градусов молочно-лунным по тусклой дорожке
export function gauge(value, label) {
  const box = svg('svg', { viewBox: '0 0 200 200', role: 'img', 'aria-label': `${label}: ${value}%` });
  const r = 80, c = 2 * Math.PI * r, arc = c * 0.75;
  const ring = { cx: 100, cy: 100, r, fill: 'none', 'stroke-width': 6, 'stroke-linecap': 'round', transform: 'rotate(135 100 100)' };
  const track = svg('circle', { ...ring, stroke: 'rgba(255,255,255,0.07)', 'stroke-dasharray': `${arc} ${c}` });
  const bar = svg('circle', { ...ring, stroke: '#ece6d6', 'stroke-dasharray': `0 ${c}` });
  bar.style.transition = 'stroke-dasharray 1.1s cubic-bezier(.2,.8,.2,1)';
  // метки 50% и 80%: на глаз видно, где «смешанные» и где «очень положительные»
  const ticks = [50, 80].map(p => {
    const a = (135 + 270 * p / 100) * Math.PI / 180;
    return svg('line', { x1: 100 + (r - 11) * Math.cos(a), y1: 100 + (r - 11) * Math.sin(a), x2: 100 + (r - 5) * Math.cos(a),
                         y2: 100 + (r - 5) * Math.sin(a), stroke: 'rgba(255,255,255,0.25)', 'stroke-width': 1.5 });
  });
  const text = svg('text', { x: 100, y: 108, 'text-anchor': 'middle', fill: '#ece6d6', 'font-size': 38, 'font-weight': 500, 'font-family': 'Onest, sans-serif' });
  text.textContent = value == null ? '—' : `${value}%`;
  const sub = svg('text', { x: 100, y: 132, 'text-anchor': 'middle', fill: '#736e7d', 'font-size': 12, 'font-family': 'Onest, sans-serif' });
  sub.textContent = label;
  box.append(track, ...ticks, bar, text, sub);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    bar.setAttribute('stroke-dasharray', `${arc * (value || 0) / 100} ${c}`);
  }));
  return box;
}

// столбики по месяцам для темы: вверх - хвалят, вниз - ругают, в долях размеченных. Подписи месяцев - HTML под рисунком:
// SVG растянут по ширине без сохранения пропорций, и текст внутри него растянулся бы вместе с ним
export function monthBars(months, up, down) {
  const wrap = el('div', 'months');
  const box = svg('svg', { class: 'months-chart', viewBox: '0 0 600 160', preserveAspectRatio: 'none', role: 'img' });
  const shares = months.map(m => ({ ...m, p: m.labeled ? m.positive / m.labeled : 0, n: m.labeled ? m.negative / m.labeled : 0 }));
  const max = Math.max(...shares.map(s => Math.max(s.p, s.n)), 0.01);
  const w = 600 / Math.max(months.length, 1);
  box.append(svg('line', { x1: 0, x2: 600, y1: 80, y2: 80, stroke: 'rgba(255,255,255,0.15)', 'stroke-width': 1 }));
  shares.forEach((s, i) => {
    const x = i * w + w * 0.3, bw = w * 0.4;
    const hp = 74 * s.p / max, hn = 74 * s.n / max;
    const g = svg('g');
    const title = svg('title');
    title.textContent = `${ruDate(s.month, { month: 'long', year: 'numeric' })}: хвалят ${Math.round(100 * s.p)}%, ` +
      `ругают ${Math.round(100 * s.n)}% из ${s.labeled} размеченных`;
    // прозрачная полоса во всю высоту - цель для наведения шире самих столбиков
    g.append(title, svg('rect', { x: i * w, y: 0, width: w, height: 160, fill: 'transparent' }),
      svg('rect', { x, y: 78 - hp, width: bw, height: Math.max(hp, 0.5), rx: 2, fill: up, 'fill-opacity': 0.85 }),
      svg('rect', { x, y: 82, width: bw, height: Math.max(hn, 0.5), rx: 2, fill: down, 'fill-opacity': 0.85 }));
    box.append(g);
  });
  const labels = el('div', 'months-labels');
  months.forEach(m => labels.append(el('span', null, ruDate(m.month, { month: 'short' }).replace('.', ''))));
  wrap.append(box, labels);
  return wrap;
}

// текст с подсвеченными вхождениями слова; только textContent и <mark> - текст отзыва пишет кто угодно
export function highlighted(text, word) {
  const node = document.createDocumentFragment();
  if (!word) {
    node.append(text);
    return node;
  }
  const lower = text.toLowerCase(), needle = word.toLowerCase();
  let at = 0;
  for (let i = lower.indexOf(needle); i !== -1; i = lower.indexOf(needle, at)) {
    node.append(text.slice(at, i), el('mark', null, text.slice(i, i + word.length)));
    at = i + word.length;
  }
  node.append(text.slice(at));
  return node;
}
