import { fetchMe, fetchTask, login, logout, postCollect } from './api.js';
import { $, el } from './util.js';

// вход и сбор игры: форма сбора есть только у вошедших, учётки выдаёт владелец (web/users.py)
const STORAGE_KEY = 'steamHealthCollectTask';
const POLL_MS = 2000;
// Celery отдаёт PENDING и для задачи в очереди, и для неизвестного id - ожидание ограничено
const PENDING_TRIES = 30;

let onCollected = () => {};

function renderAccount(me) {
  const box = $('account');
  if (!me.enabled) {
    box.replaceChildren();
    return;
  }
  if (!me.login) {
    const btn = el('button', 'ghost', 'Войти');
    btn.type = 'button';
    btn.onclick = () => { $('login-error').textContent = ''; $('login').showModal(); };
    box.replaceChildren(btn);
    return;
  }
  const add = el('button', 'primary', '+ Игра');
  add.type = 'button';
  add.title = 'добавить или обновить игру';
  add.onclick = () => $('collect').showModal();
  const out = el('button', 'ghost', 'Выйти');
  out.type = 'button';
  out.onclick = async () => { renderAccount(await logout().then(() => ({ enabled: true, login: null }))); };
  box.replaceChildren(el('span', 'who', me.login), add, out);
}

function setRunning(running) {
  ['collect-id', 'collect-mode', 'collect-btn'].forEach(id => { $(id).disabled = running; });
}

function status(text, kind = '') {
  $('collect-status').className = `collect-status ${kind}`;
  $('collect-status').textContent = text;
}

function finish(text, kind) {
  status(text, kind);
  setRunning(false);
  try { localStorage.removeItem(STORAGE_KEY); } catch {}
}

// own = false - следим за чужим сбором после 409: список игр обновить надо, открытую игру не трогаем
function poll(taskId, own = true) {
  setRunning(true);
  let pendingLeft = PENDING_TRIES;
  const tick = async () => {
    let body;
    try {
      body = await fetchTask(taskId);
    } catch (err) {
      if (err.status === 401) return finish('сессия закончилась - войдите снова', 'error');
      status('нет связи с сервером, пробую ещё раз…');
      return setTimeout(tick, POLL_MS);
    }
    if (body.state === 'SUCCESS') {
      const name = body.result?.name || 'игра';
      finish(own ? `готово: ${name}${body.result?.reviews ? ' - ' + body.result.reviews : ''}`
                 : `чужой сбор закончен (${name}), запустите свой заново`, 'ok');
      return onCollected(own ? body.result?.app_id : null);
    }
    if (body.state === 'FAILURE') {
      return finish(own ? `ошибка: ${body.error || 'сбор не удался'}` : 'чужой сбор упал, запустите свой заново', 'error');
    }
    if (body.state === 'PROGRESS' && body.meta) {
      const m = body.meta;
      status(`шаг ${m.step} из ${m.total}: ${m.message}${m.progress ? ` (${m.progress})` : ''}`);
    } else if (--pendingLeft <= 0) {
      return finish('задача не найдена: очередь её не знает, воркер мог не запуститься', 'error');
    } else {
      status('задача в очереди…');
    }
    setTimeout(tick, POLL_MS);
  };
  tick();
}

export async function initAccount(onCollectedCallback) {
  onCollected = onCollectedCallback;
  document.querySelectorAll('dialog [data-close]').forEach(btn => { btn.onclick = () => btn.closest('dialog').close(); });

  $('login-form').addEventListener('submit', async e => {
    e.preventDefault();
    const f = e.target.elements;
    try {
      const me = await login(f.login.value.trim(), f.password.value);
      f.password.value = '';
      $('login').close();
      renderAccount({ enabled: true, login: me.login });
    } catch (err) {
      $('login-error').textContent = err.message;
    }
  });

  $('collect-form').addEventListener('submit', async e => {
    e.preventDefault();
    const raw = $('collect-id').value.trim();
    if (!raw) return;
    setRunning(true);
    status('запускаю…');
    try {
      const { task_id } = await postCollect(raw, $('collect-mode').value);
      try { localStorage.setItem(STORAGE_KEY, task_id); } catch {}
      poll(task_id);
    } catch (err) {
      if (err.status === 409) {
        status('сейчас идёт сбор другой игры, слежу за ним…');
        poll(err.body.busy_task_id, false);
      } else {
        finish(`ошибка: ${err.message}`, 'error');
      }
    }
  });

  const me = await fetchMe().catch(() => ({ enabled: false, login: null }));
  renderAccount(me);
  let saved = null;
  try { saved = localStorage.getItem(STORAGE_KEY); } catch {}
  if (saved && me.login) poll(saved);
}
