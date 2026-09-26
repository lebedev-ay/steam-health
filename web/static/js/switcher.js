import { UP, DOWN } from './labels.js';
import { $, el, pct, sparkline } from './util.js';

// быстрый выбор игры: «/» или Ctrl+K, стрелки и Enter. Список - из обзора, с долей позитива и полугодом по неделям
let games = [];
let selected = 0;
let onPick = () => {};

function filtered() {
  const q = $('switcher-input').value.trim().toLowerCase();
  // сначала совпадения в названии, затем в жанре или разработчике
  const inName = games.filter(g => g.game_name.toLowerCase().includes(q));
  const inMeta = games.filter(g => !inName.includes(g) && [g.genres, g.developers].some(x => (x || '').toLowerCase().includes(q)));
  return [...inName, ...inMeta];
}

function render() {
  const list = filtered();
  selected = Math.min(selected, Math.max(list.length - 1, 0));
  $('switcher-list').replaceChildren(...list.map((g, i) => {
    const li = el('li');
    li.setAttribute('role', 'option');
    li.setAttribute('aria-selected', String(i === selected));
    const now = pct(g.positive_30, g.reviews_30);
    const before = pct(g.positive_prev, g.reviews_prev);
    const name = el('span', null, g.game_name);
    name.append(el('small', null, [g.genres, g.developers].filter(Boolean).join(' · ')));
    li.append(name,
              sparkline(g.spark, now != null && before != null && now < before ? DOWN : UP),
              el('span', 'num', now == null ? '—' : `${now}%`));
    li.onclick = () => pick(g);
    return li;
  }));
}

function pick(g) {
  $('switcher').close();
  onPick(g.app_id);
}

export function open() {
  $('switcher-input').value = '';
  selected = 0;
  render();
  $('switcher').showModal();
  $('switcher-input').focus();
}

export function initSwitcher(onPickCallback) {
  onPick = onPickCallback;
  $('switcher-open').onclick = open;
  $('switcher-input').addEventListener('input', () => { selected = 0; render(); });
  $('switcher-input').addEventListener('keydown', e => {
    const list = filtered();
    if (e.key === 'ArrowDown') selected = Math.min(selected + 1, list.length - 1);
    else if (e.key === 'ArrowUp') selected = Math.max(selected - 1, 0);
    else if (e.key === 'Enter' && list[selected]) {
      // без preventDefault то же нажатие после закрытия окна «нажало» бы кнопку, на которую вернулся фокус
      e.preventDefault();
      return pick(list[selected]);
    }
    else return;
    e.preventDefault();
    render();
    $('switcher-list').children[selected]?.scrollIntoView({ block: 'nearest' });
  });
  // клик по фону закрывает окно
  $('switcher').addEventListener('click', e => { if (e.target === $('switcher')) $('switcher').close(); });
  document.addEventListener('keydown', e => {
    const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName);
    if ((e.key === '/' && !typing) || (e.key === 'k' && (e.ctrlKey || e.metaKey))) {
      e.preventDefault();
      open();
    }
  });
}

export function setGames(list) {
  games = list;
}
