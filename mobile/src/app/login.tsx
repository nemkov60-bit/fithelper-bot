import * as AppleAuthentication from 'expo-apple-authentication';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Linking, Platform, Pressable, View } from 'react-native';

import { PhotoBanner } from '../components/PhotoBanner';
import { Button, Card, Screen, T } from '../components/ui';
import { api, type Me } from '../lib/api';
import { useAuth } from '../lib/auth';
import { openPrivacy } from '../lib/links';
import { colors } from '../lib/theme';

// Вход через Telegram: приложение получает код, пользователь подтверждает его в боте,
// приложение опрашивает сервер и получает токен.
export default function Login() {
  const { signIn, meta } = useAuth();
  const pair = meta?.photos?.home_u;
  const [code, setCode] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearInterval(timer.current);
  }, []);

  const poll = (value: string) => {
    if (timer.current) clearInterval(timer.current);
    const started = Date.now();
    timer.current = setInterval(async () => {
      if (Date.now() - started > 10 * 60 * 1000) {
        if (timer.current) clearInterval(timer.current);
        setCode(null);
        setError('Время ожидания вышло. Нажми «Войти через Telegram» ещё раз.');
        return;
      }
      try {
        const r = await api<{ status: string; token?: string; me?: Me }>('/api/auth/poll', { body: { code: value } });
        if (r.status === 'ok' && r.token && r.me) {
          if (timer.current) clearInterval(timer.current);
          await signIn(r.token, r.me);
          router.replace(r.me.profile_complete ? '/home' : '/onboarding');
        }
      } catch {
        // сеть мигнула — попробуем на следующем тике
      }
    }, 2000);
  };

  // «Войти с Apple» — только в приложении для iPhone (требование App Store при входе через сторонний сервис).
  const [appleAvailable, setAppleAvailable] = useState(false);
  useEffect(() => {
    if (Platform.OS === 'ios') AppleAuthentication.isAvailableAsync().then(setAppleAvailable).catch(() => {});
  }, []);
  const signInWithApple = async () => {
    setError('');
    try {
      const cred = await AppleAuthentication.signInAsync({
        requestedScopes: [AppleAuthentication.AppleAuthenticationScope.FULL_NAME, AppleAuthentication.AppleAuthenticationScope.EMAIL],
      });
      if (!cred.identityToken) throw new Error('no token');
      const r = await api<{ token: string; me: Me }>('/api/auth/apple', {
        body: { identity_token: cred.identityToken, given_name: cred.fullName?.givenName ?? null, family_name: cred.fullName?.familyName ?? null },
      });
      await signIn(r.token, r.me);
      router.replace(r.me.profile_complete ? '/home' : '/onboarding');
    } catch (e: any) {
      if (e?.code !== 'ERR_REQUEST_CANCELED') setError('Не удалось войти через Apple. Попробуй ещё раз.');
    }
  };

  const start = async () => {
    setError('');
    setBusy(true);
    try {
      const r = await api<{ code: string; url: string }>('/api/auth/start', { method: 'POST' });
      setCode(r.code);
      setUrl(r.url);
      poll(r.code);
      if (Platform.OS === 'web') {
        globalThis.open?.(r.url, '_blank');
      } else {
        await Linking.openURL(r.url);
      }
    } catch {
      setError('Не удалось связаться с сервером. Проверь интернет и попробуй ещё раз.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen bottomInset={40}>
      {pair ? (
        <PhotoBanner url={pair} minHeight={220} label="Фитнес-модели">
          <View style={{ alignSelf: 'flex-start', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.accent }}>
            <T v="label" style={{ color: colors.onAccent }}>FITHELPER</T>
          </View>
        </PhotoBanner>
      ) : <View style={{ height: 40 }} />}
      <View style={{ gap: 10 }}>
        {!pair ? (
          <View style={{ alignSelf: 'flex-start', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.accent }}>
            <T v="label" style={{ color: colors.onAccent }}>FITHELPER</T>
          </View>
        ) : null}
        <T v="big" style={{ fontSize: 36, lineHeight: 42 }}>Твой персональный тренер в телефоне</T>
        <T v="small" style={{ fontSize: 15, lineHeight: 22 }}>
          Готовая программа под цель, пол, возраст и опыт. Подходы, веса, отдых и прогресс — в одном месте.
        </T>
      </View>

      <Card style={{ gap: 12, marginTop: 12 }}>
        <T v="h3">Вход через Telegram</T>
        <T v="small">
          Нажми кнопку — откроется наш бот. Нажми в нём «Запустить», и ты войдёшь в приложение.
          Если ты уже занимаешься с ботом, программа и история подтянутся автоматически.
        </T>
        <Button title="Войти через Telegram" icon="arrow" onPress={start} loading={busy} />
        {code ? (
          <View style={{ gap: 10 }}>
            <T v="small" style={{ color: colors.accent }}>Ждём подтверждения в Telegram…</T>
            {url ? <Button title="Открыть бота ещё раз" variant="ghost" small onPress={() => (Platform.OS === 'web' ? globalThis.open?.(url, '_blank') : Linking.openURL(url))} /> : null}
          </View>
        ) : null}
        {appleAvailable ? (
          <AppleAuthentication.AppleAuthenticationButton
            buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
            buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.WHITE}
            cornerRadius={29} style={{ height: 58, width: '100%' }} onPress={signInWithApple} />
        ) : null}
        {error ? <T v="small" style={{ color: colors.danger }}>{error}</T> : null}
      </Card>
      <Pressable accessibilityRole="link" onPress={() => openPrivacy()}>
        <T v="small" style={{ textAlign: 'center', textDecorationLine: 'underline' }}>Политика конфиденциальности</T>
      </Pressable>
    </Screen>
  );
}
