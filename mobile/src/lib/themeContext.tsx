import { createContext, Fragment, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { api } from './api';
import { useAuth } from './auth';
import { loadThemeFonts } from './fonts';
import { getItem, setItem } from './storage';
import { applyTheme, isThemeName, type ThemeName } from './theme';

const KEY = 'fithelper.theme';
type ThemeState = { theme: ThemeName; setTheme: (t: ThemeName) => Promise<void> };
const ThemeContext = createContext<ThemeState | null>(null);

// Тема: выбор хранится на устройстве и в аккаунте (чтобы совпадал в вебе и на телефоне).
// По умолчанию — «Неоновый лайм».
export function ThemeProvider({ children }: { children: ReactNode }) {
  const { me, refresh } = useAuth();
  const [theme, setThemeState] = useState<ThemeName | null>(null);
  const chosen = useRef(false);

  const set = useCallback(async (t: ThemeName) => {
    try {
      await loadThemeFonts(t);
    } catch {
      // шрифт не загрузился — тема покажется со шрифтами по умолчанию
    }
    applyTheme(t);
    setThemeState(t);
  }, []);

  useEffect(() => {
    getItem(KEY).then((saved) => {
      chosen.current = isThemeName(saved);
      set(isThemeName(saved) ? saved : 'classic');
    });
  }, [set]);

  // Синхронизация с аккаунтом — только когда пришли новые данные пользователя (вход, обновление профиля),
  // а не при каждой смене темы: иначе устаревший me откатывал бы только что выбранную тему.
  const themeRef = useRef<ThemeName | null>(null);
  themeRef.current = theme;
  useEffect(() => {
    if (!me || themeRef.current === null) return;
    if (isThemeName(me.theme)) {
      if (me.theme !== themeRef.current) set(me.theme);
      setItem(KEY, me.theme);
      chosen.current = true;
    }
  }, [me, theme === null, set]);

  const setTheme = useCallback(async (t: ThemeName) => {
    chosen.current = true;
    await set(t);
    await setItem(KEY, t);
    try {
      await api('/api/me/settings', { method: 'PATCH', body: { theme: t } });
      await refresh();
    } catch {
      // анкета не заполнена или нет сети — тема всё равно сохранена на устройстве
    }
  }, [set, refresh]);

  const value = useMemo(() => ({ theme: theme ?? 'classic', setTheme }), [theme, setTheme]);
  if (theme === null) return null;
  // key: при смене темы экраны монтируются заново и читают новые colors.*
  return <ThemeContext.Provider value={value}><Fragment key={theme}>{children}</Fragment></ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme вне ThemeProvider');
  return ctx;
}
