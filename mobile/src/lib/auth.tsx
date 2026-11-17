import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { api, setToken, setUnauthorizedHandler, type Me, type Meta } from './api';
import { getItem, removeItem, setItem } from './storage';

const TOKEN_KEY = 'fithelper.token';

type AuthState = {
  ready: boolean;
  me: Me | null;
  meta: Meta | null;
  signIn: (token: string, me: Me) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);

  const signOut = useCallback(async () => {
    try {
      await api('/api/auth/logout', { method: 'POST' });
    } catch {
      // сессия уже недействительна
    }
    setToken(null);
    await removeItem(TOKEN_KEY);
    setMe(null);
  }, []);

  const refresh = useCallback(async () => {
    setMe(await api<Me>('/api/me'));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      removeItem(TOKEN_KEY);
      setMe(null);
    });
    (async () => {
      try {
        setMeta(await api<Meta>('/api/meta'));
      } catch {
        // сервер недоступен — экран входа покажет ошибку
      }
      const saved = await getItem(TOKEN_KEY);
      if (saved) {
        setToken(saved);
        try {
          setMe(await api<Me>('/api/me'));
        } catch {
          setMe(null);
        }
      }
      setReady(true);
    })();
  }, []);

  const signIn = useCallback(async (token: string, value: Me) => {
    setToken(token);
    await setItem(TOKEN_KEY, token);
    setMe(value);
  }, []);

  const value = useMemo(() => ({ ready, me, meta, signIn, signOut, refresh }), [ready, me, meta, signIn, signOut, refresh]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth вне AuthProvider');
  return ctx;
}
