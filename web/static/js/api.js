// токен есть, только если задан в окружении сервера; без него заголовок не отправляется
const COLLECT_TOKEN = document.querySelector('meta[name="collect-token"]')?.content || '';

async function getJson(url, options) {
  const res = await fetch(url, options);
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(body?.error || `сервер ответил ${res.status}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

export const fetchGame = (appId, { smoothing, sensitivity }) =>
  getJson(`/api/game/${appId}?smoothing=${smoothing}&sensitivity=${sensitivity}`);

export const fetchGames = () => getJson('/api/games');

export const fetchTask = taskId => getJson(`/api/task/${taskId}`);

export function postCollect(appId, mode) {
  const headers = { 'Content-Type': 'application/json' };
  if (COLLECT_TOKEN) headers['X-Collect-Token'] = COLLECT_TOKEN;
  return getJson('/api/collect', { method: 'POST', headers, body: JSON.stringify({ app_id: appId, mode }) });
}
