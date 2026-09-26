import { fetchData, fetchGames, fetchVerdicts, fetchVotes } from './api.js';
import { setData, setVerdicts, setVotes, renderChart } from './chart.js';
import { renderVerdicts, clearVerdicts } from './verdicts.js';

// полный список игр держим отдельно от select: фильтр перерисовывает его содержимое, и выбранная игра выпадать из него не должна
let gameOptions = [...document.getElementById('game').options]
  .map(o => ({ value: o.value, label: o.textContent }));

export function renderGameOptions(preferred) {
  const select = document.getElementById('game');
  const wanted = preferred != null ? String(preferred) : select.value;
  const q = document.getElementById('gameFilter').value.trim().toLowerCase();

  const visible = gameOptions.filter(
    o => o.value === wanted || o.label.toLowerCase().includes(q));

  select.replaceChildren(...visible.map(o => new Option(o.label, o.value)));

  if (visible.some(o => o.value === wanted)) select.value = wanted;

  updateSteamLink();
}

// ссылка лежит рядом с селектом, а не внутри него: renderGameOptions пересобирает только option'ы, и фильтр по имени её не задевает
export function updateSteamLink() {
  const appId = document.getElementById('game').value;
  const link = document.getElementById('steamLink');
  link.href = `https://store.steampowered.com/app/${appId}/`;
  link.hidden = !appId;
}

// перезапрашивают данные только те элементы, что входят в /api/data.
// Режим показа и полосы платформы меняют одну отрисовку, и полный запрос ради них сбрасывал бы текущий зум
export const QUERY_CONTROL_IDS = ['game', 'smoothing', 'sensitivity', 'minWeight'];
export const VIEW_CONTROL_IDS = ['mode', 'showPlatform'];
const CONTROL_IDS = [...QUERY_CONTROL_IDS, ...VIEW_CONTROL_IDS];

function setControlsDisabled(disabled) {
  CONTROL_IDS.forEach(id => { document.getElementById(id).disabled = disabled; });
}

async function load() {
  const appId = document.getElementById('game').value;
  const smoothing = document.getElementById('smoothing').value;
  const sensitivity = document.getElementById('sensitivity').value;
  const minWeight = document.getElementById('minWeight').value;

  // выводы грузятся параллельно с данными графика и не зависят от его параметров: они посчитаны заранее по детектору с настройками по умолчанию
  const [body, verdicts, votes] = await Promise.all([
    fetchData({ appId, smoothing, minWeight, sensitivity }),
    fetchVerdicts(appId),
    fetchVotes(appId)
  ]);

  setVerdicts(verdicts);
  setVotes(votes);
  setData(body);
  renderChart(null);
  renderVerdicts(verdicts);
}

export async function loadSafe() {
  const overlay = document.getElementById('loadingOverlay');
  const errorBox = document.getElementById('errorBox');
  const chart = document.getElementById('sentiment');

  setControlsDisabled(true);
  errorBox.style.display = 'none';
  chart.style.display = '';
  // строка состояния и таблица описывают прежнюю игру: ни во время запроса, ни при ошибке им на экране не место
  document.getElementById('info').textContent = '';
  document.getElementById('cpList').replaceChildren();
  clearVerdicts();
  overlay.style.display = 'flex';

  try {
    await load();
  } catch (e) {
    chart.style.display = 'none';
    errorBox.textContent = 'Не удалось загрузить данные: ' + e.message;
    errorBox.style.display = 'flex';
  } finally {
    overlay.style.display = 'none';
    setControlsDisabled(false);
  }
}

export async function refreshGamesList(appId) {
  const list = await fetchGames();

  gameOptions = list.map(g => ({
    value: String(g.app_id),
    label: g.game_name + (g.collection_status === 'partial' ? ' (данные неполные)' : '')
  }));
  renderGameOptions(appId);

  // зовётся только после успешного сбора: данные собранной игры изменились, поэтому график перерисовываем всегда
  if (document.getElementById('game').options.length) loadSafe();
}
