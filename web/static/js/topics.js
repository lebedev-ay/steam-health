import { fetchAspect, fetchWords } from './api.js';
import { ASPECTS, CATEGORIES, DOWN, LANGUAGES, UP } from './labels.js';
import { $, el, longDate, monthBars, num, pct, plural, reviewsWord, ruDate, shiftDay, truncate } from './util.js';

// вкладка «Темы»: слова отзывов - для любой игры, темы по разметке и сводки месяца - у размечаемых
const TOP_ASPECTS = 12;
let appId = null;
let lastDay = null;
let actions = {};
let wordsDays = 30;

export function renderTopics(data, handlers) {
  appId = data.game.app_id;
  lastDay = data.daily.at(-1)?.day;
  actions = handlers;
  renderWords(wordsDays);
  renderAspects(data);
}

// --- слова отзывов: работают без модели ---

function wordChips(list, rising, onPick) {
  const box = el('div', 'words');
  list.forEach((x, i) => {
    const b = el('button', rising ? 'word rising' : 'word');
    b.type = 'button';
    b.style.animationDelay = `${i * 30}ms`;
    b.title = `${x.reviews} ${reviewsWord(x.reviews)} (${String(x.share).replace('.', ',')}%), ` +
      `в ${String(x.lift).replace('.', ',')} раза чаще, чем за 90 дней до периода. Щелчок - эти отзывы`;
    b.append(x.word, el('small', null, rising ? `×${String(x.lift).replace('.', ',')}` : `${Math.round(x.share)}%`));
    b.onclick = () => onPick(x.word);
    box.append(b);
  });
  return box;
}

async function renderWords(days) {
  wordsDays = days;
  document.querySelectorAll('#words-period [data-days]').forEach(b => {
    b.classList.toggle('active', Number(b.dataset.days) === days);
    b.onclick = () => renderWords(Number(b.dataset.days));
  });
  const box = $('words');
  if (!lastDay) {
    box.replaceChildren(el('p', 'muted', 'отзывов пока нет'));
    return;
  }
  const since = shiftDay(lastDay, -(days - 1)), until = shiftDay(lastDay, 1);
  const game = appId;
  box.classList.add('loading');
  const [down, up] = await Promise.all(['down', 'up'].map(v => fetchWords(game, since, until, v).catch(() => null)));
  box.classList.remove('loading');
  if (appId !== game || wordsDays !== days) return;     // пока считали, открыли другую игру или период

  const column = (w, vote, title, color) => {
    const col = el('div', 'words-col');
    col.style.setProperty('--word-color', color);
    col.append(el('h3', null, title),
               el('p', 'card-sub', w ? `${num(w.reviews)} ${reviewsWord(w.reviews)} на английском и русском за ${days} дней` : 'не удалось посчитать'));
    const pick = word => actions.openReviews({ since, until, vote, q: word });
    if (w?.rising.length) col.append(el('p', 'words-title', 'стали писать чаще'), wordChips(w.rising, true, pick));
    if (w?.top.length) col.append(el('p', 'words-title', 'пишут чаще всего'), wordChips(w.top, false, pick));
    else if (w) col.append(el('p', 'muted', 'мало отзывов для подсчёта'));
    return col;
  };
  box.replaceChildren(column(down, 'down', '▼ Недовольные', DOWN), column(up, 'up', '▲ Довольные', UP));
}

// --- темы по разметке модели ---

function aspectRow(item, labeled, scale) {
  const praise = 100 * item.positive / labeled;
  const critique = 100 * item.negative / labeled;
  const name = ASPECTS[item.aspect_id] || item.aspect_id;
  const row = el('button', 'aspect');
  row.type = 'button';
  row.title = `${name}: упоминаний ${num(item.mentions)} - хвалят ${num(item.positive)}, ругают ${num(item.negative)}, ` +
    `смешанно ${num(item.mixed)}. Щелчок - по месяцам и цитаты`;
  row.onclick = () => openAspect(item.aspect_id);

  const left = el('div', 'aspect-side left');
  const bad = el('div', 'bar down');
  bad.style.width = `${critique / scale * 100}%`;
  left.append(el('span', 'aspect-num', `${critique.toFixed(1)}%`), bad);
  const right = el('div', 'aspect-side');
  const good = el('div', 'bar up');
  good.style.width = `${praise / scale * 100}%`;
  right.append(good, el('span', 'aspect-num', `${praise.toFixed(1)}%`));
  row.append(left, el('div', 'aspect-name', name), right);
  return row;
}

