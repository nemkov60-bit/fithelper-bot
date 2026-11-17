import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { Card, ErrorBox, IconButton, Loading, Screen, T } from '../components/ui';
import { api, type HistoryItem } from '../lib/api';
import { colors, fonts } from '../lib/theme';

export default function History() {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api<{ workouts: HistoryItem[] }>('/api/history?limit=30').then((r) => setItems(r.workouts))
      .catch((e) => setError(e?.message ?? 'Не удалось загрузить'));
  }, []);

  if (error) return <Screen><ErrorBox message={error} /></Screen>;
  if (!items) return <Loading />;

  return (
    <Screen bottomInset={40}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <IconButton icon="back" label="Назад" onPress={() => router.back()} />
        <T v="h1">История</T>
      </View>
      {items.length === 0 ? <Card><T v="small">Тренировок пока нет.</T></Card> : null}
      {items.map((w) => (
        <Card key={w.id} style={{ gap: 6 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 8 }}>
            <T v="h3" style={{ flex: 1 }}>{w.title}</T>
            <T v="small">{w.date.split('-').reverse().slice(0, 2).join('.')} · {w.minutes} мин</T>
          </View>
          {w.exercises.map((e) => (
            <T key={e.name} v="small" style={{ color: colors.soft }}>
              <T v="small" style={{ fontFamily: fonts.bold, color: colors.text }}>{e.name}: </T>{e.sets.join(', ')}
            </T>
          ))}
          {w.cardio.map((c) => <T key={c} v="small">{c}</T>)}
        </Card>
      ))}
    </Screen>
  );
}
