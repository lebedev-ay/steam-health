// токен есть, только если задан в окружении сервера - без него форма работает как раньше, заголовок не отправляется
const COLLECT_TOKEN =
  document.querySelector('meta[name="collect-token"]')?.content || '';

export async function fetchData({ appId, smoothing, minWeight, sensitivity }) {
  const res = await fetch(`/api/data?app_id=${appId}&smoothing=${smoothing}` +
    `&min_weight=${minWeight}&sensitivity=${sensitivity}`);
  const body = await res.json().catch(() => null);

  // на 400 и 500 в теле лежит {error}: рисовать нечего, и текст сервера полезнее падения на data.daily
  if (!res.ok || !body || !body.daily) {
    throw new Error((body && body.error) || `сервер ответил ${res.status}`);
  }

  return body;
}

export async function fetchGames() {
  const res = await fetch('/api/games');
  return res.json();
}

export async function fetchTask(taskId) {
  const res = await fetch(`/api/task/${taskId}`);
  return res.json();
}

export async function postCollect(appId, mode) {
  const headers = { 'Content-Type': 'application/json' };
  if (COLLECT_TOKEN) headers['X-Collect-Token'] = COLLECT_TOKEN;

  const res = await fetch('/api/collect', {
    method: 'POST',
    headers,
    body: JSON.stringify({ app_id: appId, mode })
  });
  const body = await res.json();

  if (!res.ok) {
    const err = new Error(body.error || res.status);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}
