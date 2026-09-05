import { dayInRange } from './util.js';
import { mainEventLabel } from './events.js';

// cps приходит полным списком: data-idx строки обязан остаться индексом в нём же, по нему ищется ромб на графике
export function renderChangePointList(cps, range,
                                      { note: emptyNote, onSelect, onHover, onLeave }) {
  const el = document.getElementById('cpList');

  if (!cps.length) {
    const note = document.createElement('div');
    note.className = 'cp-empty';
    note.textContent = emptyNote || 'переломов не найдено';
    el.replaceChildren(note);
    return;
  }

  const visible = cps
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => dayInRange(c.day, range));

  if (!visible.length) {
    const note = document.createElement('div');
    note.className = 'cp-empty';
    note.textContent = 'в видимом диапазоне переломов нет - ' +
      'расширьте диапазон или сбросьте зум двойным кликом';
    el.replaceChildren(note);
    return;
  }

  const table = document.createElement('table');
  const head = table.createTHead().insertRow();
  ['Дата', 'Напр.', 'Величина', 'Главное событие'].forEach(t => {
    const th = document.createElement('th');
    th.textContent = t;
    head.append(th);
  });

  const body = table.createTBody();
  visible.forEach(({ c, i }) => {
    const dir = c.score < 0 ? 'спад' : 'рост';
    const dirClass = c.score < 0 ? 'cp-down' : 'cp-up';
    const dateStr = new Date(c.day + 'T00:00:00').toLocaleDateString('ru-RU');

    const row = body.insertRow();
    row.className = 'cp-row';
    row.dataset.idx = i;
    [[dateStr, ''], [dir, dirClass], [`${Math.abs(c.score)} п.п.`, dirClass],
     [mainEventLabel(c), '']].forEach(([text, cls]) => {
      const td = row.insertCell();
      td.textContent = text;
      if (cls) td.className = cls;
    });
  });

  el.replaceChildren(table);

  el.querySelectorAll('.cp-row').forEach(row => {
    const idx = +row.dataset.idx;
    const c = cps[idx];
    row.addEventListener('click', () => onSelect(c));
    row.addEventListener('mouseenter', () => onHover(idx));
    row.addEventListener('mouseleave', onLeave);
  });
}
