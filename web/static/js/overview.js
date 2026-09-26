import { UP, DOWN, steamRating } from './labels.js';
import { $, countUp, delta, el, num, pct, plural, sparkline } from './util.js';

let games = [];
let sortKey = 'name';

// карточка игры: доля позитива за последние 30 дней, изменение к прошлым 30 и полгода по неделям
function card(g, onOpen) {
  const now = pct(g.positive_30, g.reviews_30);
  const before = pct(g.positive_prev, g.reviews_prev);
  const node = el('a', 'game-card');
  node.href = `/?app=${g.app_id}`;
  node.addEventListener('click', e => { e.preventDefault(); onOpen(g.app_id); });

  node.append(el('h3', null, g.game_name));
  if (g.genres) node.append(el('div', 'genres', g.genres));

  const row = el('div', 'row');
  const big = el('div', 'big');
  big.textContent = now == null ? '—' : String(now);
  if (now != null) big.append(el('small', null, '%'));
  const side = el('div');
  side.style.textAlign = 'right';
  if (now != null && before != null) side.append(delta(now - before));
  side.append(el('div', 'rating', now == null ? 'нет свежих отзывов' : steamRating(now, g.reviews_30)));
  row.append(big, side);
  node.append(row);

  // цвет кривой - тот же знак, что у стрелки: последние 30 дней к прошлым
  node.append(sparkline(g.spark, now != null && before != null && now < before ? DOWN : UP));
  node.append(el('div', 'rating', `${num(g.reviews)} ${plural(g.reviews, 'отзыв', 'отзыва', 'отзывов')} · полгода по неделям`));
  if (g.collection_status === 'partial') node.append(el('span', 'chip warn', 'данные неполные'));
  return node;
}

function sorted() {
  const now = g => pct(g.positive_30, g.reviews_30) ?? -1;
  const change = g => (pct(g.positive_30, g.reviews_30) ?? 0) - (pct(g.positive_prev, g.reviews_prev) ?? 0);
  const by = {
    name: (a, b) => a.game_name.localeCompare(b.game_name, 'ru'),
    pct: (a, b) => now(b) - now(a),
    delta: (a, b) => Math.abs(change(b)) - Math.abs(change(a))
  };
  return [...games].sort(by[sortKey]);
}

function renderGrid(onOpen) {
  $('games').replaceChildren(...sorted().map((g, i) => {
    const node = card(g, onOpen);
    node.style.animationDelay = `${Math.min(i * 40, 400)}ms`;
    return node;
  }));
}

export function renderOverview(list, onOpen) {
  games = list;
  const reviews = list.reduce((a, g) => a + g.reviews, 0);
  const last = list.map(g => g.last_day).filter(Boolean).sort().pop();

  const stat = (value, label) => {
    const node = el('div', 'hero-stat');
    node.append(value, el('span', null, label));
    return node;
  };
  const counted = n => {
    const b = el('b');
    countUp(b, n, v => num(Math.round(v)));
    return b;
  };
  $('overview-stats').replaceChildren(
    stat(counted(list.length), plural(list.length, 'игра', 'игры', 'игр') + ' под наблюдением'),
    stat(counted(reviews), plural(reviews, 'отзыв', 'отзыва', 'отзывов') + ' в базе'),
    ...(last ? [stat(el('b', null, new Date(last + 'T00:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })),
                     'последний день с отзывами')] : [])
  );

  document.querySelectorAll('[data-sort]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.sort === sortKey);
    btn.onclick = () => {
      sortKey = btn.dataset.sort;
      document.querySelectorAll('[data-sort]').forEach(b => b.classList.toggle('active', b === btn));
      renderGrid(onOpen);
    };
  });
  renderGrid(onOpen);
}
