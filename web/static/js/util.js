// элемент с классом и текстом; текст ставится через textContent - заголовки новостей и отзывы пишет кто угодно
export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

// экранирование для строк, которые собираются в разметку подсказок Plotly
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

export function ruDate(day, opts = {}) {
  return new Date(day + 'T00:00:00').toLocaleDateString('ru-RU', opts);
}

export function shiftDay(day, n) {
  const d = new Date(day + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function truncate(s, n) {
  s = String(s);
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}
