import { ASPECTS, CATEGORIES, PLATFORM_TYPES, SEGMENTS, UP, DOWN, eventType, steamRating } from './labels.js';
import { el, num, pct, plural, ruDate, truncate } from './util.js';

const RECENT_DAYS = 30;
const TOP_ASPECTS = 12;
const TOP_LANGUAGES = 8;
// сегмент меньше этого числа отзывов в выводы «кто доволен меньше всех» не идёт: на десятке отзывов доля скачет сама по себе
const MIN_SEGMENT = 50;

// --- шапка игры ---

export function renderHeader(game) {
  const meta = [
    game.developers && `разработчик: ${game.developers}`,
    game.publishers && game.publishers !== game.developers && `издатель: ${game.publishers}`,
    game.genres,
    game.release_date && `релиз ${ruDate(game.release_date, { year: 'numeric', month: 'long', day: 'numeric' })}`,
    game.metacritic_score && `Metacritic ${game.metacritic_score}`
  ].filter(Boolean);

  const title = el('h1', 'game-title', game.game_name);
  if (game.collection_status === 'partial') {
    title.append(el('span', 'badge', 'данные неполные'));
  }
  const link = el('a', 'steam-link', 'Открыть в Steam ↗');
  link.href = `https://store.steampowered.com/app/${game.app_id}/`;
  link.target = '_blank';
  link.rel = 'noopener';

  document.getElementById('game-head').replaceChildren(title, el('p', 'game-meta', meta.join(' · ')), link);
}

// --- ключевые числа ---

function tile(label, value, note, sub, subColor) {
  const node = el('div', 'tile');
  node.append(el('div', 'tile-label', label), el('div', 'tile-value', value));
  if (note) node.append(el('div', 'tile-note', note));
  if (sub) {
    const s = el('div', 'tile-sub', sub);
    if (subColor) s.style.color = subColor;
    node.append(s);
  }
  return node;
}

function share(days) {
  const total = days.reduce((a, d) => a + d.total, 0);
  const positive = days.reduce((a, d) => a + d.positive, 0);
  return { total, pct: pct(positive, total) };
}

export function renderKpis(data) {
  const box = document.getElementById('kpis');
  const daily = data.daily;
  if (!daily.length) {
    box.replaceChildren();
    return;
  }

  const all = share(daily);
  const recent = share(daily.slice(-RECENT_DAYS));
  const before = share(daily.slice(-2 * RECENT_DAYS, -RECENT_DAYS));
  const diff = recent.pct != null && before.pct != null ? recent.pct - before.pct : null;
  const peak = daily.reduce((a, d) => (d.total > a.total ? d : a), daily[0]);
  const cps = data.change_points;
  const drops = cps.filter(c => c.score < 0).length;
  const withVerdict = cps.filter(c => c.verdict).length;

  box.replaceChildren(
    tile(`Последние ${RECENT_DAYS} дней`, recent.pct != null ? `${recent.pct}%` : '—',
         `${steamRating(recent.pct, recent.total)} · ${num(recent.total)} ${plural(recent.total, 'отзыв', 'отзыва', 'отзывов')}`,
         diff == null ? null : diff === 0 ? 'как в прошлые 30 дней'
           : `${diff > 0 ? '▲' : '▼'} ${Math.abs(diff)} п.п. к прошлым 30 дням`,
         diff > 0 ? UP : diff < 0 ? DOWN : null),
    tile('За всё собранное время', `${all.pct}%`,
         `${steamRating(all.pct, all.total)} · ${num(all.total)} ${plural(all.total, 'отзыв', 'отзыва', 'отзывов')}`,
         `с ${ruDate(daily[0].day)}`),
    tile('Отзывов в день', num(data.median_volume), 'медиана',
         `пик ${num(peak.total)} - ${ruDate(peak.day)}`),
    tile('Переломы настроения', String(cps.length),
         `${drops} ${plural(drops, 'спад', 'спада', 'спадов')}, ${cps.length - drops} ${plural(cps.length - drops, 'рост', 'роста', 'ростов')}`,
         withVerdict ? `по ${withVerdict} есть разбор отзывов` : null)
  );
}

// --- переломы ---

