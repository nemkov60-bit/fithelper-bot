import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Platform, Pressable, TextInput, View } from 'react-native';

import { Button, Card, Screen, Segmented, T } from '../../components/ui';
import { api } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { openPrivacy } from '../../lib/links';
import { IOS_STORE } from '../../lib/platform';
import { colors, fonts, THEME_NAMES, THEMES } from '../../lib/theme';
import { useTheme } from '../../lib/themeContext';

export default function Profile() {
  const { me, meta, refresh, signOut } = useAuth();
  const { theme, setTheme } = useTheme();
  const [target, setTarget] = useState(me?.profile.target_weight ? String(me.profile.target_weight) : '');
  const [groupType, setGroupType] = useState<string | null>(null);
  const [minutes, setMinutes] = useState(55);
  const [message, setMessage] = useState('');
  const [targetError, setTargetError] = useState('');
  const [groupNote, setGroupNote] = useState('');

  if (!me || !meta) return null;
  const p = me.profile;
  const label = (map: Record<string, string>, key: string | null) => (key && map[key]) || '—';

  const saveSettings = async (body: Record<string, unknown>, done = 'Сохранено') => {
    await api('/api/me/settings', { method: 'PATCH', body });
    await refresh();
    setMessage(done);
  };

  // Цель по весу: проверяем ввод и показываем результат прямо у поля, а не вверху экрана.
  const saveTarget = async () => {
    const raw = target.trim().replace(',', '.');
    const value = raw ? Number(raw) : 0;
    if (raw && (!Number.isFinite(value) || value < 30 || value > 300)) {
      setTargetError('Укажи вес числом от 30 до 300 кг, например 75 или 72,5');
      throw new Error('invalid');
    }
    setTargetError('');
    await api('/api/me/settings', { method: 'PATCH', body: { target_weight: value } });
    await refresh();
  };

  const logGroup = async () => {
    if (!groupType) return;
    await api('/api/groups/log', { body: { type: groupType, minutes } });
    setGroupType(null);
    setGroupNote('✓ Засчитано в прогресс тренировок');
  };

  return (
    <Screen>
      <T v="big">Профиль</T>
      {message ? <Card style={{ backgroundColor: colors.surface2 }}><T v="small" style={{ color: colors.accent }}>{message}</T></Card> : null}

      <Card style={{ gap: 8 }}>
        <T v="h3">{me.name || 'Спортсмен'}</T>
        <T v="small">{label(meta.genders, p.gender)} · {label(meta.ages, p.age)}</T>
        <T v="small">{label(meta.goals, p.goal)}</T>
        <T v="small">{label(meta.levels, p.level)} · {p.days} трен./нед.</T>
        <Button title="Заполнить анкету заново" variant="ghost" small onPress={() => router.push('/onboarding')} />
      </Card>

      {THEME_NAMES.length > 1 ? (
      <Card style={{ gap: 10 }}>
        <T v="h3">Оформление</T>
        <View style={{ gap: 8 }}>
          {THEME_NAMES.map((name) => {
            const t = THEMES[name];
            const active = theme === name;
            return (
              <Pressable key={name} accessibilityRole="radio" accessibilityState={{ checked: active }} accessibilityLabel={`Оформление ${t.title}`}
                onPress={() => setTheme(name)}
                style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 10, borderRadius: 18, borderWidth: 1.5,
                  borderColor: active ? colors.accent : colors.border, backgroundColor: active ? colors.surface2 : 'transparent' }}>
                <View style={{ width: 52, height: 40, borderRadius: 12, backgroundColor: t.bg, borderWidth: 1, borderColor: t.border, padding: 6, gap: 4, justifyContent: 'center' }}>
                  <View style={{ height: 8, borderRadius: 4, backgroundColor: t.surface2 }} />
                  <View style={{ height: 10, width: 26, borderRadius: 5, backgroundColor: t.accent }} />
                </View>
                <View style={{ flex: 1 }}>
                  <T style={{ fontFamily: fonts.bold }}>{t.title}</T>
                  <T v="small" style={{ fontSize: 12 }}>{t.hint}</T>
                </View>
                {active ? <T style={{ color: colors.accent, fontFamily: fonts.extrabold }}>✓</T> : null}
              </Pressable>
            );
          })}
        </View>
      </Card>
      ) : null}

      <Card style={{ gap: 10 }}>
        <T v="h3">Где тренируешься обычно</T>
        <Segmented label="Место по умолчанию" value={p.place ?? 'gym'}
          options={[{ key: 'gym', label: 'В зале' }, { key: 'home', label: 'Дома' }]}
          onChange={(place) => saveSettings({ place }, 'Место по умолчанию изменено')} />
      </Card>

      <Card style={{ gap: 10 }}>
        <T v="h3">Цель по весу тела</T>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <TextInput value={target} onChangeText={setTarget} keyboardType="decimal-pad" placeholder="Например, 75"
            placeholderTextColor={colors.muted} accessibilityLabel="Цель по весу тела, кг"
            style={{ flex: 1, minWidth: 0, height: 48, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg, color: colors.text, paddingHorizontal: 14, fontFamily: fonts.semibold, fontSize: 15 }} />
          <Button title="Сохранить" small successTitle="Сохранено ✓" onPress={saveTarget} />
        </View>
        {targetError ? <T v="small" style={{ color: colors.danger }}>{targetError}</T> : null}
        {!targetError && me.profile.target_weight ? (
          <T v="small">Текущая цель: {String(me.profile.target_weight).replace('.', ',')} кг. Прогресс к цели — на экране «Прогресс».</T>
        ) : null}
      </Card>

      <Card style={{ gap: 10 }}>
        <T v="h3">Отметить групповую тренировку</T>
        <T v="small">Йога, пилатес, сайкл и другие занятия засчитываются в недельный план.</T>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {Object.entries(meta.group_types).map(([key, name]) => (
            <Pressable key={key} accessibilityRole="button" accessibilityState={{ selected: groupType === key }} onPress={() => { setGroupType(key); setGroupNote(''); }}
              style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: groupType === key ? colors.accent : colors.surface2 }}>
              <T v="small" style={{ color: groupType === key ? colors.onAccent : colors.text, fontFamily: fonts.bold }}>{name}</T>
            </Pressable>
          ))}
        </View>
        {groupType ? (
          <>
            <Segmented label="Длительность" value={String(minutes)} onChange={(m) => setMinutes(Number(m))}
              options={[30, 45, 55, 60, 90].map((m) => ({ key: String(m), label: `${m}` }))} />
            <Button title={`Засчитать ${minutes} мин`} small onPress={logGroup} />
          </>
        ) : groupNote ? <T v="small" style={{ color: colors.accent }}>{groupNote}</T> : null}
      </Card>

      <Pressable accessibilityRole="button" accessibilityLabel="Друзья" onPress={() => router.push('/friends')}>
        <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          <View style={{ flex: 1, gap: 4 }}>
            <T v="h3">Друзья</T>
            <T v="small">{IOS_STORE ? 'Пригласи друга и тренируйтесь вместе' : 'Пригласи друга — вам обоим дни подписки в подарок'}</T>
          </View>
          <T v="small" style={{ color: colors.accent }}>Открыть</T>
        </Card>
      </Pressable>

      {!me.trainer && !me.is_trainer ? (
        <Card accent style={{ gap: 10 }}>
          <T v="h3" style={{ color: colors.onAccent }}>{IOS_STORE ? 'Персональный тренер' : 'Улучшить: занятия с тренером'}</T>
          <T v="small" style={{ color: colors.onAccent }}>
            {IOS_STORE ? 'Программа и контроль от персонального тренера. Выбери тренера по рейтингу.'
              : 'Тариф COACH — программа и контроль от персонального тренера. Выбери тренера по рейтингу.'}
          </T>
          <Button title="Выбрать тренера" variant="dark" small onPress={() => router.push('/trainers')} />
        </Card>
      ) : null}

      {IOS_STORE && !me.subscription_until ? null : (
        <Card style={{ gap: 8 }}>
          <T v="h3">Подписка</T>
          <T v="small">
            {me.subscription_until ? `Активна до ${me.subscription_until.split('-').reverse().join('.')}` : 'Сейчас все функции доступны бесплатно. Тарифы появятся позже.'}
          </T>
        </Card>
      )}

      <Button title="Выйти" variant="ghost" small onPress={async () => { await signOut(); router.replace('/login'); }} />
      <View style={{ flexDirection: 'row', justifyContent: 'center', gap: 20 }}>
        <Pressable accessibilityRole="link" onPress={openPrivacy}>
          <T v="small" style={{ textDecorationLine: 'underline' }}>Конфиденциальность</T>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Удалить аккаунт" onPress={() => confirmDelete(async () => {
          await api('/api/me', { method: 'DELETE' });
          await signOut();
          router.replace('/login');
        })}>
          <T v="small" style={{ color: colors.danger, textDecorationLine: 'underline' }}>Удалить аккаунт</T>
        </Pressable>
      </View>
      <T v="small" style={{ textAlign: 'center', fontSize: 11 }}>Версия сервера: {me.version}</T>
    </Screen>
  );
}

// Удаление аккаунта — с подтверждением (требование App Store и Google Play).
function confirmDelete(onYes: () => void) {
  const text = 'Аккаунт и все данные — тренировки, вес, объёмы, переписка — будут удалены навсегда. Восстановить их нельзя.';
  if (Platform.OS === 'web') {
    if (globalThis.confirm?.(`Удалить аккаунт?\n\n${text}`)) onYes();
    return;
  }
  Alert.alert('Удалить аккаунт?', text, [{ text: 'Отмена', style: 'cancel' }, { text: 'Удалить', style: 'destructive', onPress: onYes }]);
}
