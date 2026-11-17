import * as Font from 'expo-font';

import type { ThemeName } from './theme';

// Шрифтовые пары тем. Основной текст — читаемый гротеск, заголовки — с характером темы.
// Шрифты загружаются только для выбранной темы, Manrope грузится всегда (запасной).
export type FontSet = {
  regular: string; medium: string; semibold: string; bold: string; extrabold: string;
  heading: string; // крупные заголовки (big, h1)
  title: string; // заголовки блоков (h2, h3)
  headingSpacing: number; // трекинг крупных заголовков
};

const MANROPE = {
  regular: 'Manrope_400Regular', medium: 'Manrope_500Medium', semibold: 'Manrope_600SemiBold',
  bold: 'Manrope_700Bold', extrabold: 'Manrope_800ExtraBold',
};
const INTER = {
  regular: 'Inter_400Regular', medium: 'Inter_500Medium', semibold: 'Inter_600SemiBold',
  bold: 'Inter_700Bold', extrabold: 'Inter_800ExtraBold',
};
const NUNITO = {
  regular: 'Nunito_400Regular', medium: 'Nunito_600SemiBold', semibold: 'Nunito_600SemiBold',
  bold: 'Nunito_700Bold', extrabold: 'Nunito_800ExtraBold',
};

export const FONT_SETS: Record<ThemeName, FontSet> = {
  // Неоновый лайм — современный геометричный Manrope.
  classic: { ...MANROPE, heading: MANROPE.extrabold, title: MANROPE.extrabold, headingSpacing: -0.6 },
  // Бирюзовая ночь — динамичный спортивный курсив Exo 2 в заголовках.
  men: { ...MANROPE, heading: 'Exo2_800ExtraBold_Italic', title: 'Exo2_700Bold', headingSpacing: -0.3 },
  // Пудровая роза — мягкий скруглённый Nunito.
  women: { ...NUNITO, heading: NUNITO.extrabold, title: NUNITO.extrabold, headingSpacing: -0.4 },
  // Аметист — элегантный Montserrat в заголовках.
  premium: { ...MANROPE, heading: 'Montserrat_800ExtraBold', title: 'Montserrat_700Bold', headingSpacing: -0.8 },
  // Холодная сталь — строгий узкий Oswald и технологичный Inter.
  steel: { ...INTER, heading: 'Oswald_600SemiBold', title: 'Oswald_500Medium', headingSpacing: 0.2 },
  // Белый лёд — чистый минималистичный Inter.
  light: { ...INTER, heading: INTER.extrabold, title: INTER.bold, headingSpacing: -0.7 },
};

/* eslint-disable @typescript-eslint/no-require-imports */
const FILES: Record<string, number> = {
  Inter_400Regular: require('@expo-google-fonts/inter/400Regular/Inter_400Regular.ttf'),
  Inter_500Medium: require('@expo-google-fonts/inter/500Medium/Inter_500Medium.ttf'),
  Inter_600SemiBold: require('@expo-google-fonts/inter/600SemiBold/Inter_600SemiBold.ttf'),
  Inter_700Bold: require('@expo-google-fonts/inter/700Bold/Inter_700Bold.ttf'),
  Inter_800ExtraBold: require('@expo-google-fonts/inter/800ExtraBold/Inter_800ExtraBold.ttf'),
  Nunito_400Regular: require('@expo-google-fonts/nunito/400Regular/Nunito_400Regular.ttf'),
  Nunito_600SemiBold: require('@expo-google-fonts/nunito/600SemiBold/Nunito_600SemiBold.ttf'),
  Nunito_700Bold: require('@expo-google-fonts/nunito/700Bold/Nunito_700Bold.ttf'),
  Nunito_800ExtraBold: require('@expo-google-fonts/nunito/800ExtraBold/Nunito_800ExtraBold.ttf'),
  Exo2_700Bold: require('@expo-google-fonts/exo-2/700Bold/Exo2_700Bold.ttf'),
  Exo2_800ExtraBold_Italic: require('@expo-google-fonts/exo-2/800ExtraBold_Italic/Exo2_800ExtraBold_Italic.ttf'),
  Montserrat_700Bold: require('@expo-google-fonts/montserrat/700Bold/Montserrat_700Bold.ttf'),
  Montserrat_800ExtraBold: require('@expo-google-fonts/montserrat/800ExtraBold/Montserrat_800ExtraBold.ttf'),
  Oswald_500Medium: require('@expo-google-fonts/oswald/500Medium/Oswald_500Medium.ttf'),
  Oswald_600SemiBold: require('@expo-google-fonts/oswald/600SemiBold/Oswald_600SemiBold.ttf'),
};
/* eslint-enable @typescript-eslint/no-require-imports */

export async function loadThemeFonts(name: ThemeName) {
  const set = FONT_SETS[name];
  const needed = [...new Set(Object.values(set).filter((v): v is string => typeof v === 'string'))]
    .filter((f) => FILES[f] && !Font.isLoaded(f));
  if (needed.length) await Font.loadAsync(Object.fromEntries(needed.map((f) => [f, FILES[f]])));
}
