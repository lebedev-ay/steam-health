import { fetchTask, postCollect } from './api.js';

// сбор игры в фоне: задача в очереди Celery, страница опрашивает её статус. id задачи переживает перезагрузку страницы
const STORAGE_KEY = 'steamHealthCollectTask';
const POLL_MS = 2000;
// Celery отдаёт PENDING и для задачи в очереди, и для неизвестного id - ожидание ограничено
const PENDING_TRIES = 30;

const $ = id => document.getElementById(id);

function setRunning(running) {
  ['collect-id', 'collect-mode', 'collect-btn'].forEach(id => { $(id).disabled = running; });
}

function show(text, kind = 'busy') {
  const box = $('collect-status');
  box.className = `collect-status ${kind}`;
  box.textContent = text;
}

function finish(text, kind) {
  show(text, kind);
  setRunning(false);
  try { localStorage.removeItem(STORAGE_KEY); } catch {}
}

// own = false - следим за чужим сбором после 409: список игр обновить надо, а открытую игру не трогаем
function poll(taskId, onDone, own = true) {
  setRunning(true);
  let pendingLeft = PENDING_TRIES;

  const tick = async () => {
    let body;
    try {
      body = await fetchTask(taskId);
    } catch {
      show('нет связи с сервером, пробую ещё раз…');
      return setTimeout(tick, POLL_MS);
    }

    if (body.state === 'SUCCESS') {
      const name = body.result?.name || 'игра';
      finish(own ? `готово: ${name}${body.result?.reviews ? ' - ' + body.result.reviews : ''}`
                 : `чужой сбор закончен (${name}), запустите свой заново`, 'ok');
      return onDone(own ? body.result?.app_id : null);
    }
    if (body.state === 'FAILURE') {
      return finish(own ? `ошибка: ${body.error || 'сбор не удался'}` : 'чужой сбор упал, запустите свой заново', 'error');
    }
    if (body.state === 'PROGRESS' && body.meta) {
      const m = body.meta;
      show(`шаг ${m.step} из ${m.total}: ${m.message}${m.progress ? ` (${m.progress})` : ''}`);
    } else if (--pendingLeft <= 0) {
      return finish('задача не найдена: очередь её не знает, воркер мог не запуститься', 'error');
    } else {
      show('задача в очереди…');
    }
    setTimeout(tick, POLL_MS);
  };
  tick();
}

export function initCollect(onDone) {
  $('collect-form').addEventListener('submit', async e => {
    e.preventDefault();
    const raw = $('collect-id').value.trim();
    if (!raw) return;

    setRunning(true);
    show('запускаю…');
    try {
      const { task_id } = await postCollect(raw, $('collect-mode').value);
      try { localStorage.setItem(STORAGE_KEY, task_id); } catch {}
      poll(task_id, onDone);
    } catch (err) {
      if (err.status === 409) {
        show('сейчас идёт сбор другой игры, слежу за ним…');
        poll(err.body.busy_task_id, onDone, false);
      } else {
        finish(`ошибка: ${err.message}`, 'error');
      }
    }
  });

  let saved = null;
  try { saved = localStorage.getItem(STORAGE_KEY); } catch {}
  if (saved) {
    $('collect').open = true;
    poll(saved, onDone);
  }
}
