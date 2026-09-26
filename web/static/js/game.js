import { renderChart } from './chart.js';
import { ASPECTS, CATEGORIES, DOWN, LANGUAGES, PLATFORM_TYPES, SEGMENTS, UP, eventType, steamRating } from './labels.js';
import { $, countUp, delta, el, gauge, longDate, monthBars, num, pct, plural, reviewsWord, ruDate, shiftDay,
         sparkline, truncate } from './util.js';
import { fetchAspect } from './api.js';

const RECENT_DAYS = 30;
const TOP_ASPECTS = 12;
const TOP_LANGUAGES = 8;
const LATEST_TURNS = 3;
// сегмент меньше этого числа отзывов в выводы «кто доволен меньше всех» не идёт: на десятке отзывов доля скачет сама по себе
const MIN_SEGMENT = 50;

let current = null;
let actions = {};

export function renderGame(data, handlers) {
  current = data;
  actions = handlers;
  renderHero(data);
  renderDigest(data.digest);
  renderKpis(data);

  $('chart-card').hidden = !data.daily.length;
  if (data.daily.length) {
    renderChart(data, { onPointClick: day => focusTurn(day) });
    $('chart-note').textContent = `Сглаживание - окно ${data.window} дн. Фиолетовая линия - норма игры, медиана за 90 дней. ` +
      'Колесо мыши - приблизить, перетаскивание - сдвинуть, двойной щелчок - весь период.';
  }
  renderTurns(data);
  renderHighlights(data);
  renderTopics(data);
  renderAudience(data.segments);
  renderUpdates(data.updates);
}

// --- шапка ---

function share(days) {
  const total = days.reduce((a, d) => a + d.total, 0);
  return { total, pct: pct(days.reduce((a, d) => a + d.positive, 0), total) };
}

function renderHero(data) {
  const g = data.game;
  $('game-title').textContent = g.game_name;
  $('game-meta').textContent = [
    g.developers,
    g.publishers && g.publishers !== g.developers && `издатель ${g.publishers}`,
    g.release_date && `релиз ${longDate(g.release_date)}`
  ].filter(Boolean).join(' · ');

  const chips = (g.genres || '').split(', ').filter(Boolean).map(x => el('span', 'chip', x));
  if (g.metacritic_score) chips.push(el('span', 'chip', `Metacritic ${g.metacritic_score}`));
  if (g.collection_status === 'partial') chips.push(el('span', 'chip warn', 'данные неполные'));
  const steam = el('a', 'chip', 'Steam ↗');
  steam.href = `https://store.steampowered.com/app/${g.app_id}/`;
  steam.target = '_blank';
  steam.rel = 'noopener';
  $('game-chips').replaceChildren(...chips, steam);

  const recent = share(data.daily.slice(-RECENT_DAYS));
  const box = $('gauge');
  box.replaceChildren();
  if (data.daily.length) {
    box.append(gauge(recent.pct, `за ${RECENT_DAYS} дней`),
               el('div', 'gauge-caption', recent.pct == null ? '' : steamRating(recent.pct, recent.total)));
  }
}

// сводка месяца от модели - первым делом, если есть: это самое короткое «что происходит»
function renderDigest(digests) {
  const box = $('digest');
  box.hidden = !digests.length;
  if (!digests.length) return;
  const d = digests[0];
  box.replaceChildren(
    el('p', 'eyebrow', `сводка за ${ruDate(d.period_from, { month: 'long', year: 'numeric' })}`),
    el('h2', null, d.headline),
    el('p', null, d.summary)
  );
}

function tile(label, value, format, note, extra) {
  const node = el('div', 'tile');
  const v = el('div', 'tile-value');
  countUp(v, value, format);
  node.append(el('div', 'tile-label', label), v);
  if (note) node.append(el('div', 'tile-note', note));
  if (extra) node.append(extra);
  return node;
}

