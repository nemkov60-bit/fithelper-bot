import { useState } from 'react';
import { TextInput, View } from 'react-native';

import { api, type Measurements } from '../lib/api';
import { colors, fonts } from '../lib/theme';
import { Button, Card, T } from './ui';

const fmt = (n: number) => String(n).replace('.', ',');

// Объёмы тела: последние значения и изменение с первого замера; форма нового замера (для себя).
export function MeasurementsCard({ data, labels, editable, onSaved }: {
  data: Measurements; labels: Record<string, string>; editable?: boolean; onSaved?: (m: Measurements) => void;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const keys = Object.keys(labels);
  const has = keys.some((k) => data[k]);
  const last = keys.map((k) => data[k]?.date).filter(Boolean).sort().pop();

  const save = async () => {
    const body: Record<string, number> = {};
    for (const k of keys) {
      const v = parseFloat((form[k] ?? '').replace(',', '.'));
      if (v) body[k] = v;
    }
    setBusy(true);
    setError('');
    try {
      const r = await api<{ measurements: Measurements }>('/api/measurements', { body });
      setOpen(false);
      setForm({});
      onSaved?.(r.measurements);
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось сохранить');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card style={{ gap: 12, borderRadius: 28 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <T v="h3">Объёмы тела</T>
        {last ? <T v="small" style={{ fontSize: 12 }}>замер {last.split('-').reverse().join('.')}</T> : null}
      </View>
      {has ? keys.filter((k) => data[k]).map((k, i) => {
        const m = data[k];
        const d = m.total_delta;
        // Для талии уменьшение — хорошо, для остальных объёмов знак зависит от цели — показываем нейтрально.
        const good = d !== null && (k === 'waist' ? d < 0 : d > 0);
        return (
          <View key={k} style={{ flexDirection: 'row', alignItems: 'center', paddingTop: i ? 10 : 0, borderTopWidth: i ? 1 : 0, borderTopColor: colors.border }}>
            <T v="small" style={{ flex: 1, color: colors.soft }}>{labels[k]}</T>
            <T style={{ fontFamily: fonts.extrabold, width: 80, textAlign: 'right' }}>{fmt(m.value)} см</T>
            <T v="small" style={{ width: 70, textAlign: 'right', fontFamily: fonts.bold, color: d ? (good ? colors.accent : colors.orange) : colors.muted }}>
              {d ? `${d > 0 ? '+' : '−'}${fmt(Math.abs(d))}` : '—'}
            </T>
          </View>
        );
      }) : <T v="small">{editable ? 'Замеряй объёмы раз в 2–4 недели — так видно изменения, даже когда вес стоит на месте.' : 'Подопечный ещё не записывал объёмы.'}</T>}
      {editable && !open ? <Button title="Записать замер" small variant="secondary" onPress={() => setOpen(true)} /> : null}
      {editable && open ? (
        <View style={{ gap: 8 }}>
          <T v="small">В сантиметрах, утром. Заполни то, что мерил(а).</T>
          {keys.map((k) => (
            <View key={k} style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
              <T v="small" style={{ flex: 1, color: colors.text }}>{labels[k]}</T>
              <TextInput value={form[k] ?? ''} onChangeText={(v) => setForm({ ...form, [k]: v })} keyboardType="decimal-pad"
                placeholder={data[k] ? fmt(data[k].value) : 'см'} placeholderTextColor={colors.muted} accessibilityLabel={labels[k]}
                style={{ width: 96, height: 44, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg, color: colors.text, paddingHorizontal: 12, fontFamily: fonts.semibold, fontSize: 15, textAlign: 'right' }} />
            </View>
          ))}
          {error ? <T v="small" style={{ color: colors.orange }}>{error}</T> : null}
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <Button title="Сохранить замер" small loading={busy} style={{ flex: 1 }} onPress={save} />
            <Button title="Отмена" small variant="ghost" onPress={() => setOpen(false)} />
          </View>
        </View>
      ) : null}
    </Card>
  );
}
