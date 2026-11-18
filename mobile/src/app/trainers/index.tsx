import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, TextInput, View } from 'react-native';

import { PhotoBanner } from '../../components/PhotoBanner';
import { Stars } from '../../components/Stars';
import { TrainerAvatar } from '../../components/TrainerAvatar';
import { Badge, Card, ErrorBox, IconButton, Loading, Screen, Segmented, T } from '../../components/ui';
import { api } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { plural, REVIEWS, YEARS } from '../../lib/format';
import { colors, fonts } from '../../lib/theme';
import type { TrainerCard } from '../../lib/trainer';
import { goBack } from '../../lib/nav';

type Catalog = { trainers: TrainerCard[]; specializations: Record<string, string>; my_requests: number[] };

// Каталог тренеров: лучшие по рейтингу сверху, фильтры по специализации, формату и городу.
export default function Trainers() {
  const { me, meta } = useAuth();
  const coachPhoto = meta?.photos?.[`coach_${me?.profile.gender === 'f' ? 'f' : 'm'}`];
  const [data, setData] = useState<Catalog | null>(null);
  const [error, setError] = useState('');
  const [spec, setSpec] = useState('');
  const [format, setFormat] = useState<'all' | 'online' | 'offline'>('all');
  const [city, setCity] = useState('');

  const load = useCallback(async () => {
    try {
      const q = new URLSearchParams();
      if (spec) q.set('spec', spec);
      if (format !== 'all') q.set('format', format);
      if (city.trim()) q.set('city', city.trim());
      setData(await api<Catalog>(`/api/trainers?${q.toString()}`));
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить каталог');
    }
  }, [spec, format, city]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (error) return <Screen><ErrorBox message={error} onRetry={load} /></Screen>;
  if (!data) return <Loading />;

  return (
    <Screen bottomInset={40}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <IconButton icon="back" label="Назад" onPress={() => goBack('/coach')} />
        <T v="h1" style={{ flex: 1 }}>Тренеры</T>
      </View>
      {coachPhoto ? <PhotoBanner url={coachPhoto} minHeight={170} label="Занятия с тренером" /> : null}
      <T v="small">Персональная программа, контроль техники и прогресса. Рейтинг — по оценкам подопечных.</T>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        {[['', 'Все'], ...Object.entries(data.specializations)].map(([k, v]) => (
          <Pressable key={k || 'all'} accessibilityRole="button" accessibilityState={{ selected: spec === k }} onPress={() => setSpec(k)}
            style={{ paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999, backgroundColor: spec === k ? colors.accent : colors.surface }}>
            <T v="small" style={{ color: spec === k ? colors.onAccent : colors.text, fontFamily: fonts.bold }}>{v}</T>
          </Pressable>
        ))}
      </ScrollView>
      <Segmented label="Формат" value={format} onChange={setFormat}
        options={[{ key: 'all', label: 'Любой' }, { key: 'online', label: 'Онлайн' }, { key: 'offline', label: 'В зале' }]} />
      {format === 'offline' ? (
        <TextInput value={city} onChangeText={setCity} placeholder="Город" placeholderTextColor={colors.muted} accessibilityLabel="Город"
          style={{ height: 48, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, color: colors.text, paddingHorizontal: 14, fontFamily: fonts.semibold, fontSize: 15 }} />
      ) : null}

      {data.trainers.length === 0 ? <Card><T v="small">Тренеров по этим фильтрам пока нет. Попробуй другие.</T></Card> : null}
      {data.trainers.map((t) => (
        <Pressable key={t.id} accessibilityRole="button" accessibilityLabel={`Тренер ${t.name}`} onPress={() => router.push(`/trainers/${t.id}`)}>
          <Card style={{ gap: 12, borderRadius: 26 }}>
            <View style={{ flexDirection: 'row', gap: 14, alignItems: 'center' }}>
              <TrainerAvatar name={t.name} url={t.photo_url} size={60} />
              <View style={{ flex: 1, gap: 4 }}>
                <T v="h3" style={{ fontSize: 17 }}>{t.name}</T>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                  {t.rating ? <><Stars value={t.rating} size={15} /><T v="small" style={{ fontFamily: fonts.bold, color: colors.text }}>{String(t.rating).replace('.', ',')}</T></> : null}
                  <T v="small" style={{ fontSize: 12 }}>{t.reviews ? `${t.reviews} ${plural(t.reviews, REVIEWS)}` : 'Новый тренер'}</T>
                </View>
                <T v="small" style={{ fontSize: 12 }}>
                  {[t.experience_years ? `стаж ${t.experience_years} ${plural(t.experience_years, YEARS)}` : '', t.format_label, t.city].filter(Boolean).join(' · ')}
                </T>
              </View>
            </View>
            {t.specializations.length ? (
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
                {t.specializations.map((s) => <Badge key={s.key} label={s.label} tone="dark" />)}
              </View>
            ) : null}
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <T v="small" style={{ fontSize: 12 }}>Подопечных: {t.clients}</T>
              {data.my_requests.includes(t.id) ? <T v="small" style={{ color: colors.accent, fontSize: 12 }}>Заявка отправлена</T>
                : !t.has_room ? <T v="small" style={{ color: colors.orange, fontSize: 12 }}>Мест нет</T> : null}
            </View>
          </Card>
        </Pressable>
      ))}
    </Screen>
  );
}