function heatTable(months) {
  const monthList = [...new Set(months.map(m => m.month))].sort();
  const cats = Object.keys(CATEGORIES).filter(c => months.some(m => m.category_id === c));
  const byKey = new Map(months.map(m => [`${m.category_id}|${m.month}`, m]));
  const max = Math.max(...months.map(m => m.critique / m.labeled), 0.01);

  const table = el('table', 'heat');
  const head = table.createTHead().insertRow();
  head.append(el('th'));
  monthList.forEach(m => head.append(el('th', null, ruDate(m, { month: 'short' }).replace('.', ''))));
  const body = table.createTBody();
  cats.forEach(cat => {
    const row = body.insertRow();
    row.append(el('th', null, CATEGORIES[cat]));
    monthList.forEach(month => {
      const m = byKey.get(`${cat}|${month}`);
      const value = m ? m.critique / m.labeled : 0;
      const cell = el('td', null, m ? Math.round(100 * value) : '');
      // одна краска от фона к красному: сильнее цвет - больше доля отзывов с критикой
      cell.style.background = `color-mix(in oklab, ${DOWN} ${Math.round(80 * value / max)}%, #1a1920)`;
      if (m) cell.title = `${CATEGORIES[cat]}, ${ruDate(month, { month: 'long', year: 'numeric' })}: ` +
        `критика в ${Math.round(100 * value)}% размеченных отзывов (${m.critique} из ${m.labeled})`;
      row.append(cell);
    });
  });
  return table;
}

function callout(label, name, text, color) {
  const node = el('div', 'callout');
  node.style.borderLeft = `3px solid ${color}`;
  node.append(el('div', 'tile-label', label), el('div', 'callout-name', name), el('div', 'tile-note', text));
  return node;
}

function renderAspects(data) {
  const a = data.aspects;
  $('topics-empty').hidden = !!a;
  $('topics').hidden = !a;
  if (!a) return;

  const top = a.items.slice(0, TOP_ASPECTS);
  const scale = Math.max(...top.map(i => 100 * Math.max(i.positive, i.negative) / a.labeled), 1);
  const pain = [...a.items].sort((x, y) => y.negative - x.negative)[0];
  const love = [...a.items].sort((x, y) => y.positive - x.positive)[0];

  $('aspects-note').textContent = `По выборке из ${num(a.labeled)} ${plural(a.labeled, 'отзыва', 'отзывов', 'отзывов')} с текстом, ` +
    `размеченных моделью с ${longDate(a.since)} по ${longDate(a.until)}. Доля - от размеченных. Щелчок по теме - её история и цитаты.`;
  $('callouts').replaceChildren(
    ...(pain ? [callout('главная боль', ASPECTS[pain.aspect_id], `ругают в ${pct(pain.negative, a.labeled)}% отзывов`, DOWN)] : []),
    ...(love ? [callout('главная сила', ASPECTS[love.aspect_id], `хвалят в ${pct(love.positive, a.labeled)}% отзывов`, UP)] : []));

  const legend = el('div', 'aspect-legend');
  legend.append(el('div', null, '← ругают'), el('div'), el('div', null, 'хвалят →'));
  $('aspects').replaceChildren(legend, ...top.map(i => aspectRow(i, a.labeled, scale)));
  $('heat').replaceChildren(heatTable(a.months));

  $('digests-card').hidden = !data.digest.length;
  $('digests').replaceChildren(...data.digest.map(d => {
    const node = el('article', 'digest-item');
    node.append(el('p', 'eyebrow', ruDate(d.period_from, { month: 'long', year: 'numeric' })), el('h3', null, d.headline),
                el('p', null, d.summary));
    return node;
  }));
}

async function openAspect(aspectId) {
  const dialog = $('aspect');
  const body = $('aspect-body');
  const name = ASPECTS[aspectId] || aspectId;
  body.replaceChildren(el('h2', null, name), el('p', 'card-sub', 'загрузка…'));
  dialog.showModal();
  try {
    const d = await fetchAspect(appId, aspectId);
    const quotes = (title, list, color) => {
      const col = el('div');
      const h = el('h3', null, title);
      h.style.color = color;
      col.append(h, ...(list.length ? list.map(q => {
        const node = el('div', 'quote', truncate(q.text, 420));
        node.append(el('small', null, [longDate(q.day), LANGUAGES[q.language] || q.language, q.votes_up ? `полезно ${q.votes_up}` : null].filter(Boolean).join(' · ')));
        return node;
      }) : [el('p', 'muted', 'нет подходящих отзывов')]));
      return col;
    };
    const cols = el('div', 'aspect-quotes');
    cols.append(quotes('Хвалят', d.praise, UP), quotes('Ругают', d.critique, DOWN));
    body.replaceChildren(el('h2', null, name),
      el('p', 'card-sub', 'По месяцам: вверх - доля размеченных отзывов, где тему хвалят, вниз - где ругают. Наведите на столбик - точные числа.'),
      monthBars(d.months, UP, DOWN), cols);
  } catch (err) {
    body.replaceChildren(el('h2', null, name), el('p', 'form-error', err.message));
  }
}
