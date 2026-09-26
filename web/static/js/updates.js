import { TIER_LABELS, eventGroup, eventType } from './labels.js';
import { $, delta, el, num, ruDate, shiftDay, truncate } from './util.js';

// вкладка «Обновления»: реакция на каждую новость игры, с сортировкой
const UPDATE_COLUMNS = [
  { key: 'day', title: 'дата', sort: (a, b) => b.day.localeCompare(a.day) },
  { key: 'title', title: 'новость' },
  { key: 'before', title: 'позитив до → после' },
  { key: 'change', title: 'изменение', sort: (a, b) => change(a) - change(b) },
  { key: 'volume', title: 'отзывов после', sort: (a, b) => ratio(b) - ratio(a) }
];
const change = u => u.positive_after != null && u.positive_before != null ? u.positive_after - u.positive_before : 0;
const ratio = u => u.reviews_before ? u.reviews_after / u.reviews_before : 0;
let updatesSort = 'day';
let actions = {};

export function renderUpdates(updates, handlers = actions) {
  actions = handlers;
  const box = $('updates');
  if (!updates.length) {
    box.replaceChildren(el('p', 'muted', 'новостей игры в собранном периоде нет'));
    return;
  }
  const table = el('table', 'table');
  const head = table.createTHead().insertRow();
  UPDATE_COLUMNS.forEach(col => {
    const th = el('th', null, col.title);
    if (col.sort) {
      if (col.key === updatesSort) th.dataset.sorted = '';
      th.onclick = () => { updatesSort = col.key; renderUpdates(updates); };
    }
    head.append(th);
  });
  const body = table.createTBody();
  [...updates].sort(UPDATE_COLUMNS.find(c => c.key === updatesSort).sort).forEach(u => {
    const row = body.insertRow();
    row.onclick = () => actions.openReviews({ since: u.day, until: shiftDay(u.day, 7) });
    const type = el('td');
    const dot = el('span', 'dot');
    dot.style.background = eventGroup(u).color;
    if (u.title_ru) {
      type.append(dot, u.title_ru, el('span', 'muted', ` · ${TIER_LABELS[u.tier]}${u.future ? ', анонс' : ''}`));
      type.title = u.title;
    } else {
      type.append(dot, `${eventType(u.type).label}: ${truncate(u.title, 80)}`);
    }
    const d = change(u);
    const deltaCell = el('td');
    if (u.positive_after != null && u.positive_before != null) deltaCell.append(delta(d));
    const r = ratio(u);
    row.append(el('td', 'num', ruDate(u.day)), type,
               el('td', 'num', u.positive_before != null ? `${u.positive_before}% → ${u.positive_after ?? '—'}%` : '—'),
               deltaCell,
               el('td', 'num', `${num(u.reviews_after)}${r ? ` · ×${r.toFixed(1).replace('.', ',')}` : ''}`));
  });
  box.replaceChildren(table);
}
