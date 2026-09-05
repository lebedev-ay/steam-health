import { renderChart, getRange } from './chart.js';
import { QUERY_CONTROL_IDS, VIEW_CONTROL_IDS, renderGameOptions, loadSafe,
         refreshGamesList } from './games.js';
import { initCollect } from './collect.js';

QUERY_CONTROL_IDS.forEach(id =>
  document.getElementById(id).addEventListener('change', loadSafe));
VIEW_CONTROL_IDS.forEach(id =>
  document.getElementById(id).addEventListener('change', () => renderChart(getRange())));
document.getElementById('gameFilter').addEventListener('input', () => renderGameOptions());
loadSafe();

initCollect(refreshGamesList);
