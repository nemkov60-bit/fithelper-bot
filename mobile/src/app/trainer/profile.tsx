import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, Switch, TextInput, View } from 'react-native';

import { TrainerAvatar } from '../../components/TrainerAvatar';
import { Button, Card, ErrorBox, IconButton, Loading, Screen, Segmented, T } from '../../components/ui';
import { api } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { colors, fonts } from '../../lib/theme';
import type { TrainerProfile } from '../../lib/trainer';

const inputStyle = () => ({
  minWidth: 0, height: 48, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg,
  color: colors.text, paddingHorizontal: 14, fontFamily: fonts.semibold, fontSize: 15,
} as const);

// Профиль тренера в каталоге: фото, о себе, специализации, опыт, город и формат.
export default function TrainerProfileScreen() {
  const { me } = useAuth();
  const [p, setP] = useState<TrainerProfile | null>(null);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<TrainerProfile>('/api/trainer/profile').then(setP).catch((e) => setError(e?.message ?? 'Не удалось загрузить'));
  }, []);

  if (error) return <Screen><ErrorBox message={error} /></Screen>;
  if (!p) return <Loading />;

  const set = (patch: Partial<TrainerProfile>) => { setP({ ...p, ...patch }); setSaved(''); };
  const toggleSpec = (k: string) => set({ specializations: p.specializations.includes(k) ? p.specializations.filter((x) => x !== k) : [...p.specializations, k] });

  const pickPhoto = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: 'images', allowsEditing: true, aspect: [1, 1], quality: 0.7, base64: true });
    if (r.canceled || !r.assets?.[0]?.base64) return;
    const asset = r.assets[0];
    const mime = asset.mimeType && ['image/jpeg', 'image/png', 'image/webp'].includes(asset.mimeType) ? asset.mimeType : 'image/jpeg';
    try {
      const res = await api<{ photo_url: string }>('/api/trainer/photo', { body: { data: asset.base64, mime } });
      set({ photo_url: res.photo_url });
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить фото');
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      const body = { bio: p.bio ?? '', specializations: p.specializations, experience_years: p.experience_years, certificates: p.certificates ?? '',
        city: p.city ?? '', format: p.format ?? 'both', max_clients: p.max_clients, listed: p.listed };
      setP(await api<TrainerProfile>('/api/trainer/profile', { method: 'PUT', body }));
      setSaved(p.listed && p.bio ? 'Сохранено — профиль виден в каталоге' : 'Сохранено');
    } catch (e: any) {
      setSaved(e?.message ?? 'Не удалось сохранить');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen bottomInset={40}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <IconButton icon="back" label="Назад" onPress={() => router.back()} />
        <T v="h1" style={{ flex: 1 }}>Профиль в каталоге</T>
      </View>
      <T v="small">Так тебя увидят пользователи, которые ищут тренера. Без текста «О себе» профиль в каталоге не показывается.</T>

      <Pressable accessibilityRole="button" accessibilityLabel="Изменить фото" onPress={pickPhoto} style={{ alignItems: 'center', gap: 8 }}>
        <TrainerAvatar name={me?.name || 'Тренер'} url={p.photo_url} size={110} />
        <T v="small" style={{ color: colors.accent }}>{p.photo_url ? 'Изменить фото' : 'Добавить фото'}</T>
      </Pressable>

      <Card style={{ gap: 10 }}>
        <T v="label">О СЕБЕ</T>
        <TextInput value={p.bio ?? ''} onChangeText={(bio) => set({ bio })} multiline maxLength={1500} accessibilityLabel="О себе"
          placeholder="Как работаешь, с кем, каких результатов добиваются подопечные" placeholderTextColor={colors.muted}
          style={[inputStyle(), { height: 130, paddingTop: 12, textAlignVertical: 'top' }]} />
        <T v="label">СПЕЦИАЛИЗАЦИИ</T>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {Object.entries(p.specializations_all).map(([k, v]) => {
            const on = p.specializations.includes(k);
            return (
              <Pressable key={k} accessibilityRole="checkbox" accessibilityState={{ checked: on }} onPress={() => toggleSpec(k)}
                style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: on ? colors.accent : colors.surface2 }}>
                <T v="small" style={{ color: on ? colors.onAccent : colors.text, fontFamily: fonts.bold }}>{v}</T>
              </Pressable>
            );
          })}
        </View>
        <T v="label">СТАЖ, ЛЕТ</T>
        <TextInput value={p.experience_years ? String(p.experience_years) : ''} keyboardType="number-pad" accessibilityLabel="Стаж в годах"
          onChangeText={(v) => set({ experience_years: v ? Math.min(60, parseInt(v, 10) || 0) : null })} style={inputStyle()} />
        <T v="label">ОБРАЗОВАНИЕ И СЕРТИФИКАТЫ</T>
        <TextInput value={p.certificates ?? ''} onChangeText={(certificates) => set({ certificates })} multiline maxLength={1000}
          accessibilityLabel="Сертификаты" style={[inputStyle(), { height: 90, paddingTop: 12, textAlignVertical: 'top' }]} />
      </Card>

      <Card style={{ gap: 10 }}>
        <T v="label">ФОРМАТ</T>
        <Segmented label="Формат" value={p.format ?? 'both'} onChange={(format) => set({ format })}
          options={[{ key: 'online', label: 'Онлайн' }, { key: 'offline', label: 'В зале' }, { key: 'both', label: 'Оба' }]} />
        <T v="label">ГОРОД</T>
        <TextInput value={p.city ?? ''} onChangeText={(city) => set({ city })} maxLength={60} accessibilityLabel="Город" style={inputStyle()} />
        <T v="label">ЛИМИТ ПОДОПЕЧНЫХ (ПУСТО — БЕЗ ЛИМИТА)</T>
        <TextInput value={p.max_clients ? String(p.max_clients) : ''} keyboardType="number-pad" accessibilityLabel="Лимит подопечных"
          onChangeText={(v) => set({ max_clients: v ? parseInt(v, 10) || null : null })} style={inputStyle()} />
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
          <T style={{ flex: 1, fontFamily: fonts.bold }}>Показывать меня в каталоге</T>
          <Switch value={p.listed} onValueChange={(listed) => set({ listed })} trackColor={{ true: colors.accent, false: colors.border }} />
        </View>
      </Card>

      {saved ? <T v="small" style={{ color: colors.accent }}>{saved}</T> : null}
      <Button title="Сохранить" loading={busy} onPress={save} />
    </Screen>
  );
}
