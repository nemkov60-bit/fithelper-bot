import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { TextInput, View } from 'react-native';

import { Icon } from '../../components/Icon';
import { LineChart } from '../../components/LineChart';
import { MeasurementsCard } from '../../components/Measurements';
import { Badge, Button, Card, ErrorBox, Loading, ProgressBar, Screen, Segmented, Stat, T } from '../../components/ui';
import { api, type Progress as ProgressData } from '../../lib/api';
import { colors, fonts } from '../../lib/theme';

const PERIODS = { '1m': 31, '3m': 92, '6m': 183, y: 366 } as const;
type Period = keyof typeof PERIODS;

const fmt = (n: number) => String(Math.round(n * 10) / 10).replace('.', ',');

export default function Progress() {
  const [data, setData] = useState<ProgressData | null>(null);
  const [error, setError] = useState('');
  const [period, setPeriod] = useState<Period>('3m');
  const [weightInput, setWeightInput] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError('');
    try {
      setData(await api<ProgressData>('/api/progress'));
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить прогресс');
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!data && !error) return <Loading />;
  if (!data) return <Screen><ErrorBox message={error} onRetry={load} /></Screen>;

  const since = new Date(Date.now() - PERIODS[period] * 86400000).toISOString().slice(0, 10);
  const weights = data.body_weight.filter((b) => b.date >= since);
  const current = data.body_weight.length ? data.body_weight[data.body_weight.length - 1].weight : null;
  const start = data.body_weight.length ? data.body_weight[0].weight : null;
  const target = data.target_weight;
  const goalPct = current !== null && start !== null && target && start !== target
    ? Math.max(0, Math.min(1, (start - current) / (start - target))) : null;

  const saveWeight = async () => {
    const value = parseFloat(weightInput.replace(',', '.'));
    if (!(value >= 20 && value <= 400)) return;
    setSaving(true);
    try {
      await api('/api/body-weight', { body: { weight: value } });
      setWeightInput('');
      await load();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Screen>
      <T v="big">Прогресс</T>

      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Card style={{ flex: 1, gap: 8 }}>
          <T v="small" style={{ fontSize: 12 }}>Вес тела</T>
          <T v="h1">{current !== null ? fmt(current) : '—'} <T v="small">кг</T></T>
          {goalPct !== null ? (
            <>
              <ProgressBar value={goalPct} />
              <T v="small" style={{ fontSize: 12 }}>Цель: {fmt(target!)} кг</T>
            </>
          ) : <T v="small" style={{ fontSize: 12 }}>Цель можно задать в профиле</T>}
        </Card>
        <Card style={{ flex: 1, alignItems: 'center', gap: 6 }}>
          <Icon name="flame" size={40} color={colors.orange} strokeWidth={1.8} />
          <T v="h1">{data.streak}</T>
          <T v="small" style={{ color: colors.orange, fontFamily: fonts.extrabold, fontSize: 12 }}>дней подряд</T>
        </Card>
      </View>

      <Card style={{ gap: 10 }}>
        <T v="h3">Записать вес</T>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <TextInput value={weightInput} onChangeText={setWeightInput} keyboardType="decimal-pad" placeholder="Например, 78,4"
            placeholderTextColor={colors.muted} accessibilityLabel="Вес тела в килограммах"
            style={{ flex: 1, minWidth: 0, height: 48, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg, color: colors.text, paddingHorizontal: 14, fontFamily: fonts.semibold, fontSize: 15 }} />
          <Button title="Сохранить" small onPress={saveWeight} loading={saving} />
        </View>
      </Card>

      {data.body_weight.length > 1 ? (
        <Card style={{ gap: 12, borderRadius: 28 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <T v="h3">Динамика веса</T>
            {goalPct !== null ? <Badge label={`${Math.round(goalPct * 100)}% цели`} tone="dark" /> : null}
          </View>
          <LineChart values={(weights.length > 1 ? weights : data.body_weight).map((b) => b.weight)} label="График веса тела" />
          <Segmented label="Период" value={period} onChange={setPeriod}
            options={[{ key: '1m', label: '1М' }, { key: '3m', label: '3М' }, { key: '6m', label: '6М' }, { key: 'y', label: 'Год' }]} />
        </Card>
      ) : null}

      <MeasurementsCard data={data.measurements} labels={data.measure_labels} editable
        onSaved={(measurements) => setData({ ...data, measurements })} />

      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Stat value={String(data.month)} label="тренировок за месяц" />
        <Stat value={data.tonnage_month >= 1000 ? `${fmt(data.tonnage_month / 1000)} т` : `${data.tonnage_month} кг`} label="поднято за месяц" />
        <Stat value={String(data.cardio_week)} label="мин кардио за неделю" />
      </View>
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Stat value={`${data.week}/${data.plan}`} label="тренировок за 7 дней" />
        <Stat value={String(data.total)} label="тренировок всего" />
        <Stat value={String(data.groups_month.count)} label="групповых за месяц" />
      </View>

      <Card style={{ gap: 4, borderRadius: 28 }}>
        <T v="h3" style={{ marginBottom: 6 }}>Личные рекорды</T>
        {data.records.length === 0 ? <T v="small">Рекорды появятся после первых тренировок.</T> : null}
        {data.records.map((r) => (
          <View key={r.id} style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10, paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.border }}>
            <View style={{ flex: 1, gap: 2 }}>
              <T style={{ fontFamily: fonts.bold, fontSize: 14 }}>{r.name}</T>
              <T v="small" style={{ fontSize: 12 }}>{r.date}{r.e1rm ? ` · ≈1ПМ ${fmt(r.e1rm)} кг` : ''}</T>
            </View>
            <T style={{ color: colors.accent, fontFamily: fonts.extrabold }}>{r.text}</T>
          </View>
        ))}
      </Card>

      <Button title="История тренировок" variant="ghost" small onPress={() => router.push('/history')} />
    </Screen>
  );
}
