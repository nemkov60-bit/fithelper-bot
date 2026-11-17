import { FONT_SETS, type FontSet } from './fonts';

// Темы оформления. `colors` — изменяемый объект: при смене темы в него копируются цвета выбранной
// темы, а дерево экранов перерисовывается заново (см. ThemeProvider), поэтому экраны просто читают colors.*
export type ThemeName = 'classic' | 'men' | 'women' | 'premium' | 'steel' | 'light';

type Palette = {
  bg: string; surface: string; surface2: string; border: string; borderStrong: string;
  text: string; soft: string; muted: string; accent: string; onAccent: string; orange: string; danger: string;
  light: boolean;
};

export const THEMES: Record<ThemeName, Palette & { title: string; hint: string }> = {
  // Согласованный прототип: графит и лайм.
  classic: {
    title: 'Неоновый лайм', hint: 'Тёмный графит и салатовый',
    bg: '#0E0F0F', surface: '#1A1C1B', surface2: '#232625', border: '#2C302E', borderStrong: '#3A3F3C',
    text: '#F2F4F0', soft: '#C9CEC7', muted: '#A3A9A2', accent: '#C8F04A', onAccent: '#0E0F0F',
    orange: '#FF8A3D', danger: '#FF6B6B', light: false,
  },
  // «Бирюзовая ночь»: тёмная, мощная, бирюзовые акценты.
  men: {
    title: 'Бирюзовая ночь', hint: 'Тёмно-синий и бирюза',
    bg: '#091015', surface: '#111C23', surface2: '#18262F', border: '#21333D', borderStrong: '#2D4450',
    text: '#EEF6F8', soft: '#BFD0D6', muted: '#8EA3AB', accent: '#1FD3E6', onAccent: '#03161B',
    orange: '#FF8A3D', danger: '#FF6B6B', light: false,
  },
  // «Пудровая роза»: светлая розовая тема.
  women: {
    title: 'Пудровая роза', hint: 'Светлый, нежно-розовый',
    bg: '#FBEFF1', surface: '#FFFFFF', surface2: '#F8E4E9', border: '#F1D9DF', borderStrong: '#E6C3CC',
    text: '#2B1F25', soft: '#5E4A53', muted: '#8E7A83', accent: '#D45F7E', onAccent: '#FFFFFF',
    orange: '#E8804E', danger: '#D9435B', light: true,
  },
  // Тёмная тема с фиолетовым акцентом.
  premium: {
    title: 'Аметист', hint: 'Глубокий тёмный и фиолетовый',
    bg: '#120E17', surface: '#1D1724', surface2: '#272031', border: '#32293E', borderStrong: '#43384F',
    text: '#F5F0FA', soft: '#CFC4DB', muted: '#A094AE', accent: '#C77DFF', onAccent: '#170F1F',
    orange: '#FF9A5C', danger: '#FF6B8B', light: false,
  },
  // Стальная: строгая, графитово-серая, холодный голубой акцент.
  steel: {
    title: 'Холодная сталь', hint: 'Графитово-серый и серебристо-голубой',
    bg: '#16191C', surface: '#1F2327', surface2: '#282D32', border: '#343A40', borderStrong: '#454C53',
    text: '#EEF1F4', soft: '#C5CCD3', muted: '#97A1AA', accent: '#9FB8CC', onAccent: '#101418',
    orange: '#F2994A', danger: '#FF6B6B', light: false,
  },
  // Светлая: чистая и минималистичная.
  light: {
    title: 'Белый лёд', hint: 'Светлый, белый и морская волна',
    bg: '#F3F5F7', surface: '#FFFFFF', surface2: '#E9EDF1', border: '#DEE3E8', borderStrong: '#C9D0D7',
    text: '#14191E', soft: '#47515B', muted: '#7A848E', accent: '#1A9DB0', onAccent: '#FFFFFF',
    orange: '#E67A35', danger: '#D9434B', light: true,
  },
};

export const THEME_NAMES = Object.keys(THEMES) as ThemeName[];

export function isThemeName(v: unknown): v is ThemeName {
  return typeof v === 'string' && v in THEMES;
}

const { title: _t, hint: _h, ...initial } = THEMES.classic;
export const colors: Palette = { ...initial };

export function applyTheme(name: ThemeName) {
  const { title, hint, ...palette } = THEMES[name];
  Object.assign(colors, palette);
  Object.assign(fonts, FONT_SETS[name]);
}

// Шрифты текущей темы (изменяемый объект, как colors).
export const fonts: FontSet = { ...FONT_SETS.classic };

export const radius = { sm: 14, md: 20, lg: 24, xl: 28, pill: 999 };
