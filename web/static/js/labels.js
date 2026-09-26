// Подписи и цвета: всё, что переводит коды из базы в то, что видит читатель.

// типы событий игры. Цвета - категориальная палитра, проверенная на тёмном фоне (контраст, различимость при дальтонизме);
// синий и красный в неё не входят - они заняты ростом и спадом. Маркетинг, блоги и служебное - фон, одним серым
const BACKGROUND = '#8b929b';
export const EVENT_TYPES = {
  patch:        { color: '#d95926', label: 'патчи' },
  season_start: { color: '#199e70', label: 'сезоны' },
  expansion:    { color: '#c98500', label: 'дополнения' },
  press:        { color: '#d55181', label: 'пресса' },
  announce:     { color: '#9085e9', label: 'анонсы' },
  beta:         { color: '#008300', label: 'бета' },
  marketing:    { color: BACKGROUND, label: 'маркетинг' },
  blog:         { color: BACKGROUND, label: 'блоги' },
  service:      { color: BACKGROUND, label: 'служебное' },
  unknown:      { color: BACKGROUND, label: 'прочее' }
};

export const PLATFORM_TYPES = {
  sale: 'распродажа Steam',
  awards: 'Steam Awards',
  fest: 'фестиваль Steam'
};

export function eventType(type) {
  return EVENT_TYPES[type] || { color: BACKGROUND, label: type };
}

// рост и спад доли позитива, похвала и критика в темах - одна полярность, одна пара цветов на всей странице
export const UP = '#3987e5';
export const DOWN = '#e66767';

export const CATEGORIES = {
  monetization_and_value: 'Цена и монетизация',
  technical_performance: 'Техническое состояние',
  challenge_and_difficulty: 'Сложность',
  progression_and_engagement: 'Прогрессия',
  presentation: 'Графика и звук',
  narrative_and_world: 'Сюжет и мир',
  core_systems: 'Игровые системы',
  social_and_online: 'Режимы и сообщество',
  development_and_support: 'Разработка и поддержка',
  usability: 'Удобство',
  content_design: 'Контент'
};

export const ASPECTS = {
  pricing_fairness: 'цена',
  monetization_practices: 'монетизация',
  content_access_model: 'доступ к контенту',
  business_conduct: 'поведение издателя',
  frame_performance: 'производительность',
  stability: 'стабильность',
  connectivity: 'соединение и серверы',
  difficulty_balance: 'баланс сложности',
  punishment_design: 'наказание за ошибки',
  learning_curve: 'порог входа',
  progression_pacing: 'темп прогрессии',
  grind_and_repetition: 'гринд',
  reward_satisfaction: 'награды',
  visual_quality: 'графика',
  audio_quality: 'звук и музыка',
  atmosphere_and_immersion: 'атмосфера',
  narrative_quality: 'сюжет',
  world_design: 'мир',
  quest_design: 'квесты',
  combat_feel: 'бой',
  power_balance: 'баланс силы',
  build_depth: 'билды',
  non_combat_systems: 'небоевые системы',
  solo_experience: 'одиночная игра',
  multiplayer_experience: 'мультиплеер',
  community_quality: 'сообщество',
  matchmaking_quality: 'подбор игроков',
  anti_cheat: 'читеры',
  update_quality: 'качество обновлений',
  development_pace: 'темп разработки',
  developer_communication: 'общение разработчиков',
  customer_support: 'поддержка',
  mod_support: 'моды',
  game_lifecycle: 'будущее игры',
  interface_design: 'интерфейс',
  control_scheme: 'управление',
  accessibility: 'доступность',
  localization: 'локализация',
  content_volume: 'объём контента',
  content_variety: 'разнообразие',
  endgame_depth: 'эндгейм',
  replayability: 'реиграбельность',
  originality: 'оригинальность'
};

export const LANGUAGES = {
  english: 'английский', russian: 'русский', schinese: 'китайский упр.', tchinese: 'китайский трад.',
  german: 'немецкий', french: 'французский', spanish: 'испанский', latam: 'испанский (Лат. Ам.)',
  brazilian: 'португальский (Бр.)', portuguese: 'португальский', polish: 'польский', italian: 'итальянский',
  japanese: 'японский', koreana: 'корейский', turkish: 'турецкий', ukrainian: 'украинский', czech: 'чешский',
  thai: 'тайский', vietnamese: 'вьетнамский', dutch: 'нидерландский', hungarian: 'венгерский',
  swedish: 'шведский', finnish: 'финский', danish: 'датский', norwegian: 'норвежский', romanian: 'румынский',
  greek: 'греческий', bulgarian: 'болгарский', indonesian: 'индонезийский', arabic: 'арабский'
};

export const SEGMENTS = {
  playtime: { title: 'Сколько наиграно к отзыву', labels: { h0_2: 'до 2 ч', h2_10: '2–10 ч', h10_50: '10–50 ч', h50_200: '50–200 ч', h200: '200+ ч' } },
  language: { title: 'Язык отзыва', labels: LANGUAGES },
  purchase: { title: 'Как получена игра', labels: { steam: 'куплена в Steam', key: 'ключ из другого магазина', free: 'получена бесплатно' } },
  early_access: { title: 'Когда написан', labels: { early_access: 'в раннем доступе', release: 'после релиза' } },
  dev_response: { title: 'Ответ разработчика', labels: { answered: 'разработчик ответил', silent: 'без ответа' } }
};

// словесная оценка, как её пишет сам Steam: по доле положительных и числу отзывов
export function steamRating(pct, n) {
  if (n < 10) return 'мало отзывов';
  if (pct >= 95 && n >= 500) return 'крайне положительные';
  if (pct >= 80) return n >= 50 ? 'очень положительные' : 'положительные';
  if (pct >= 70) return 'в основном положительные';
  if (pct >= 40) return 'смешанные';
  if (pct >= 20) return 'в основном отрицательные';
  if (n >= 500) return 'крайне отрицательные';
  return n >= 50 ? 'очень отрицательные' : 'отрицательные';
}
