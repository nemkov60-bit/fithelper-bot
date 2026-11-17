import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, View } from 'react-native';

import { Icon } from '../../components/Icon';
import { Badge, Button, Card, ErrorBox, Loading, Ring, Screen, Segmented, T } from '../../components/ui';
import { api, type Today } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { colors, fonts } from '../../lib/theme';

const WEEKDAYS = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'];

export default function Home() {
  const { me } = useAuth();
  const [data, setData] = useState<Today | null>(null);
  const [place, setPlace] = useState<string | null>(null);
  const [day, setDay] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (p = place, d = day) => {
    setError('');
    try {
      const q = new URLSearchParams();
      if (p) q.set('place', p);
      if (d !== null) q.set('day', String(d));
      setData(await api<Today>(`/api/today?${q.toString()}`));
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить тренировку');
    }
  }, [place, day]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!data && !error) return <Loading />;
  if (!data) return <Screen><ErrorBox message={error} onRetry={() => load()} /></Screen>;

  const startWorkout = (assignment?: number) => {
    router.push({ pathname: '/workout', params: assignment ? { assignment: String(assignment) } : { place: data.place, day: String(data.day_index) } });
  };
  const name = me?.name ? `, ${me.name}` : '';
  const weekday = WEEKDAYS[new Date().getDay()];

  return (
    <Screen refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}>
      <View style={{ gap: 2 }}>
        <T v="small" style={{ fontFamily: fonts.semibold }}>
          {weekday[0].toUpperCase() + weekday.slice(1)} · день {data.day_index + 1} из {data.days}
        </T>
        <T v="h1">Привет{name}</T>
      </View>

      {data.assignments.map((a) => (
        <Card key={a.id} style={{ gap: 10, borderColor: colors.accent }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <T v="h3" style={{ flex: 1 }}>{a.title}</T>
            <Badge label={a.date_label} tone="outline" />
          </View>
          <T v="small">Тренировка от тренера · {a.items.length} упражнений</T>
          {a.note ? <T v="small" style={{ color: colors.soft }}>«{a.note}»</T> : null}
          <Button title="Начать тренировку от тренера" small onPress={() => startWorkout(a.id)} />
        </Card>
      ))}

      <View style={{ borderRadius: 28, overflow: 'hidden', backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, padding: 18, gap: 8, minHeight: 170, justifyContent: 'flex-end' }}>
        <Badge label="Тренировка дня" />
        <T v="h1">{data.plan.title}</T>
        <T v="small" style={{ color: colors.soft }}>{data.plan.groups.join(', ')}</T>
      </View>

      {data.notes.map((n) => (
        <Card key={n} style={{ backgroundColor: colors.surface2 }}><T v="small" style={{ color: colors.soft }}>{n}</T></Card>
      ))}

      <Segmented label="Где тренируемся" value={data.place}
        options={[{ key: 'gym', label: 'В зале' }, { key: 'home', label: 'Дома' }]}
        onChange={(p) => { setPlace(p); load(p, day); }} />

      <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <T v="h3" style={{ fontSize: 18 }}>Упражнения</T>
        <Pressable accessibilityRole="button" onPress={() => router.push('/program')}>
          <T v="small" style={{ color: colors.accent }}>Вся программа</T>
        </Pressable>
      </View>

      <View style={{ gap: 10 }}>
        {data.plan.exercises.map((e, i) => (
          <Pressable key={e.id} accessibilityRole="button" accessibilityLabel={`${e.name}, техника`}
            onPress={() => router.push(`/exercise/${e.id}`)}>
            <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 14, padding: 12, borderRadius: 22 }}>
              <View style={{ width: 52, height: 52, borderRadius: 16, backgroundColor: colors.surface2, alignItems: 'center', justifyContent: 'center' }}>
                <T style={{ color: colors.accent, fontFamily: fonts.extrabold }}>{String(i + 1).padStart(2, '0')}</T>
              </View>
              <View style={{ flex: 1, gap: 3 }}>
                <T style={{ fontFamily: fonts.bold }}>{e.name}</T>
                <T v="small">{e.sets} × {e.unit === 'sec' ? `${e.lo}–${e.hi} сек` : `${e.lo}–${e.hi}`}{e.weight ? ` · ${String(e.weight).replace('.', ',')} кг` : ''}</T>
              </View>
              <Icon name="book" size={20} />
            </Card>
          </Pressable>
        ))}
      </View>

      <Button title={data.light_day ? 'Начать облегчённую тренировку' : 'Начать тренировку'} icon="arrow" onPress={() => startWorkout()} />

      {data.program_days.length > 1 ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {data.program_days.map((t, i) => (
            <Pressable key={i} accessibilityRole="button" onPress={() => { setDay(i); load(place, i); }}
              style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: i === data.day_index ? colors.surface2 : 'transparent', borderWidth: 1, borderColor: colors.border }}>
              <T v="small" style={{ color: i === data.day_index ? colors.accent : colors.soft }}>День {i + 1}</T>
            </Pressable>
          ))}
        </View>
      ) : null}

      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Card style={{ flex: 1, gap: 10 }}>
          <T v="small">План недели</T>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <Ring value={data.week.done / data.week.plan} label={`Выполнено ${data.week.done} из ${data.week.plan}`} />
            <T v="big" style={{ fontSize: 26 }}>{data.week.done}<T v="small" style={{ fontSize: 16 }}>/{data.week.plan}</T></T>
          </View>
        </Card>
        <Card accent style={{ flex: 1, gap: 10 }}>
          <T v="small" style={{ color: colors.onAccent, fontFamily: fonts.bold }}>Серия</T>
          <T v="big" style={{ color: colors.onAccent, fontSize: 34 }}>{data.streak} <T style={{ color: colors.onAccent, fontFamily: fonts.extrabold }}>дн.</T></T>
        </Card>
      </View>

      <Card style={{ gap: 12 }}>
        <T v="small">Эта неделя</T>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
          {data.week.strip.map((d) => (
            <View key={d.date} style={{ alignItems: 'center', gap: 8 }}>
              <T v="small" style={{ fontSize: 12, fontFamily: fonts.bold }}>{d.label}</T>
              <View style={{
                width: 30, height: 30, borderRadius: 15,
                backgroundColor: d.done ? colors.accent : d.today ? 'transparent' : colors.border,
                borderWidth: d.today && !d.done ? 2 : 0, borderColor: colors.accent,
              }} />
            </View>
          ))}
        </View>
      </Card>
    </Screen>
  );
}
