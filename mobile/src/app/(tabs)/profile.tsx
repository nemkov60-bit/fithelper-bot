import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { Button, Card, Screen, Segmented, T } from '../../components/ui';
import { api } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { colors, fonts } from '../../lib/theme';

export default function Profile() {
  const { me, meta, refresh, signOut } = useAuth();
  const [target, setTarget] = useState(me?.profile.target_weight ? String(me.profile.target_weight) : '');
  const [groupType, setGroupType] = useState<string | null>(null);
  const [minutes, setMinutes] = useState(55);
  const [message, setMessage] = useState('');

  if (!me || !meta) return null;
  const p = me.profile;
  const label = (map: Record<string, string>, key: string | null) => (key && map[key]) || '—';

  const saveSettings = async (body: Record<string, unknown>, done = 'Сохранено') => {
    await api('/api/me/settings', { method: 'PATCH', body });
    await refresh();
    setMessage(done);
  };

  const logGroup = async () => {
    if (!groupType) return;
    await api('/api/groups/log', { body: { type: groupType, minutes } });
    setGroupType(null);
    setMessage('Групповая тренировка засчитана в прогресс');
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
          <Button title="Сохранить" small onPress={() => saveSettings({ target_weight: parseFloat(target.replace(',', '.')) || 0 }, 'Цель сохранена')} />
        </View>
      </Card>

      <Card style={{ gap: 10 }}>
        <T v="h3">Отметить групповую тренировку</T>
        <T v="small">Йога, пилатес, сайкл и другие занятия засчитываются в недельный план.</T>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {Object.entries(meta.group_types).map(([key, name]) => (
            <Pressable key={key} accessibilityRole="button" accessibilityState={{ selected: groupType === key }} onPress={() => setGroupType(key)}
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
        ) : null}
      </Card>

      <Card style={{ gap: 8 }}>
        <T v="h3">Подписка</T>
        <T v="small">
          {me.subscription_until ? `Активна до ${me.subscription_until.split('-').reverse().join('.')}` : 'Сейчас все функции доступны бесплатно. Тарифы появятся позже.'}
        </T>
      </Card>

      <Button title="Выйти" variant="ghost" small onPress={async () => { await signOut(); router.replace('/login'); }} />
      <T v="small" style={{ textAlign: 'center', fontSize: 11 }}>Версия сервера: {me.version}</T>
    </Screen>
  );
}
