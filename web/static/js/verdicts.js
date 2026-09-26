import { shiftDay } from './util.js';

function ruDate(day) {
  return new Date(day + 'T00:00:00').toLocaleDateString('ru-RU');
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function part(label, text) {
  const p = el('p', 'verdict-part');
  p.append(el('span', 'verdict-label', label + ' '), text);
  return p;
}

function card(v) {
  const article = el('article', 'verdict');
  article.id = `verdict-${v.day}`;

  const head = el('div', 'verdict-head');
  head.append(el('span', 'verdict-date', ruDate(v.day)));
  if (v.preliminary) {
    const badge = el('span', 'verdict-badge', 'предварительный');
    badge.title = 'окно «после» ещё не закрыто: поздние отзывы могут изменить вывод';
    head.append(badge);
  }
  article.append(head);

  // вывод, не прошедший проверку кодом, без текста: остаются только даты и доли, которые считал код, а не модель
  if (!v.checked) {
    article.append(el('p', 'verdict-numbers',
      `Доля отзывов с оценкой «не рекомендую»: ${v.negative_before}% за ${ruDate(v.before_from)}-${ruDate(shiftDay(v.day, -1))}, ` +
      `${v.negative_after}% за ${ruDate(v.day)}-${ruDate(shiftDay(v.after_to, -1))}`));
    return article;
  }

  article.append(part('Что случилось.', v.what_happened));
  if (v.what_players_say) article.append(part('О чём пишут игроки.', v.what_players_say));

  if (v.excerpts && v.excerpts.length) {
    const details = el('details', 'verdict-excerpts');
    details.append(el('summary', null, 'Отрывки из отзывов'));
    v.excerpts.forEach(t => details.append(el('blockquote', null, t)));
    article.append(details);
  }
  return article;
}

export function renderVerdicts(list) {
  const section = document.getElementById('verdicts');
  // игра без разметки и без выводов - блока нет совсем, пустой заголовок только занимал бы место
  if (!list.length) {
    section.hidden = true;
    section.replaceChildren();
    return;
  }
  section.replaceChildren(
    el('h2', 'verdicts-title', 'Выводы по переломам'),
    el('p', 'verdicts-note', 'Текст собран моделью по разметке отзывов за 7 дней до и 7 дней после перелома и проверен кодом. ' +
                             'Совпадение по времени с событием не означает, что событие стало причиной.'),
    ...list.map(card));
  section.hidden = false;
}

export function clearVerdicts() {
  renderVerdicts([]);
}

// переход с графика: карточка прокручивается в поле зрения и коротко подсвечивается
export function focusVerdict(day) {
  const node = document.getElementById(`verdict-${day}`);
  if (!node) return;
  node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  document.querySelectorAll('.verdict-focus').forEach(n => n.classList.remove('verdict-focus'));
  node.classList.add('verdict-focus');
}
