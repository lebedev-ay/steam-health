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

// тултип Plotly строки не переносит, длинный вывод уезжал бы за край графика. Текст экранируется: его пишет модель
export function wrapText(s, width) {
  const lines = [];
  let line = '';
  String(s).split(/\s+/).forEach(word => {
    if (line && (line + ' ' + word).length > width) {
      lines.push(line);
      line = word;
    } else {
      line = line ? line + ' ' + word : word;
    }
  });
  if (line) lines.push(line);
  return lines.map(esc).join('<br>');
}

// не длиннее n символов с обрезкой по границе слова; truncate выше режет по символу, им пользуется таблица переломов
export function cutWords(s, n) {
  s = String(s);
  if (s.length <= n) return s;
  const cut = s.slice(0, n - 1);
  const space = cut.lastIndexOf(' ');
  return (space > 0 ? cut.slice(0, space) : cut).replace(/[\s,.;:-]+$/, '') + '…';
}

// i-я фраза текста (с нуля), не длиннее n символов; null, если столько фраз нет
export function nthSentence(s, i, n) {
  const sentence = String(s).split(/(?<=[.!?])\s+/).filter(Boolean)[i];
  return sentence ? cutWords(sentence, n) : null;
}

export function firstSentence(s, n) {
  return nthSentence(s, 0, n) || '';
}
