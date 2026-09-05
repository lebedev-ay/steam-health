export function shiftDay(day, n) {
  const d = new Date(day);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

export function truncate(s, n) {
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

// заголовки новостей и имена игр приходят из Steam, то есть их пишет кто угодно.
//  Экранируем всё, что подставляется в разметку, которую собираем строкой - тултипы Plotly
export function esc(s) {
  return String(s).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

// границы оси Plotly пишет в своём формате и со временем, поэтому сравнение строк ловило бы различия записи вместо различий диапазона
export function sameRange(a, b) {
  if (!a || !b) return a === b;
  return Date.parse(a[0]) === Date.parse(b[0])
      && Date.parse(a[1]) === Date.parse(b[1]);
}

// Plotly отдаёт границу оси то с временем, то без - сравниваем по первым 10 символам, ISO-дата сравнивается как строка
export function dayInRange(day, range) {
  if (!range) return true;
  const lo = String(range[0]).slice(0, 10);
  const hi = String(range[1]).slice(0, 10);
  return day >= lo && day <= hi;
}

export function plural(n, one, few, many) {
  const tail = Math.abs(n) % 100;
  if (tail > 10 && tail < 20) return many;
  const last = tail % 10;
  if (last === 1) return one;
  if (last > 1 && last < 5) return few;
  return many;
}
