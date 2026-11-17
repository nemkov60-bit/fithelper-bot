import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';

import { Badge, Button, Card, ErrorBox, IconButton, Loading, Screen, Segmented, T } from '../components/ui';
import { api } from '../lib/api';
import { colors, fonts } from '../lib/theme';

type Program = {
  place: string;
  next_day: number;
  days: { index: number; title: string; groups: string[]; exercises: { id: string; name: string; plan_text: string; swapped: boolean }[] }[];
};

export default function ProgramScreen() {
  const [place, setPlace] = useState<string | null>(null);
  const [data, setData] = useState<Program | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async (p: string | null) => {
    try {
      setData(await api<Program>(`/api/program${p ? `?place=${p}` : ''}`));
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить');
    }
  }, []);
  useEffect(() => { load(place); }, [load, place]);

  if (error) return <Screen><ErrorBox message={error} /></Screen>;
  if (!data) return <Loading />;
  const anySwapped = data.days.some((d) => d.exercises.some((e) => e.swapped));

  return (
    <Screen bottomInset={40}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <IconButton icon="back" label="Назад" onPress={() => router.back()} />
        <T v="h1">Программа</T>
      </View>
      <Segmented label="Место" value={data.place} onChange={(p) => setPlace(p)}
        options={[{ key: 'gym', label: 'В зале' }, { key: 'home', label: 'Дома' }]} />
      {data.days.map((d) => (
        <Card key={d.index} style={{ gap: 8, borderColor: d.index === data.next_day ? colors.accent : colors.border }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <T v="h3" style={{ flex: 1 }}>День {d.index + 1}. {d.title}</T>
            {d.index === data.next_day ? <Badge label="следующая" tone="outline" /> : null}
          </View>
          <T v="small">{d.groups.join(', ')}</T>
          {d.exercises.map((e) => (
            <Pressable key={e.id} accessibilityRole="button" onPress={() => router.push(`/exercise/${e.id}`)}
              style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 10, paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.border }}>
              <T style={{ flex: 1, fontFamily: fonts.bold, fontSize: 14 }}>{e.name}{e.swapped ? ' 🔄' : ''}</T>
              <T v="small" style={{ fontSize: 12 }}>{e.plan_text.split(',')[0]}</T>
            </Pressable>
          ))}
        </Card>
      ))}
      {anySwapped ? (
        <Button title="Вернуть исходные упражнения" variant="ghost" small onPress={async () => {
          await api('/api/swaps', { method: 'DELETE' });
          load(place);
        }} />
      ) : null}
    </Screen>
  );
}
