async function request(url, options) {
  const res = await fetch(url, { credentials: 'same-origin', ...options });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(body?.error || `сервер ответил ${res.status}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

// изменения - только JSON: форма с чужого сайта такой запрос не пошлёт, а сервер ещё и сверяет Origin
const post = (url, data) => request(url, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data || {})
});

export const fetchGames = () => request('/api/games');
export const fetchGame = (appId, { smoothing, sensitivity }) =>
  request(`/api/game/${appId}?smoothing=${smoothing}&sensitivity=${sensitivity}`);
export const fetchAspect = (appId, aspect) => request(`/api/game/${appId}/aspect/${encodeURIComponent(aspect)}`);
export const fetchReviews = (appId, params) => request(`/api/game/${appId}/reviews?${new URLSearchParams(params)}`);
export const fetchWords = (appId, since, until, vote) =>
  request(`/api/game/${appId}/words?${new URLSearchParams({ since, until, vote })}`);

export const fetchMe = () => request('/api/me');
export const login = (name, password) => post('/api/login', { login: name, password });
export const logout = () => post('/api/logout');
export const postCollect = (appId, mode) => post('/api/collect', { app_id: appId, mode });
export const fetchTask = taskId => request(`/api/task/${taskId}`);
