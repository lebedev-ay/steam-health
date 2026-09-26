import { SEGMENTS } from './labels.js';
import { $, el, num, pct, reviewsWord } from './util.js';

// вкладка «Аудитория»: доля позитива по группам игроков
const TOP_LANGUAGES = 8;
// сегмент меньше этого числа отзывов в выводы «кто доволен меньше всех» не идёт: на десятке отзывов доля скачет сама по себе
export const MIN_SEGMENT = 50;

function segmentRows(dimension, rows) {
  const labels = SEGMENTS[dimension].labels;
  let list = rows.map(r => ({ ...r, label: labels[r.segment] || r.segment }));
  if (dimension === 'language' && list.length > TOP_LANGUAGES) {
    const rest = list.slice(TOP_LANGUAGES);
    list = list.slice(0, TOP_LANGUAGES).concat({
      label: 'остальные', reviews: rest.reduce((a, r) => a + r.reviews, 0), positive: rest.reduce((a, r) => a + r.positive, 0)
    });
  }
  return list;
}

function insight(list) {
  const big = list.filter(r => r.reviews >= MIN_SEGMENT && r.label !== 'остальные');
  if (big.length < 2) return null;
  const rate = r => r.positive / r.reviews;
  const low = big.reduce((a, r) => (rate(r) < rate(a) ? r : a));
  const high = big.reduce((a, r) => (rate(r) > rate(a) ? r : a));
  if (pct(high.positive, high.reviews) - pct(low.positive, low.reviews) < 5) return 'Доля позитива почти не зависит от этого признака.';
  return `Довольнее всех - «${high.label}» (${pct(high.positive, high.reviews)}%), меньше всех - «${low.label}» (${pct(low.positive, low.reviews)}%).`;
}

function segmentCard(dimension, rows) {
  const list = segmentRows(dimension, rows);
  const card = el('div', 'segment');
  card.append(el('h3', null, SEGMENTS[dimension].title));
  const text = insight(list);
  if (text) card.append(el('p', 'segment-insight', text));
  const total = list.reduce((a, r) => a + r.reviews, 0);
  list.forEach(r => {
    const p = pct(r.positive, r.reviews);
    const row = el('div', 'segment-row');
    row.title = `${r.label}: ${num(r.reviews)} ${reviewsWord(r.reviews)}, положительных ${p}%`;
    const meter = el('div', 'meter');
    const fill = el('i');
    fill.style.width = `${p}%`;
    meter.append(fill);
    row.append(el('span', 'segment-label', r.label), meter, el('span', 'segment-num', `${p}%`),
               el('span', 'segment-share', `${pct(r.reviews, total)}% отз.`));
    card.append(row);
  });
  return card;
}

export function renderAudience(segments) {
  // разрез с одним сегментом ничего не сравнивает: у игры без раннего доступа все отзывы - «после релиза»
  const cards = Object.keys(SEGMENTS).filter(d => (segments[d] || []).length > 1).map(d => segmentCard(d, segments[d]));
  $('audience').replaceChildren(...(cards.length ? cards : [el('p', 'muted', 'отзывов пока нет')]));
}
