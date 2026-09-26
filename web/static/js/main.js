import { initAccount } from './account.js';
import { fetchGame, fetchGames } from './api.js';
import { zoomTo } from './chart.js';
import { renderGame } from './game.js';
import { initOverview, renderOverview } from './overview.js';
import { initReviews, loadReviews, resetReviews, showReviews } from './reviews.js';
import { initSwitcher, setGames } from './switcher.js';
import { $ } from './util.js';

// одна страница, два вида: все игры (/) и игра (/?app=ID&tab=...). Адрес - единственный источник состояния, им можно поделиться
const TABS = ['overview', 'turns', 'topics', 'audience', 'updates', 'reviews'];
let loadedApp = null;
let reviewsLoaded = false;
let gamesList = [];

function url(params) {
  const u = new URL(location.href);
  u.search = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
  return u;
}

function showError(err) {
  $('error').textContent = err ? `Не удалось загрузить: ${err.message}` : '';
  $('error').hidden = !err;
}

function show(view) {
  $('view-overview').hidden = view !== 'overview';
  $('view-game').hidden = view !== 'game';
}

// --- вкладки ---

// индикатор под активной вкладкой переезжает к новой, а не появляется на месте
function moveIndicator() {
  const active = document.querySelector('#tabs button.active');
  const bar = document.querySelector('.tabs-indicator');
  if (!active || !bar) return;
  bar.style.width = `${active.offsetWidth - 20}px`;
  bar.style.transform = `translateX(${active.offsetLeft + 10}px)`;
}

function selectTab(tab, { push = false } = {}) {
  if (!TABS.includes(tab)) tab = 'overview';
  document.querySelectorAll('#tabs [data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  moveIndicator();
  document.querySelectorAll('.panel').forEach(p => { p.hidden = p.dataset.panel !== tab; });
  const params = { app: loadedApp, tab: tab === 'overview' ? null : tab };
  history[push ? 'pushState' : 'replaceState'](null, '', url(params));
  // график рисовался, пока его вкладка могла быть скрыта: ширину он узнаёт только теперь
  if (tab === 'overview' && window.Plotly && $('chart').data) Plotly.Plots.resize('chart');
  if (tab === 'reviews' && !reviewsLoaded) {
    reviewsLoaded = true;
    loadReviews();
  }
}

// --- виды ---

async function openOverview({ push = false } = {}) {
  loadedApp = null;
  $('switcher-label').textContent = 'Найти игру';
  document.title = 'Steam Health - пульс игр Steam';
  if (push) history.pushState(null, '', url({}));
  show('overview');
  window.scrollTo({ top: 0 });
  try {
    gamesList = await fetchGames();
    setGames(gamesList);
    renderOverview(gamesList);
    showError(null);
  } catch (err) {
    showError(err);
  }
}

async function openGame(appId, { push = false, tab = 'overview' } = {}) {
  const view = $('view-game');
  view.classList.add('loading');
  showError(null);
  try {
    // список игр нужен для места в рейтинге; по прямой ссылке его ещё нет - грузится вместе с игрой
    const [data, games] = await Promise.all([
      fetchGame(appId, { smoothing: $('smoothing').value, sensitivity: $('sensitivity').value }),
      gamesList.length ? gamesList : fetchGames().catch(() => [])
    ]);
    if (!gamesList.length && games.length) { gamesList = games; setGames(games); }
    const firstVisit = loadedApp !== data.game.app_id;
    loadedApp = data.game.app_id;
    if (push) history.pushState(null, '', url({ app: loadedApp }));
    show('game');
    if (firstVisit) {
      window.scrollTo({ top: 0 });
      resetReviews(data.game, (data.segments.language || []).map(s => s.segment), data.daily.at(-1)?.day);
      reviewsLoaded = false;
    }
    $('switcher-label').textContent = data.game.game_name;
    document.title = `${data.game.game_name} - Steam Health`;
    // вкладку выбираем до отрисовки, чтобы график считал ширину по видимой панели
    selectTab(firstVisit ? tab : document.querySelector('#tabs .active')?.dataset.tab);
    // ширина вкладок известна только после показа страницы и загрузки шрифтов
    document.fonts?.ready.then(moveIndicator);
    renderGame(data, {
      firstVisit,
      games: gamesList,
      selectTab: t => selectTab(t),
      showOnChart: day => { selectTab('overview'); zoomTo(day); $('chart').scrollIntoView({ behavior: 'smooth', block: 'center' }); },
      openReviews: filter => { selectTab('reviews'); reviewsLoaded = true; showReviews(filter); $('tabs').scrollIntoView({ behavior: 'smooth' }); }
    });
  } catch (err) {
    show(null);
    showError(err);
  } finally {
    view.classList.remove('loading');
  }
}

function route() {
  const params = new URLSearchParams(location.search);
  const app = Number(params.get('app'));
  if (app) openGame(app, { tab: params.get('tab') || 'overview' });
  else openOverview();
}

// --- связки ---

document.querySelectorAll('[data-nav="overview"]').forEach(a => a.addEventListener('click', e => {
  e.preventDefault();
  openOverview({ push: true });
}));
document.querySelectorAll('#tabs [data-tab]').forEach(b => b.addEventListener('click', () => selectTab(b.dataset.tab)));
document.querySelectorAll('[data-goto]').forEach(b => b.addEventListener('click', () => selectTab(b.dataset.goto)));
['smoothing', 'sensitivity'].forEach(id => $(id).addEventListener('change', () => openGame(loadedApp)));
window.addEventListener('popstate', route);
window.addEventListener('resize', moveIndicator);
initOverview(appId => openGame(appId, { push: true }));

initSwitcher(appId => openGame(appId, { push: true }));
initReviews();
initAccount(appId => {
  // после сбора список игр изменился; собранную игру открываем, чужую - только обновляем список
  fetchGames().then(list => { gamesList = list; setGames(list); });
  if (appId) openGame(appId, { push: true });
  else if (!loadedApp) openOverview();
});
route();
