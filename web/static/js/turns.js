import { fetchWords } from './api.js';
import { DOWN, PLATFORM_TYPES, TIER_ORDER, UP, eventGroup, eventType, kindLabel } from './labels.js';
import { $, el, longDate, num, plural, reviewsWord, shiftDay, truncate } from './util.js';

// переломы: карточки во вкладке и последние три на обзоре
const LATEST_TURNS = 3;
let appId = null;
let actions = {};

// главное событие рядом с переломом: с разметкой новостей - старшее по уровню, даже если по весу оно числилось фоном
export function mainEvent(c) {
  const tiered = [...c.events, ...c.events_minor].filter(e => e.tier).sort((a, b) => TIER_ORDER[a.tier] - TIER_ORDER[b.tier]);
  if (tiered.length && tiered[0].tier !== 'background') {
    const e = tiered[0];
    return { color: eventGroup(e).color, text: `${e.tier === 'milestone' ? 'веха' : kindLabel(e.kind)}${e.future ? ' (анонс)' : ''}: ${e.title_ru}` };
  }
  if (c.events.length) {
    const e = c.events[0];
    return { color: eventGroup(e).color, text: `${eventType(e.type).label}: ${truncate(e.title, 90)}` };
  }
  if (c.platform_event) {
    return { color: null, text: `${PLATFORM_TYPES[c.platform_event.type] || 'Steam'}: ${truncate(c.platform_event.title, 90)}` };
  }
  if (c.events_minor.length) {
    const n = c.events_minor.length;
    return { text: `${n} ${plural(n, 'фоновое событие', 'фоновых события', 'фоновых событий')}`, muted: true };
  }
  return { text: 'событий рядом нет', muted: true };
}

function turnCard(c, { full }) {
  const down = c.score < 0;
  const card = el('article', 'turn');
  card.id = full ? `turn-${c.day}` : '';
  card.style.setProperty('--turn-color', down ? DOWN : UP);

  const head = el('div', 'turn-head');
  const shift = el('span', 'turn-shift', `${down ? '▼' : '▲'} ${Math.abs(c.score)} п.п.`);
  shift.style.color = down ? DOWN : UP;
  head.append(el('span', 'turn-date', longDate(c.day)), shift);
  if (c.verdict?.preliminary) {
    const badge = el('span', 'badge', 'предварительно');
    badge.title = 'окно «после» ещё не закрыто: поздние отзывы могут изменить вывод';
    head.append(badge);
  }
  card.append(head);

  if (c.positive_before != null && c.positive_after != null) {
    card.append(el('p', 'turn-numbers', `Позитивных за неделю: ${c.positive_before}% → ${c.positive_after}% · ` +
      `${num(c.reviews_before)} → ${num(c.reviews_after)} ${reviewsWord(c.reviews_after)}`));
  }

  const ev = mainEvent(c);
  const event = el('p', ev.muted ? 'turn-event muted' : 'turn-event');
  if (ev.color) {
    const dot = el('span', 'dot');
    dot.style.background = ev.color;
    event.append(dot);
  }
  event.append(ev.text);
  card.append(event);

  const v = c.verdict;
  // без проверенного разбора модели карточку дополняют слова недели после перелома - они считаются для любой игры
  if (!v?.checked) {
    const words = el('p', 'turn-words', ' ');
    words.dataset.day = c.day;
    words.dataset.vote = down ? 'down' : 'up';
    wordsObserver.observe(words);
    card.append(words);
  }
  if (v?.checked) {
    card.append(el('p', 'turn-text', v.what_happened));
    if (full && v.what_players_say) card.append(el('p', 'turn-text', v.what_players_say));
    if (full && v.excerpts?.length) {
      const details = el('details', 'excerpts');
      details.append(el('summary', null, 'Цитаты из отзывов'));
      v.excerpts.forEach(t => details.append(el('blockquote', null, t)));
      card.append(details);
    }
  } else if (v && full) {
    card.append(el('p', 'turn-text muted', 'Текст разбора не прошёл проверку кодом и не показывается.'));
  }

  const buttons = el('div', 'turn-actions');
  const onChart = el('button', 'link', 'на графике');
  onChart.type = 'button';
  onChart.onclick = () => actions.showOnChart(c.day);
  const reviews = el('button', 'link', 'отзывы недели →');
  reviews.type = 'button';
  reviews.onclick = () => actions.openReviews({ since: c.day, until: shiftDay(c.day, 7), vote: down ? 'down' : 'up' });
  buttons.append(onChart, reviews);
  card.append(buttons);
  return card;
}

// слова недели грузятся, только когда карточка показалась на экране: у игры бывает десяток переломов
const wordsObserver = new IntersectionObserver(entries => entries.forEach(async entry => {
  if (!entry.isIntersecting) return;
  const node = entry.target;
  wordsObserver.unobserve(node);
  const { day, vote } = node.dataset;
  try {
    const w = await fetchWords(appId, day, shiftDay(day, 7), vote);
    const list = (w.rising.length ? w.rising : w.top).slice(0, 5).map(x => x.word);
    node.replaceChildren(list.length ? `${vote === 'down' ? 'Недовольные' : 'Довольные'} чаще писали: `
      : w.reviews < 20 ? `За неделю всего ${w.reviews} ${reviewsWord(w.reviews)} на английском и русском - слов не выделить.`
      : 'Слов с заметным ростом за неделю нет.');
    if (list.length) node.append(el('b', null, list.join(', ')));
  } catch {
    node.remove();
  }
}), { rootMargin: '200px' });

export function renderTurns(data, handlers) {
  appId = data.game.app_id;
  actions = handlers;
  const cps = [...data.change_points].reverse();
  $('turns-note').textContent = data.change_points_note ||
    'Дни, когда доля положительных отзывов резко сменила уровень. Совпадение с событием по времени - подсказка, а не доказательство причины.';
  $('turns').replaceChildren(...cps.map(c => turnCard(c, { full: true })));
  $('turns-latest').replaceChildren(...(cps.length
    ? cps.slice(0, LATEST_TURNS).map(c => turnCard(c, { full: false }))
    : [el('p', 'muted', data.change_points_note || 'переломов не найдено')]));
}

export function focusTurn(day) {
  actions.selectTab('turns');
  const node = $(`turn-${day}`);
  if (!node) return;
  node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  document.querySelectorAll('.turn.focus').forEach(n => n.classList.remove('focus'));
  node.classList.add('focus');
}