function renderKpis(data) {
  const daily = data.daily;
  const box = $('kpis');
  box.hidden = !daily.length;
  if (!daily.length) return;

  const all = share(daily);
  const recent = share(daily.slice(-RECENT_DAYS));
  const before = share(daily.slice(-2 * RECENT_DAYS, -RECENT_DAYS));
  const peak = daily.reduce((a, d) => (d.total > a.total ? d : a), daily[0]);
  const cps = data.change_points;
  const drops = cps.filter(c => c.score < 0).length;

  const trend = el('div', 'tile-sub');
  if (recent.pct != null && before.pct != null) trend.append(delta(recent.pct - before.pct), ' к прошлым 30 дням');
  const weekly = [];
  for (let i = Math.max(daily.length - 182, 0); i < daily.length; i += 7) weekly.push(share(daily.slice(i, i + 7)).pct);
  const recentTile = tile(`последние ${RECENT_DAYS} дней`, recent.pct ?? NaN, v => Number.isFinite(v) ? `${Math.round(v)}%` : '—',
                          `${num(recent.total)} ${reviewsWord(recent.total)}`, trend);
  recentTile.append(sparkline(weekly, recent.pct != null && before.pct != null && recent.pct < before.pct ? DOWN : UP));

  box.replaceChildren(
    recentTile,
    tile('за всё время', all.pct, v => `${Math.round(v)}%`, `${steamRating(all.pct, all.total)} · ${num(all.total)} ${reviewsWord(all.total)}`,
         el('div', 'tile-sub', `с ${longDate(daily[0].day)}`)),
    tile('отзывов в день', data.median_volume, v => num(Math.round(v)), 'медиана',
         el('div', 'tile-sub', `пик ${num(peak.total)} - ${longDate(peak.day)}`)),
    tile('переломов', cps.length, v => String(Math.round(v)),
         `${drops} ${plural(drops, 'спад', 'спада', 'спадов')}, ${cps.length - drops} ${plural(cps.length - drops, 'рост', 'роста', 'ростов')}`,
         el('div', 'tile-sub', cps.some(c => c.verdict?.checked) ? `по ${cps.filter(c => c.verdict?.checked).length} есть разбор отзывов` : ''))
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

function renderTurns(data) {
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

// --- коротко: несколько фактов, которые иначе пришлось бы выискивать по вкладкам ---

function segmentShare(list, code) {
  const r = (list || []).find(s => s.segment === code);
  return r && r.reviews >= MIN_SEGMENT ? { pct: pct(r.positive, r.reviews), reviews: r.reviews } : null;
}

function renderHighlights(data) {
  const items = [];
  const add = (mark, color, title, text) => items.push({ mark, color, title, text });
  const cps = data.change_points;
  if (cps.length) {
    const worst = cps.reduce((a, c) => (c.score < a.score ? c : a));
    if (worst.score < 0) add('▼', DOWN, `Самый резкий спад - ${longDate(worst.day)}`, `${Math.abs(worst.score)} п.п.; ${mainEvent(worst).text}`);
  }
  const a = data.aspects;
  if (a?.items.length) {
    const pain = [...a.items].sort((x, y) => y.negative - x.negative)[0];
    const love = [...a.items].sort((x, y) => y.positive - x.positive)[0];
    add('✕', DOWN, `Чаще всего ругают: ${ASPECTS[pain.aspect_id] || pain.aspect_id}`, `в ${pct(pain.negative, a.labeled)}% размеченных отзывов`);
    add('♥', UP, `Чаще всего хвалят: ${ASPECTS[love.aspect_id] || love.aspect_id}`, `в ${pct(love.positive, a.labeled)}% размеченных отзывов`);
  }
  const fresh = segmentShare(data.segments.playtime, 'h0_2');
  const veteran = segmentShare(data.segments.playtime, 'h200');
  if (fresh && veteran) {
    add('◷', '#b86bff', `До 2 часов - ${fresh.pct}%, после 200 часов - ${veteran.pct}%`,
        'доля положительных у тех, кто ещё может вернуть игру, и у ветеранов');
  }
  const ru = segmentShare(data.segments.language, 'russian');
  if (ru && items.length < 4) add('Р', '#b86bff', `Русскоязычные отзывы: ${ru.pct}% положительных`, `${num(ru.reviews)} ${reviewsWord(ru.reviews)}`);

  $('highlights').replaceChildren(...(items.length ? items.map(i => {
    const node = el('div', 'highlight');
    const mark = el('div', 'highlight-mark', i.mark);
    mark.style.color = i.color;
    const text = el('div');
    text.append(el('b', null, i.title), el('span', null, i.text));
    node.append(mark, text);
    return node;
  }) : [el('p', 'muted', 'Пока нечего сказать - мало данных.')]));
}

// --- темы ---

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
      cell.style.background = `color-mix(in oklab, ${DOWN} ${Math.round(80 * value / max)}%, #1b1826)`;
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

function renderTopics(data) {
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
    const d = await fetchAspect(current.game.app_id, aspectId);
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

function renderAudience(segments) {
  // разрез с одним сегментом ничего не сравнивает: у игры без раннего доступа все отзывы - «после релиза»
  const cards = Object.keys(SEGMENTS).filter(d => (segments[d] || []).length > 1).map(d => segmentCard(d, segments[d]));
  $('audience').replaceChildren(...(cards.length ? cards : [el('p', 'muted', 'отзывов пока нет')]));
}

// --- обновления ---

const UPDATE_COLUMNS = [
  { key: 'day', title: 'дата', sort: (a, b) => b.day.localeCompare(a.day) },
  { key: 'title', title: 'новость' },
  { key: 'before', title: 'позитив до → после' },
  { key: 'change', title: 'изменение', sort: (a, b) => change(a) - change(b) },
  { key: 'volume', title: 'отзывов после', sort: (a, b) => ratio(b) - ratio(a) }
];
const change = u => u.positive_after != null && u.positive_before != null ? u.positive_after - u.positive_before : 0;
const ratio = u => u.reviews_before ? u.reviews_after / u.reviews_before : 0;
let updatesSort = 'day';

function renderUpdates(updates) {
  const box = $('updates');
  if (!updates.length) {
    box.replaceChildren(el('p', 'muted', 'новостей игры в собранном периоде нет'));
    return;
  }
  const table = el('table', 'table');
  const head = table.createTHead().insertRow();
  UPDATE_COLUMNS.forEach(col => {
    const th = el('th', null, col.title);
    if (col.sort) {
      if (col.key === updatesSort) th.dataset.sorted = '';
      th.onclick = () => { updatesSort = col.key; renderUpdates(updates); };
    }
    head.append(th);
  });
  const body = table.createTBody();
  [...updates].sort(UPDATE_COLUMNS.find(c => c.key === updatesSort).sort).forEach(u => {
    const row = body.insertRow();
    row.onclick = () => actions.openReviews({ since: u.day, until: shiftDay(u.day, 7) });
    const type = el('td');
    const dot = el('span', 'dot');
    dot.style.background = eventType(u.type).color;
    dot.style.display = 'inline-block';
    dot.style.marginRight = '8px';
    type.append(dot, `${eventType(u.type).label}: ${truncate(u.title, 80)}`);
    const d = change(u);
    const deltaCell = el('td');
    if (u.positive_after != null && u.positive_before != null) deltaCell.append(delta(d));
    const r = ratio(u);
    row.append(el('td', 'num', ruDate(u.day)), type,
               el('td', 'num', u.positive_before != null ? `${u.positive_before}% → ${u.positive_after ?? '—'}%` : '—'),
               deltaCell,
               el('td', 'num', `${num(u.reviews_after)}${r ? ` · ×${r.toFixed(1).replace('.', ',')}` : ''}`));
  });
  box.replaceChildren(table);
}