function mainEvent(c) {
  if (c.events.length) {
    const e = c.events[0];
    return { color: eventType(e.type).color, text: `${eventType(e.type).label}: ${truncate(e.title, 90)}` };
  }
  if (c.platform_event) {
    return { color: null, text: `${PLATFORM_TYPES[c.platform_event.type] || 'Steam'}: ${truncate(c.platform_event.title, 90)}` };
  }
  if (c.events_minor.length) {
    const n = c.events_minor.length;
    return { color: null, text: `${n} ${plural(n, 'фоновое событие', 'фоновых события', 'фоновых событий')}`, muted: true };
  }
  return { color: null, text: 'событий рядом нет', muted: true };
}

function turnCard(c, onSelect) {
  const down = c.score < 0;
  const card = el('article', 'turn');
  card.id = `turn-${c.day}`;

  const head = el('div', 'turn-head');
  const shift = el('span', 'turn-shift', `${down ? '▼' : '▲'} ${Math.abs(c.score)} п.п.`);
  shift.style.color = down ? DOWN : UP;
  head.append(el('span', 'turn-date', ruDate(c.day, { day: 'numeric', month: 'long', year: 'numeric' })), shift);
  if (c.verdict?.preliminary) {
    const badge = el('span', 'badge', 'предварительно');
    badge.title = 'окно «после» ещё не закрыто: поздние отзывы могут изменить вывод';
    head.append(badge);
  }
  card.append(head);

  if (c.positive_before != null && c.positive_after != null) {
    card.append(el('p', 'turn-numbers', `Позитивных за неделю: ${c.positive_before}% → ${c.positive_after}%`));
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
  if (v && v.checked) {
    card.append(el('p', 'turn-text', v.what_happened));
    if (v.what_players_say) card.append(el('p', 'turn-text', v.what_players_say));
    if (v.excerpts?.length) {
      const details = el('details', 'excerpts');
      details.append(el('summary', null, 'Цитаты из отзывов'));
      v.excerpts.forEach(t => details.append(el('blockquote', null, t)));
      card.append(details);
    }
  } else if (v) {
    card.append(el('p', 'turn-text muted', 'Текст разбора не прошёл проверку кодом и не показывается.'));
  }

  const btn = el('button', 'link-button', 'Показать на графике');
  btn.type = 'button';
  btn.addEventListener('click', () => onSelect(c.day));
  card.append(btn);
  return card;
}

export function renderTurns(data, onSelect) {
  const list = document.getElementById('turns');
  const cps = [...data.change_points].reverse();
  document.getElementById('turns-note').textContent = data.change_points_note ||
    'Дни, когда доля позитивных отзывов резко сменила уровень. Совпадение с событием по времени - подсказка, а не доказательство причины.';
  list.replaceChildren(...cps.map(c => turnCard(c, onSelect)));
}

export function focusTurn(day) {
  const node = document.getElementById(`turn-${day}`);
  if (!node) return;
  node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  document.querySelectorAll('.turn.focus').forEach(n => n.classList.remove('focus'));
  node.classList.add('focus');
}

// --- темы отзывов ---

function aspectRow(item, labeled, scale) {
  const praise = 100 * item.positive / labeled;
  const critique = 100 * item.negative / labeled;
  const row = el('div', 'aspect');
  row.title = `${ASPECTS[item.aspect_id] || item.aspect_id}: упоминаний ${num(item.mentions)} - ` +
    `хвалят ${num(item.positive)}, ругают ${num(item.negative)}, смешанно ${num(item.mixed)}`;

  const left = el('div', 'aspect-side left');
  const bad = el('div', 'bar');
  bad.style.width = `${critique / scale * 100}%`;
  bad.style.background = DOWN;
  left.append(el('span', 'aspect-num', `${critique.toFixed(1)}%`), bad);

  const right = el('div', 'aspect-side');
  const good = el('div', 'bar');
  good.style.width = `${praise / scale * 100}%`;
  good.style.background = UP;
  right.append(good, el('span', 'aspect-num', `${praise.toFixed(1)}%`));

  row.append(left, el('div', 'aspect-name', ASPECTS[item.aspect_id] || item.aspect_id), right);
  return row;
}

function heatTable(months, labeled) {
  const monthList = [...new Set(months.map(m => m.month))].sort();
  const cats = Object.keys(CATEGORIES).filter(c => months.some(m => m.category_id === c));
  const byKey = new Map(months.map(m => [`${m.category_id}|${m.month}`, m]));
  const values = months.map(m => m.critique / m.labeled);
  const max = Math.max(...values, 0.01);

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
      cell.style.background = `color-mix(in oklab, ${DOWN} ${Math.round(85 * value / max)}%, #1a1d21)`;
      cell.title = m ? `${CATEGORIES[cat]}, ${ruDate(month, { month: 'long', year: 'numeric' })}: ` +
        `критика в ${Math.round(100 * value)}% размеченных отзывов (${m.critique} из ${m.labeled})` : '';
      row.append(cell);
    });
  });
  return table;
}

