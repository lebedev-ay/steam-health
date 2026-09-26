import { renderAudience, MIN_SEGMENT } from './audience.js';
import { fetchReviews } from './api.js';
import { renderChart } from './chart.js';
import { ASPECTS, DOWN, UP, steamRating } from './labels.js';
import { renderTopics } from './topics.js';
import { focusTurn, mainEvent, renderTurns } from './turns.js';
import { renderUpdates } from './updates.js';
import { $, countUp, delta, el, gauge, hours, longDate, num, pct, plural, reviewsWord, ruDate, shiftDay,
         sparkline } from './util.js';

// страница игры: шапка, сводка месяца, показатели и вкладка «Обзор»; остальные вкладки - в своих модулях
const RECENT_DAYS = 30;
let appId = null;

export function renderGame(data, handlers) {
  appId = data.game.app_id;
  renderHero(data);
  renderDigest(data.digest);
  renderKpis(data);

  $('chart-card').hidden = !data.daily.length;
  if (data.daily.length) {
    renderChart(data, { onPointClick: day => focusTurn(day), animate: handlers.firstVisit });
    $('chart-note').textContent = `Сглаживание - окно ${data.window} дн. Серая линия - норма игры, медиана за 90 дней. ` +
      'Колесо мыши - приблизить, перетаскивание - сдвинуть, двойной щелчок - весь период.';
  }
  renderTurns(data, handlers);
  renderHighlights(data, handlers.games || []);
  renderPicks(data);
  renderTopics(data, handlers);
  renderAudience(data.segments);
  renderUpdates(data.updates, handlers);
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
  $('game-chips').replaceChildren(...chips);
  $('game-steam').href = `https://store.steampowered.com/app/${g.app_id}/`;

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

// --- коротко: несколько фактов, которые иначе пришлось бы выискивать по вкладкам ---

function segmentShare(list, code) {
  const r = (list || []).find(s => s.segment === code);
  return r && r.reviews >= MIN_SEGMENT ? { pct: pct(r.positive, r.reviews), reviews: r.reviews } : null;
}

function renderHighlights(data, games) {
  const items = [];
  const add = (mark, title, text) => items.push({ mark, title, text });
  const daily = data.daily;
  const recent = share(daily.slice(-RECENT_DAYS));

  // место среди игр стенда по доле позитива за 30 дней
  const ranked = games.filter(g => g.reviews_30).map(g => ({ id: g.app_id, p: g.positive_30 / g.reviews_30 })).sort((a, b) => b.p - a.p);
  const place = ranked.findIndex(g => g.id === data.game.app_id);
  if (ranked.length > 2 && place >= 0) {
    add('#', `${place + 1}-е место из ${ranked.length} по позитиву за 30 дней`, 'среди игр на стенде');
  }
  const cps = data.change_points;
  if (cps.length) {
    const worst = cps.reduce((a, c) => (c.score < a.score ? c : a));
    if (worst.score < 0) add('▼', `Самый резкий спад - ${longDate(worst.day)}`, `${Math.abs(worst.score)} п.п.; ${mainEvent(worst).text}`);
  }
  const fresh = segmentShare(data.segments.playtime, 'h0_2');
  if (fresh && recent.pct != null) {
    add('◷', `До 2 часов игры - ${fresh.pct}% положительных`, 'это те, кто ещё может вернуть игру; в среднем по игре ' +
        `${pct(daily.reduce((a, d) => a + d.positive, 0), daily.reduce((a, d) => a + d.total, 0))}%`);
  }
  const answered = (data.segments.dev_response || []).find(s => s.segment === 'answered');
  const allDev = (data.segments.dev_response || []).reduce((a, s) => a + s.reviews, 0);
  if (answered && allDev) add('↩', `Разработчик ответил на ${pct(answered.reviews, allDev) || '<1'}% отзывов`, `${num(answered.reviews)} ${reviewsWord(answered.reviews)} с ответом`);
  const len = data.lengths || {};
  if (len.up && len.down) {
    const ratio = len.down / len.up;
    add('¶', ratio >= 1.2 ? `Недовольные пишут в ${ratio.toFixed(1).replace('.', ',')} раза длиннее` : 'Довольные и недовольные пишут примерно одинаково',
        `медиана ${num(len.down)} и ${num(len.up)} знаков за 90 дней`);
  }
  const a = data.aspects;
  if (a?.items.length) {
    const pain = [...a.items].sort((x, y) => y.negative - x.negative)[0];
    add('✕', `Чаще всего ругают: ${ASPECTS[pain.aspect_id] || pain.aspect_id}`, `в ${pct(pain.negative, a.labeled)}% размеченных отзывов`);
  }

  $('highlights').replaceChildren(...(items.length ? items.map((i, n) => {
    const node = el('div', 'highlight');
    node.style.animationDelay = `${n * 60}ms`;
    const text = el('div');
    text.append(el('b', null, i.title), el('span', null, i.text));
    node.append(el('div', 'highlight-mark', i.mark), text);
    return node;
  }) : [el('p', 'muted', 'Пока нечего сказать - мало данных.')]));
}

// самые полезные отзывы месяца: по голосам «полезно», по одному с каждой стороны
async function renderPicks(data) {
  const box = $('picks');
  const last = data.daily.at(-1)?.day;
  box.replaceChildren();
  if (!last) return;
  const period = { since: shiftDay(last, -29), until: shiftDay(last, 1), sort: 'helpful' };
  const game = data.game.app_id;
  const [good, bad] = await Promise.all(['up', 'down'].map(vote =>
    fetchReviews(game, { ...period, vote }).then(r => r.items[0]).catch(() => null)));
  if (appId !== game) return;     // пока ждали, открыли другую игру
  box.replaceChildren(...[[bad, 'не рекомендует', DOWN], [good, 'рекомендует', UP]].filter(([r]) => r).map(([r, label, color]) => {
    const node = el('article', 'pick');
    const head = el('div', 'review-head');
    const vote = el('span', 'vote', `${color === UP ? '▲' : '▼'} ${label}`);
    vote.style.color = color;
    head.append(vote, el('span', null, longDate(r.day)));
    if (r.minutes != null) head.append(el('span', null, `наиграно ${hours(r.minutes)}`));
    if (r.votes_up) head.append(el('span', null, `полезно ${num(r.votes_up)}`));
    node.append(head, el('p', 'review-text clamped', r.text));
    return node;
  }));
  if (!box.children.length) box.append(el('p', 'muted', 'За последние 30 дней отзывов с текстом нет.'));
}
