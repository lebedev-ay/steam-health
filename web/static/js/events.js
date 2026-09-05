import { truncate } from './util.js';

export const TYPES = {
  patch:        { color: '#ff6b5b', label: 'патчи' },
  season_start: { color: '#b07de8', label: 'сезоны' },
  expansion:    { color: '#ffb03a', label: 'дополнения' },
  beta:         { color: '#4aa3e0', label: 'бета' },
  marketing:    { color: '#8a95a3', label: 'маркетинг' },
  press:        { color: '#2dbd9e', label: 'пресса' },
  blog:         { color: '#7d8a99', label: 'блоги' },
  service:      { color: '#5a6472', label: 'служебное' },
  announce:     { color: '#c9a227', label: 'анонсы' },
  unknown:      { color: '#6b7684', label: 'прочее' }
};

// события платформы не привязаны к игре: bandColor - приглушённая полоса-фон, markerColor - тот же оттенок для маркера, насыщеннее
export const PLATFORM_TYPES = {
  sale:   { bandColor: '#9c916f', markerColor: '#d4b106', label: 'распродажа Steam' },
  awards: { bandColor: '#8b8298', markerColor: '#9b6fd6', label: 'Steam Awards' },
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
  return e => (e.weight ?? 0) >= limit;
}

// фильтров два - порог из формы на сервере и порог плотности здесь. Оба меряют вес, поэтому видно то, что прошло больший из них
export function eventFilterLabel(days, minWeight) {
  const limit = Math.max(minWeight, densityThreshold(days));
  return limit ? `показаны события с весом ≥ ${limit}` : 'показаны все события';
}

export function mainEventLabel(c) {
  if (c.events.length) {
    return `${TYPES[c.events[0].type]?.label || c.events[0].type}: ${truncate(c.events[0].title, 70)}`;
  }
  if (c.platform_event) {
    return `платформа: ${platformEventLabel(c.platform_event)}`;
  }
  if (c.events_minor.length) {
    return `${c.events_minor.length} фоновых событий`;
  }
  return '—';
}