export function renderAspects(aspects) {
  const section = document.getElementById('aspects-section');
  section.hidden = !aspects;
  if (!aspects) return;

  const { labeled, items } = aspects;
  const top = items.slice(0, TOP_ASPECTS);
  const scale = Math.max(...top.map(i => 100 * Math.max(i.positive, i.negative) / labeled), 1);
  const worst = [...items].sort((a, b) => b.negative - a.negative)[0];
  const best = [...items].sort((a, b) => b.positive - a.positive)[0];

  document.getElementById('aspects-note').textContent =
    `По выборке из ${num(labeled)} ${plural(labeled, 'отзыва', 'отзывов', 'отзывов')} с текстом, размеченных моделью ` +
    `за ${ruDate(aspects.since)} - ${ruDate(aspects.until)}. Доля - от размеченных отзывов.`;

  const callouts = el('div', 'callouts');
  if (worst) callouts.append(callout('Главная боль', ASPECTS[worst.aspect_id], `ругают в ${pct(worst.negative, labeled)}% отзывов`, DOWN));
  if (best) callouts.append(callout('Главная сила', ASPECTS[best.aspect_id], `хвалят в ${pct(best.positive, labeled)}% отзывов`, UP));

  const legend = el('div', 'aspect');
  legend.classList.add('aspect-legend');
  legend.append(el('div', 'aspect-side left', '← ругают'), el('div', 'aspect-name', ''), el('div', 'aspect-side', 'хвалят →'));

  document.getElementById('aspects').replaceChildren(callouts, legend, ...top.map(i => aspectRow(i, labeled, scale)));
  document.getElementById('heat').replaceChildren(heatTable(aspects.months, labeled));
}

function callout(label, name, text, color) {
  const node = el('div', 'callout');
  node.style.borderColor = color;
  node.append(el('div', 'tile-label', label), el('div', 'callout-name', name), el('div', 'tile-note', text));
  return node;
}

// --- аудитория ---

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
  const low = big.reduce((a, r) => (r.positive / r.reviews < a.positive / a.reviews ? r : a));
  const high = big.reduce((a, r) => (r.positive / r.reviews > a.positive / a.reviews ? r : a));
  const gap = pct(high.positive, high.reviews) - pct(low.positive, low.reviews);
  if (gap < 5) return 'Доля позитива почти не зависит от этого признака.';
  return `Довольнее всех - «${high.label}» (${pct(high.positive, high.reviews)}%), ` +
         `меньше всех - «${low.label}» (${pct(low.positive, low.reviews)}%).`;
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
    row.title = `${r.label}: ${num(r.reviews)} ${plural(r.reviews, 'отзыв', 'отзыва', 'отзывов')}, положительных ${p}%`;
    const bar = el('div', 'split');
    const good = el('div', null);
    good.style.width = `${p}%`;
    good.style.background = UP;
    const bad = el('div', null);
    bad.style.width = `${100 - p}%`;
    bad.style.background = DOWN;
    bar.append(good, bad);
    row.append(el('span', 'segment-label', r.label), bar, el('span', 'segment-num', `${p}%`),
               el('span', 'segment-share', `${pct(r.reviews, total)}% отзывов`));
    card.append(row);
  });
  return card;
}

export function renderAudience(segments) {
  // разрез с одним сегментом ничего не сравнивает: у игры без раннего доступа все отзывы - «после релиза»
  const cards = Object.keys(SEGMENTS)
    .filter(d => (segments[d] || []).length > 1)
    .map(d => segmentCard(d, segments[d]));
  document.getElementById('audience-section').hidden = !cards.length;
  document.getElementById('audience').replaceChildren(...cards);
}
