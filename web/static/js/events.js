import { truncate, plural } from './util.js';

export const NO_EVENT_LABEL = 'событий рядом нет';

// один цвет на четыре типа, которые правило значимости и так держит фоном: четыре почти неразличимых серых различать было нечем. В легенде они остаются отдельными строками - клик по типу это фильтр
export const BACKGROUND_COLOR = '#a0adbb';

export const TYPES = {
  patch:        { color: '#f651f6', label: 'патчи' },
  season_start: { color: '#b07de8', label: 'сезоны' },
  expansion:    { color: '#ffb03a', label: 'дополнения' },
  beta:         { color: '#4aa3e0', label: 'бета' },
  marketing:    { color: BACKGROUND_COLOR, label: 'маркетинг' },
  press:        { color: '#2dbd9e', label: 'пресса' },
  blog:         { color: BACKGROUND_COLOR, label: 'блоги' },
  service:      { color: BACKGROUND_COLOR, label: 'служебное' },
  announce:     { color: '#f2d857', label: 'анонсы' },
  unknown:      { color: BACKGROUND_COLOR, label: 'прочее' }
};

// события платформы не привязаны к игре: bandColor - приглушённая полоса-фон, markerColor - тот же оттенок для маркера, насыщеннее
export const PLATFORM_TYPES = {
  sale:   { bandColor: '#9c916f', markerColor: '#d4b106', label: 'распродажа Steam' },
  awards: { bandColor: '#9f7a8f', markerColor: '#e879b8', label: 'Steam Awards' },
  fest:   { bandColor: '#6f8f96', markerColor: '#4fc3d9', label: 'Steam Fest' }
};

// в тултипе показывается короткое имя вроде "Steam Summer Sale" вместо всего пресс-заголовка
export function platformEventLabel(e) {
  if (e.type === 'awards') return 'Steam Awards';

  if (e.type === 'sale') {
    const m = e.title.match(
      /\b(summer|winter|spring|autumn|fall|holiday|black friday|halloween|lunar new year|chinese new year|christmas)\s+(?:steam\s+)?sale\b/i);
    const season = m ? m[1].replace(/\b\w/g, c => c.toUpperCase()) : null;
    return season ? `Steam ${season} Sale` : 'Steam Sale';
  }

  if (e.type === 'fest') {
    const m = e.title.match(/\b(\w+)\s+fest\b/i);
    const name = m ? m[1].replace(/\b\w/g, c => c.toUpperCase()) : null;
    return name ? `${name} Fest` : 'Steam Fest';
  }

  return e.title;
}

// на широком диапазоне мелкие события прячем, иначе сливаются в сплошную полосу; на узком (< 60 дней) показываем всё
function densityThreshold(days) {
  if (days > 365) return 5;
  if (days >= 180) return 2;
  if (days >= 60) return 1;
  return 0;
}

export function densityFilter(days) {
  const limit = densityThreshold(days);
  if (!limit) return () => true;
  return e => e.always_show || (e.weight ?? 0) >= limit;
}

// фильтров два - порог из формы на сервере и порог плотности здесь. Оба меряют вес, поэтому видно то, что прошло больший из них
export function eventFilterLabel(days, minWeight) {
  const limit = Math.max(minWeight, densityThreshold(days));
  if (!limit) return 'показаны все события';
  return `показаны сезоны, дополнения, события с откликом в данных и всё с весом ≥ ${limit}`;
}

export function mainEventLabel(c) {
  if (c.events.length) {
    return `${TYPES[c.events[0].type]?.label || c.events[0].type}: ${truncate(c.events[0].title, 70)}`;
  }
  if (c.platform_event) {
    return `платформа: ${platformEventLabel(c.platform_event)}`;
  }
  if (c.events_minor.length) {
    return `${c.events_minor.length} ` +
      `${plural(c.events_minor.length, 'фоновое событие', 'фоновых события', 'фоновых событий')}`;
  }
  return NO_EVENT_LABEL;
}
