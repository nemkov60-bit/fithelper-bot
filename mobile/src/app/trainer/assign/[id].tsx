import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { Button, Card, Chip, ErrorBox, IconButton, Loading, Screen, T } from '../../../components/ui';
import { api } from '../../../lib/api';
import { colors, fonts } from '../../../lib/theme';
import type { BuilderItem, Catalog, CatalogExercise, ClientCard } from '../../../lib/trainer';

const REPS = [[5, 5], [6, 8], [8, 10], [10, 12], [12, 15], [15, 20]];
const SECS = [[30, 30], [45, 45], [60, 60], [30, 60]];
const DAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

const inputStyle = () => ({
  minWidth: 0, height: 48, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg,
  color: colors.text, paddingHorizontal: 14, fontFamily: fonts.semibold, fontSize: 15,
} as const);

function isoDate(offset: number) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  const pad = (n: number) => String(n).padStart(2, '0');
  return { iso: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, label: offset === 0 ? 'Сегодня' : offset === 1 ? 'Завтра' : `${DAYS[d.getDay()]}, ${pad(d.getDate())}.${pad(d.getMonth() + 1)}` };
}

// Конструктор тренировки: день из программы подопечного или свои упражнения.
export default function Assign() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [client, setClient] = useState<ClientCard | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState('');
  const [title, setTitle] = useState('Тренировка от тренера');
  const [note, setNote] = useState('');
  const [date, setDate] = useState(isoDate(0).iso);
  const [items, setItems] = useState<BuilderItem[]>([]);
  const [adding, setAdding] = useState<{ group?: string; ex?: CatalogExercise; sets?: number; lo?: number; hi?: number } | null>(null);
  const [weight, setWeight] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([api<ClientCard>(`/api/trainer/clients/${id}`), api<Catalog>('/api/trainer/catalog')])
      .then(([c, cat]) => { setClient(c); setCatalog(cat); })
      .catch((e) => setError(e?.message ?? 'Не удалось загрузить'));
  }, [id]);

  const byId = useMemo(() => Object.fromEntries((catalog?.exercises ?? []).map((e) => [e.id, e])), [catalog]);

  if (error) return <Screen><ErrorBox message={error} /></Screen>;
  if (!client || !catalog) return <Loading />;

  const fromProgram = async (day: number) => {
    const r = await api<{ title: string; items: BuilderItem[] }>(`/api/trainer/clients/${id}/program-day/${day}`);
    setTitle(r.title);
    setItems(r.items);
  };
  const addItem = () => {
    if (!adding?.ex || !adding.sets || !adding.lo || !adding.hi) return;
    const w = parseFloat(weight.replace(',', '.'));
    setItems([...items, { ex: adding.ex.id, sets: adding.sets, lo: adding.lo, hi: adding.hi, w: w > 0 ? w : null }]);
    setAdding(null);
    setWeight('');
  };
  const save = async () => {
    setSaving(true);
    try {
      await api(`/api/trainer/clients/${id}/assignments`, { body: { date, title, note, items } });
      router.back();
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось назначить');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Screen bottomInset={40}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <IconButton icon="back" label="Назад" onPress={() => router.back()} />
        <View style={{ flex: 1 }}>
          <T v="h2">Новая тренировка</T>
          <T v="small" style={{ fontSize: 12 }}>для {client.name}</T>
        </View>
      </View>

      {client.program_days.length ? (
        <Card style={{ gap: 8 }}>
          <T v="h3">Взять день из его программы</T>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {client.program_days.map((d, i) => (
              <Pressable key={i} accessibilityRole="button" onPress={() => fromProgram(i)}
                style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surface2 }}>
                <T v="small" style={{ color: colors.text, fontFamily: fonts.bold }}>День {i + 1}: {d}</T>
              </Pressable>
            ))}
          </View>
        </Card>
      ) : null}

      <Card style={{ gap: 10 }}>
        <T v="label">НАЗВАНИЕ</T>
        <TextInput value={title} onChangeText={setTitle} maxLength={80} accessibilityLabel="Название тренировки" style={inputStyle()} />
        <T v="label">ДЕНЬ</T>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {[0, 1, 2, 3, 4, 5, 6].map((o) => {
            const d = isoDate(o);
            return (
              <Pressable key={d.iso} accessibilityRole="button" accessibilityState={{ selected: date === d.iso }} onPress={() => setDate(d.iso)}
                style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: date === d.iso ? colors.accent : colors.surface2 }}>
                <T v="small" style={{ color: date === d.iso ? colors.onAccent : colors.text, fontFamily: fonts.bold }}>{d.label}</T>
              </Pressable>
            );
          })}
        </View>
        <T v="label">КОММЕНТАРИЙ</T>
        <TextInput value={note} onChangeText={setNote} maxLength={500} multiline placeholder="Подопечный увидит его перед началом"
          placeholderTextColor={colors.muted} accessibilityLabel="Комментарий" style={[inputStyle(), { height: 80, paddingTop: 12, textAlignVertical: 'top' }]} />
      </Card>

      <T v="h2">Упражнения</T>
      {items.length === 0 ? <Card><T v="small">Добавь упражнения или возьми день из программы.</T></Card> : null}
      {items.map((it, i) => (
        <Card key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <T style={{ color: colors.accent, fontFamily: fonts.extrabold, width: 22 }}>{i + 1}</T>
          <View style={{ flex: 1 }}>
            <T style={{ fontFamily: fonts.bold, fontSize: 14 }}>{byId[it.ex]?.name ?? it.ex}</T>
            <T v="small" style={{ fontSize: 12 }}>
              {it.sets}×{it.lo === it.hi ? it.lo : `${it.lo}–${it.hi}`}{byId[it.ex]?.unit === 'sec' ? ' сек' : ''}{it.w ? `, ${it.w} кг` : ''}
            </T>
          </View>
          <IconButton icon="close" label="Убрать упражнение" onPress={() => setItems(items.filter((_, j) => j !== i))} />
        </Card>
      ))}

      {adding === null ? (
        <Button title="+ Добавить упражнение" variant="ghost" small onPress={() => setAdding({})} />
      ) : (
        <Card style={{ gap: 10, borderColor: colors.accent }}>
          {!adding.group ? (
            <>
              <T v="h3">Группа мышц</T>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
                {Object.entries(catalog.groups).map(([k, v]) => (
                  <Pressable key={k} accessibilityRole="button" onPress={() => setAdding({ group: k })}
                    style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surface2 }}>
                    <T v="small" style={{ color: colors.text, fontFamily: fonts.bold }}>{v}</T>
                  </Pressable>
                ))}
              </View>
            </>
          ) : !adding.ex ? (
            <>
              <T v="h3">{catalog.groups[adding.group]} — упражнение</T>
              {catalog.exercises.filter((e) => e.group === adding.group).map((e) => (
                <Pressable key={e.id} accessibilityRole="button" onPress={() => setAdding({ ...adding, ex: e })}
                  style={{ paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.border }}>
                  <T style={{ fontFamily: fonts.bold, fontSize: 14 }}>{e.name}</T>
                  <T v="small" style={{ fontSize: 12 }}>{e.equipment} · {e.places.map((p) => (p === 'gym' ? 'зал' : 'дом')).join(', ')}</T>
                </Pressable>
              ))}
            </>
          ) : (
            <>
              <T v="h3">{adding.ex.name}</T>
              <T v="label">ПОДХОДЫ</T>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                {[1, 2, 3, 4, 5, 6].map((n) => <Chip key={n} label={String(n)} on={adding.sets === n} onPress={() => setAdding({ ...adding, sets: n })} />)}
              </View>
              <T v="label">{adding.ex.unit === 'sec' ? 'СЕКУНДЫ' : 'ПОВТОРЫ'}</T>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
                {(adding.ex.unit === 'sec' ? SECS : REPS).map(([lo, hi]) => {
                  const on = adding.lo === lo && adding.hi === hi;
                  return (
                    <Pressable key={`${lo}-${hi}`} accessibilityRole="button" onPress={() => setAdding({ ...adding, lo, hi })}
                      style={{ paddingHorizontal: 14, height: 44, justifyContent: 'center', borderRadius: 14, backgroundColor: on ? colors.accent : colors.surface2 }}>
                      <T style={{ color: on ? colors.onAccent : colors.text, fontFamily: fonts.extrabold }}>{lo === hi ? lo : `${lo}–${hi}`}</T>
                    </Pressable>
                  );
                })}
              </View>
              {adding.ex.unit === 'reps' ? (
                <>
                  <T v="label">РАБОЧИЙ ВЕС, КГ (НЕОБЯЗАТЕЛЬНО)</T>
                  <TextInput value={weight} onChangeText={setWeight} keyboardType="decimal-pad" placeholder="Подопечный подберёт сам"
                    placeholderTextColor={colors.muted} accessibilityLabel="Рабочий вес" style={inputStyle()} />
                </>
              ) : null}
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <Button title="Отмена" variant="ghost" small style={{ flex: 1 }} onPress={() => setAdding(null)} />
                <Button title="Добавить" small style={{ flex: 1 }} disabled={!adding.sets || !adding.lo} onPress={addItem} />
              </View>
            </>
          )}
        </Card>
      )}

      <Button title="Назначить" icon="send" disabled={!items.length || !title.trim()} loading={saving} onPress={save} />
    </Screen>
  );
}
