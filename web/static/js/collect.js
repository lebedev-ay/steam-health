import { fetchTask, postCollect } from './api.js';

// --- фоновый сбор данных по игре ---

const COLLECT_STORAGE_KEY = 'steamHealthCollectTask';

let onCollected = () => {};

function setCollectRunning(running) {
  document.getElementById('collectBtn').disabled = running;
  document.getElementById('collectAppId').disabled = running;
  document.getElementById('collectMode').disabled = running;
}

export function showCollectProgress(text, kind) {
  const el = document.getElementById('collectProgress');
  el.replaceChildren();
  if (kind === 'busy') {
    const spinner = document.createElement('span');
    spinner.className = 'spinner-sm';
    el.append(spinner);
  }
  el.append(document.createTextNode(text));
  el.style.color = kind === 'error' ? '#ff6b5b' : (kind === 'ok' ? '#3ddc84' : '#8a95a3');
}

// Celery отдаёт PENDING и для задачи в очереди, и для неизвестного id - различить их нельзя, поэтому ожидание ограничено по времени
const PENDING_TRIES = 30;
const POLL_INTERVAL_MS = 2000;

// own = false, когда следим за чужим сбором после 409: список игр обновить надо, а выбор в селекте и график - не наши, не трогаем
function pollTask(taskId, own = true) {
  setCollectRunning(true);
  let pendingLeft = PENDING_TRIES;

  const tick = async () => {
    let body;
    try {
      body = await fetchTask(taskId);
    } catch (e) {
      showCollectProgress('нет связи с сервером, пробую ещё раз…', 'busy');
      setTimeout(tick, POLL_INTERVAL_MS);
      return;
    }

    if (body.state === 'PROGRESS' && body.meta) {
      const m = body.meta;
      const extra = m.progress ? ` (${m.progress})` : '';
      showCollectProgress(`шаг ${m.step}/${m.total}: ${m.message}${extra}`, 'busy');
      setTimeout(tick, POLL_INTERVAL_MS);
      return;
    }

    if (body.state === 'SUCCESS') {
      setCollectRunning(false);
      localStorage.removeItem(COLLECT_STORAGE_KEY);
      if (own) {
        showCollectProgress(`готово: ${body.result?.name || 'игра собрана'}`, 'ok');
        onCollected(body.result?.app_id);
      } else {
        showCollectProgress(`чужой сбор закончен (${body.result?.name || 'игра собрана'}), ` +
          'запустите свой заново', 'ok');
        onCollected();
      }
      return;
    }

    if (body.state === 'FAILURE') {
      showCollectProgress(own
        ? `ошибка: ${body.error || 'сбор не удался'}`
        : 'чужой сбор упал, запустите свой заново', 'error');
      setCollectRunning(false);
      localStorage.removeItem(COLLECT_STORAGE_KEY);
      return;
    }

    // PENDING / STARTED - задача в очереди, прогресса ещё нет
    if (--pendingLeft <= 0) {
      showCollectProgress('задача не найдена: очередь её не знает, ' +
        'воркер мог не запуститься', 'error');
      setCollectRunning(false);
      localStorage.removeItem(COLLECT_STORAGE_KEY);
      return;
    }
    showCollectProgress('задача поставлена в очередь…', 'busy');
    setTimeout(tick, POLL_INTERVAL_MS);
  };

  tick();
}

export function initCollect(onCollectedCallback) {
  onCollected = onCollectedCallback;

  document.getElementById('collectBtn').addEventListener('click', async () => {
    const rawId = document.getElementById('collectAppId').value.trim();
    const mode = document.getElementById('collectMode').value;
    if (!rawId) return;

    setCollectRunning(true);
    showCollectProgress('запускаю…', 'busy');

    try {
      const body = await postCollect(rawId, mode);
      localStorage.setItem(COLLECT_STORAGE_KEY, JSON.stringify({ taskId: body.task_id }));
      pollTask(body.task_id);
    } catch (e) {
      if (e.status === 409) {
        // сбор уже идёт у другой игры - подписываемся на её прогресс тем же pollTask, чтобы видеть реальный ход.
        // Запрошенная игра при этом в очередь не попала, о чём говорим по окончании
        showCollectProgress('сейчас идёт сбор другой игры, слежу за прогрессом…', 'busy');
        pollTask(e.body.busy_task_id, false);
        return;
      }
      if (e.status) {
        showCollectProgress(`ошибка: ${e.message}`, 'error');
        setCollectRunning(false);
        return;
      }
      showCollectProgress('не удалось запустить сбор: ' + e.message, 'error');
      setCollectRunning(false);
    }
  });

  document.getElementById('collectAppId').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('collectBtn').click();
  });

  // переживает случайную перезагрузку страницы во время сбора
  (() => {
    const saved = localStorage.getItem(COLLECT_STORAGE_KEY);
    if (!saved) return;
    try {
      const { taskId } = JSON.parse(saved);
      if (taskId) pollTask(taskId);
    } catch (e) {}
  })();
}
