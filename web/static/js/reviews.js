import { fetchReviews } from './api.js';
import { ASPECTS, LANGUAGES } from './labels.js';
import { $, el, highlighted, hours, longDate, num, shiftDay } from './util.js';

// обозреватель отзывов игры: период, оценка, язык, порядок; страницами по 20
let appId = null;
let offset = 0;
let request = 0;

const form = () => $('review-filters');

function params() {
  const f = new FormData(form());
  const out = { offset };
  for (const [k, v] of f.entries()) if (v) out[k] = v;
  // в форме «по» включительно, серверу нужна граница «до», не входящая в период
  if (out.until) out.until = shiftDay(out.until, 1);
  return out;
}

function reviewCard(r) {
  const node = el('article', 'review');
  const head = el('div', 'review-head');
  head.append(el('span', `vote ${r.up ? 'up' : 'down'}`, r.up ? '▲ рекомендует' : '▼ не рекомендует'),
              el('span', null, longDate(r.day)));
  if (r.minutes != null) head.append(el('span', null, `наиграно ${hours(r.minutes)}`));
  head.append(el('span', null, LANGUAGES[r.language] || r.language));
  if (r.votes_up) head.append(el('span', null, `полезно ${num(r.votes_up)}`));
  if (r.answered) head.append(el('span', null, 'есть ответ разработчика'));

  const text = el('p', 'review-text clamped');
  text.append(highlighted(r.text, form().elements.q.value.trim()));
  text.title = 'щелчок - показать целиком';
  text.onclick = () => text.classList.toggle('clamped');
  node.append(head, text);

  if (r.tags?.length) {
    const tags = el('div', 'tags');
    r.tags.forEach(t => {
      const sign = t.sentiment === '+' ? 'up' : t.sentiment === '-' ? 'down' : '';
      tags.append(el('span', `tag ${sign}`, `${t.sentiment} ${ASPECTS[t.aspect] || (t.aspect === 'overall_impression' ? 'общее впечатление' : t.aspect)}`));
    });
    node.append(tags);
  }
  return node;
}

async function load(append) {
  const my = ++request;
  const list = $('reviews');
  if (!append) {
    offset = 0;
    list.classList.add('loading');
  }
  try {
    const page = await fetchReviews(appId, params());
    if (my !== request) return;     // пока ждали, фильтр сменился - этот ответ уже не нужен
    const cards = page.items.map(reviewCard);
    if (append) list.append(...cards);
    else list.replaceChildren(...(cards.length ? cards : [el('p', 'muted', 'отзывов с текстом под эти условия нет')]));
    $('reviews-more').hidden = !page.more;
    offset += page.items.length;
  } catch (err) {
    list.replaceChildren(el('p', 'form-error', err.message));
  } finally {
    list.classList.remove('loading');
  }
}

export function initReviews() {
  form().addEventListener('change', () => load(false));
  // слово ищется по мере ввода, но не на каждую букву
  let typing = null;
  form().elements.q.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => load(false), 350); });
  form().addEventListener('submit', e => e.preventDefault());
  $('reviews-more').onclick = () => load(true);
}

// новая игра: языки - из её разрезов аудитории, период по умолчанию - последний месяц ряда
export function resetReviews(game, languages, lastDay) {
  appId = game.app_id;
  const f = form();
  const select = f.elements.lang;
  select.replaceChildren(new Option('любой', ''), ...languages.map(code => new Option(LANGUAGES[code] || code, code)));
  f.elements.vote.value = '';
  f.elements.q.value = '';
  f.elements.sort.value = 'helpful';
  f.elements.until.value = lastDay || '';
  f.elements.since.value = lastDay ? shiftDay(lastDay, -29) : '';
  $('reviews').replaceChildren();
  $('reviews-more').hidden = true;
}

// открыть с условиями снаружи: неделя перелома или обновления
export function showReviews({ since, until, vote = '', q = '' }) {
  const f = form();
  f.elements.since.value = since;
  f.elements.until.value = shiftDay(until, -1);
  f.elements.vote.value = vote;
  f.elements.q.value = q;
  load(false);
}

export const loadReviews = () => load(false);
