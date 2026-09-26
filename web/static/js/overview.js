import { DOWN, UP, steamRating } from './labels.js';
import { $, countUp, delta, el, num, pct, plural, reviewsWord, sparkline } from './util.js';

// главная: все игры с поиском, фильтрами и сортировкой. Состояние фильтров - в адресе, как и всё остальное
let games = [];
let onOpen = () => {};
const state = { q: '', genre: '', trend: '', llm: false, sort: 'name', view: 'grid' };
const TREND_PP = 2;   // меньше двух пунктов за 30 дней - не рост и не падение, а шум

const now = g => pct(g.positive_30, g.reviews_30);
const before = g => pct(g.positive_prev, g.reviews_prev);
const change = g => (now(g) != null && before(g) != null ? now(g) - before(g) : null);
const genresOf = g => (g.genres || '').split(', ').filter(Boolean);

export function steamLink(appId, size = 14) {
  const a = el('a', 'steam');
  a.href = `https://store.steampowered.com/app/${appId}/`;
  a.target = '_blank';
  a.rel = 'noopener';
  a.title = 'Страница игры в Steam';
  a.setAttribute('aria-label', 'Страница игры в Steam');
  const img = el('img');
  img.src = '/static/steam.svg';
  img.alt = '';
  img.width = img.height = size;
  a.append(img);
  // щелчок по ссылке на Steam не должен заодно открывать игру на стенде
  a.addEventListener('click', e => e.stopPropagation());
  return a;
}

function card(g, i) {
  // карточка целиком - цель щелчка, ссылка - название: так внутри может жить отдельная ссылка на Steam
  const node = el('article', 'game-card');
  node.style.animationDelay = `${Math.min(i * 35, 420)}ms`;
  node.addEventListener('click', () => onOpen(g.app_id));
  const title = el('h3');
  const link = el('a', null, g.game_name);
  link.href = `/?app=${g.app_id}`;
  link.style.textDecoration = 'none';
  link.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); onOpen(g.app_id); });
  title.append(link);
  node.append(title, steamLink(g.app_id));
  if (g.genres) node.append(el('div', 'genres', g.genres));

  const row = el('div', 'row');
  const big = el('div', 'big');
  big.textContent = now(g) == null ? '—' : String(now(g));
  if (now(g) != null) big.append(el('small', null, '%'));
  const side = el('div');
  side.style.textAlign = 'right';
  if (change(g) != null) side.append(delta(change(g)));
  side.append(el('div', 'rating', now(g) == null ? 'нет свежих отзывов' : steamRating(now(g), g.reviews_30)));
  row.append(big, side);
  node.append(row);

  // цвет кривой - тот же знак, что у стрелки: последние 30 дней к прошлым
  node.append(sparkline(g.spark, change(g) != null && change(g) < 0 ? DOWN : UP));
  const foot = el('div', 'rating foot', `${num(g.reviews)} ${reviewsWord(g.reviews)}`);
  if (g.has_llm) foot.append(' · ', el('span', 'llm-mark', 'разбор модели'));
  if (g.collection_status === 'partial') foot.append(' · ', el('span', 'delta down', 'данные неполные'));
  node.append(foot);
  return node;
}

function matches(g) {
  const q = state.q.toLowerCase();
  if (q && ![g.game_name, g.genres, g.developers].some(x => (x || '').toLowerCase().includes(q))) return false;
  if (state.genre && !genresOf(g).includes(state.genre)) return false;
  if (state.llm && !g.has_llm) return false;
  if (state.trend === 'up' && !(change(g) >= TREND_PP)) return false;
  if (state.trend === 'down' && !(change(g) <= -TREND_PP)) return false;
  return true;
}

const SORTS = {
  name: (a, b) => a.game_name.localeCompare(b.game_name, 'ru'),
  pct: (a, b) => (now(b) ?? -1) - (now(a) ?? -1),
  delta: (a, b) => Math.abs(change(b) ?? 0) - Math.abs(change(a) ?? 0),
  reviews: (a, b) => b.reviews - a.reviews
};

function render() {
  const list = games.filter(matches).sort(SORTS[state.sort]);
  const box = $('games');
  box.className = `games ${state.view}`;
  box.replaceChildren(...list.map(card));
  $('games-count').textContent = list.length === games.length
    ? `${games.length} ${plural(games.length, 'игра', 'игры', 'игр')}`
    : `показано ${list.length} из ${games.length}`;
  if (!list.length) box.append(el('p', 'muted', 'Под эти условия игр нет - ослабьте фильтры.'));

  // адрес - без пустых и значений по умолчанию, чтобы ссылка оставалась короткой
  const params = new URLSearchParams();
  Object.entries(state).forEach(([k, v]) => {
    if (v && !(k === 'sort' && v === 'name') && !(k === 'view' && v === 'grid')) params.set(k, v === true ? '1' : v);
  });
  history.replaceState(null, '', params.toString() ? `/?${params}` : '/');
}

function sync() {
  $('game-search').value = state.q;
  $('filter-genre').value = state.genre;
  $('filter-llm').checked = state.llm;
  $('sort').value = state.sort;
  document.querySelectorAll('[data-trend]').forEach(b => b.classList.toggle('active', b.dataset.trend === state.trend));
  document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
}

export function initOverview(openGame) {
  onOpen = openGame;
  $('game-search').addEventListener('input', e => { state.q = e.target.value.trim(); render(); });
  $('filter-genre').addEventListener('change', e => { state.genre = e.target.value; render(); });
  $('filter-llm').addEventListener('change', e => { state.llm = e.target.checked; render(); });
  $('sort').addEventListener('change', e => { state.sort = e.target.value; render(); });
  document.querySelectorAll('[data-trend]').forEach(b => b.addEventListener('click', () => { state.trend = b.dataset.trend; sync(); render(); }));
  document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => { state.view = b.dataset.view; sync(); render(); }));
}

export function renderOverview(list) {
  games = list;
  const params = new URLSearchParams(location.search);
  Object.assign(state, {
    q: params.get('q') || '', genre: params.get('genre') || '', trend: params.get('trend') || '',
    llm: params.get('llm') === '1', sort: SORTS[params.get('sort')] ? params.get('sort') : 'name',
    view: params.get('view') === 'list' ? 'list' : 'grid'
  });

  const genres = [...new Set(list.flatMap(genresOf))].sort((a, b) => a.localeCompare(b));
  $('filter-genre').replaceChildren(new Option('все жанры', ''), ...genres.map(g => new Option(g, g)));
  $('filter-llm').closest('label').hidden = !list.some(g => g.has_llm);

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
    stat(counted(reviews), reviewsWord(reviews) + ' в базе'),
    ...(last ? [stat(el('b', null, new Date(last + 'T00:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })),
                     'последний день с отзывами')] : [])
  );
  sync();
  render();
}
