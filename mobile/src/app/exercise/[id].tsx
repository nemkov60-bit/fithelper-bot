import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Image, ScrollView, View } from 'react-native';

import { Card, ErrorBox, IconButton, Loading, Screen, T } from '../../components/ui';
import { api, photoUrl, type Exercise } from '../../lib/api';
import { colors, fonts } from '../../lib/theme';
import { goBack } from '../../lib/nav';

// «📖 Техника»: фото кадров + понятное описание.
export default function ExerciseScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [ex, setEx] = useState<Exercise | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api<Exercise>(`/api/exercises/${id}`).then(setEx).catch((e) => setError(e?.message ?? 'Не удалось загрузить'));
  }, [id]);

  if (error) return <Screen><ErrorBox message={error} /></Screen>;
  if (!ex) return <Loading />;
  const photos = ex.photos.filter((p) => p.url);
  const t = ex.technique;

  return (
    <Screen bottomInset={40}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <IconButton icon="back" label="Назад" onPress={() => goBack('/home')} />
        <T v="small" style={{ flex: 1 }}>{ex.group_name}{t.secondary ? `, ${t.secondary}` : ''}</T>
      </View>
      <T v="h1">{ex.name}</T>

      {photos.length ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10 }}>
          {photos.map((p) => (
            <View key={p.n} style={{ width: 280, gap: 8 }}>
              <Image source={{ uri: photoUrl(p.url!) }} accessibilityLabel={p.caption}
                style={{ width: 280, height: 210, borderRadius: 22, backgroundColor: colors.surface2 }} />
              <T v="small">{p.n}. {p.caption}</T>
            </View>
          ))}
        </ScrollView>
      ) : (
        <Card style={{ gap: 6 }}>
          {ex.photos.map((p) => <T key={p.n} v="small">{p.n}. {p.caption}</T>)}
          <T v="small" style={{ fontSize: 12 }}>Фото техники скоро появятся.</T>
        </Card>
      )}

      <Card style={{ gap: 8 }}>
        <T v="h3">Подготовка</T>
        <T style={{ color: colors.soft }}>{t.setup}</T>
      </Card>
      <Card style={{ gap: 8 }}>
        <T v="h3">Выполнение</T>
        {t.steps.map((step, i) => (
          <View key={i} style={{ flexDirection: 'row', gap: 10 }}>
            <T style={{ color: colors.accent, fontFamily: fonts.extrabold, width: 18 }}>{i + 1}</T>
            <T style={{ flex: 1, color: colors.soft }}>{step}</T>
          </View>
        ))}
      </Card>
      <Card style={{ gap: 8 }}>
        <T v="h3">Дыхание</T>
        <T style={{ color: colors.soft }}>{t.breath}</T>
      </Card>
      <Card style={{ gap: 8 }}>
        <T v="h3">Частые ошибки</T>
        {t.mistakes.map((m) => <T key={m} style={{ color: colors.soft }}>• {m}</T>)}
      </Card>
      {ex.tip ? <Card accent><T style={{ color: colors.onAccent, fontFamily: fonts.bold }}>Главное: {ex.tip}</T></Card> : null}
      {ex.start_weight ? <T v="small">Стартовый вес: {ex.start_weight}</T> : null}
    </Screen>
  );
}
