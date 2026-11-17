// Темы оформления. `colors` — изменяемый объект: при смене темы в него копируются цвета выбранной
// темы, а дерево экранов перерисовывается заново (см. ThemeProvider), поэтому экраны просто читают colors.*
// Пока одна тема — «Неоновый лайм». Механизм тем оставлен: новые варианты добавляются сюда.
export type ThemeName = 'classic';

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
}

export type FontSet = {
  regular: string; medium: string; semibold: string; bold: string; extrabold: string;
  heading: string; title: string; headingSpacing: number;
};

// Шрифт приложения — Manrope.
export const fonts: FontSet = {
  regular: 'Manrope_400Regular',
  medium: 'Manrope_500Medium',
  semibold: 'Manrope_600SemiBold',
  bold: 'Manrope_700Bold',
  extrabold: 'Manrope_800ExtraBold',
  heading: 'Manrope_800ExtraBold',
  title: 'Manrope_800ExtraBold',
  headingSpacing: -0.6,
};

export const radius = { sm: 14, md: 20, lg: 24, xl: 28, pill: 999 };
