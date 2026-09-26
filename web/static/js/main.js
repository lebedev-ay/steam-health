import { fetchGame, fetchGames } from './api.js';
import { renderChart, zoomTo } from './chart.js';
import { initCollect } from './collect.js';
import { focusPoint, renderAspects, renderAudience, renderHeader, renderKpis, renderPoints } from './sections.js';

const $ = id => document.getElementById(id);

// выбранная игра живёт в адресе (?app=), чтобы ссылкой на страницу можно было поделиться
function setAppInUrl(appId) {
  const url = new URL(location.href);
  url.searchParams.set('app', appId);
  history.replaceState(null, '', url);
}

function showOnChart(day) {
  zoomTo(day);
  $('chart').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function load() {
  const appId = $('game').value;
  if (!appId) return;
  setAppInUrl(appId);

  const main = $('content');
  main.classList.add('loading');
  $('error').hidden = true;
  try {
    const data = await fetchGame(appId, { smoothing: $('smoothing').value, sensitivity: $('sensitivity').value });
    main.hidden = false;
    renderHeader(data.game);
    renderKpis(data);
    // у только что заведённой игры отзывов ещё нет: пустой график ничего не говорит, остаётся заметка в переломах
    $('chart-card').hidden = !data.daily.length;
    if (data.daily.length) {
      renderChart(data, { onPointClick: focusPoint });
      $('chart-note').textContent = `Сглаживание - окно ${data.window} дн. Серая линия - обычный для игры уровень, ` +
        'медиана за 90 дней. Колесо мыши - приблизить, перетаскивание - сдвинуть, двойной щелчок - вернуть весь период.';
    }
    renderPoints(data, showOnChart);
    renderAspects(data.aspects);
    renderAudience(data.segments);
  } catch (err) {
    main.hidden = true;
    $('error').textContent = `Не удалось загрузить игру: ${err.message}`;
    $('error').hidden = false;
  } finally {
    main.classList.remove('loading');
  }
}

async function reloadGames(appId) {
  const games = await fetchGames();
  const select = $('game');
  const current = appId || select.value;
  select.replaceChildren(...games.map(g =>
    new Option(g.game_name + (g.collection_status === 'partial' ? ' (неполные данные)' : ''), g.app_id)));
  select.value = String(current);
  load();
}

['game', 'smoothing', 'sensitivity'].forEach(id => $(id).addEventListener('change', load));
initCollect(reloadGames);

const fromUrl = new URLSearchParams(location.search).get('app');
if (fromUrl && [...$('game').options].some(o => o.value === fromUrl)) $('game').value = fromUrl;
load();
