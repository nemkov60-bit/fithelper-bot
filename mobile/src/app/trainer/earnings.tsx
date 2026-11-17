import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { Button, Card, ErrorBox, IconButton, Loading, Screen, Stat, T } from '../../components/ui';
import { api } from '../../lib/api';
import { rub } from '../../lib/format';
import { colors, fonts } from '../../lib/theme';
import type { Earnings } from '../../lib/trainer';

const inputStyle = {
  minWidth: 0, height: 48, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg,
  color: colors.text, paddingHorizontal: 14, fontFamily: fonts.semibold, fontSize: 15,
};
const TYPES = { coaching: 'ведение', referral: 'реферал', refund: 'возврат' } as const;
const STATUSES = { pending: 'ожидает', available: 'доступно', paid: 'выплачено', cancelled: 'отменено' } as const;
const HINTS: Record<string, string> = {
  card: 'Номер карты', sbp: 'Телефон и банк, например +79991234567 Т-Банк', account: 'Р/с, БИК, банк',
};

function Choice({ options, value, onChange }: { options: Record<string, string>; value: string; onChange: (k: string) => void }) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
      {Object.entries(options).map(([k, v]) => (
        <Pressable key={k} accessibilityRole="button" accessibilityState={{ selected: value === k }} onPress={() => onChange(k)}
          style={{ paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999, backgroundColor: value === k ? colors.accent : colors.surface2 }}>
          <T v="small" style={{ color: value === k ? colors.onAccent : colors.text, fontFamily: fonts.bold }}>{v}</T>
        </Pressable>
      ))}
    </View>
  );
}

// Начисления тренера: баланс, история, выплаты и реквизиты.
export default function EarningsScreen() {
  const [data, setData] = useState<Earnings | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ legal_status: 'npd', full_name: '', inn: '', method: 'card', details: '' });
  const [formError, setFormError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api<Earnings>('/api/trainer/earnings');
      setData(d);
      if (d.requisites) setForm((f) => ({ ...f, legal_status: d.requisites!.legal_status, full_name: d.requisites!.full_name, inn: d.requisites!.inn, method: d.requisites!.method }));
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить');
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (error) return <Screen><ErrorBox message={error} onRetry={load} /></Screen>;
  if (!data) return <Loading />;
  const { balance: b, rules, requisites: req } = data;

  const save = async () => {
    setBusy(true);
    setFormError('');
    try {
      await api('/api/trainer/requisites', { method: 'PUT', body: form });
      setEditing(false);
      setForm((f) => ({ ...f, details: '' }));
      await load();
    } catch (e: any) {
      setFormError(e?.message ?? 'Не удалось сохранить');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen bottomInset={40}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <IconButton icon="back" label="Назад" onPress={() => router.back()} />
        <T v="h1" style={{ flex: 1 }}>Начисления</T>
      </View>

      <Card accent style={{ gap: 4, borderRadius: 28, padding: 20 }}>
        <T v="small" style={{ color: colors.onAccent, fontFamily: fonts.bold }}>Доступно к выплате</T>
        <T style={{ color: colors.onAccent, fontFamily: fonts.extrabold, fontSize: 38, lineHeight: 44 }}>{rub(b.available)}</T>
        <T v="small" style={{ color: colors.onAccent }}>Выплата раз в месяц, если набралось от {rub(rules.min_payout)}</T>
      </Card>
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Stat value={rub(b.pending)} label={`ожидает ${rules.hold_days} дн.`} />
        <Stat value={rub(b.paid)} label="выплачено" />
      </View>

      <Card style={{ gap: 6 }}>
        <T v="h3">Как начисляется</T>
        <T v="small">• Подопечный на тарифе с тренером — <T v="small" style={{ color: colors.accent, fontFamily: fonts.bold }}>{rules.coach_share}%</T> его оплаты.</T>
        <T v="small">• Пришёл по твоей ссылке на тариф без тренера — <T v="small" style={{ color: colors.accent, fontFamily: fonts.bold }}>{rules.level_percent}%</T> (процент твоего уровня), пока он платит.</T>
        <T v="small">• Первые {rules.hold_days} дней начисление «ожидает» — на случай возврата. Возврат отменяет начисление.</T>
      </Card>

      <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <T v="h2">Реквизиты</T>
        {req && !editing ? <Pressable accessibilityRole="button" onPress={() => setEditing(true)}><T v="small" style={{ color: colors.accent }}>Изменить</T></Pressable> : null}
      </View>
      {req && !editing ? (
        <Card style={{ gap: 4 }}>
          <T style={{ fontFamily: fonts.bold }}>{req.full_name}</T>
          <T v="small">{data.legal_statuses[req.legal_status]} · ИНН {req.inn}</T>
          <T v="small">{data.methods[req.method]} {req.details_masked}</T>
        </Card>
      ) : (
        <Card style={{ gap: 10, borderColor: req ? colors.border : colors.orange }}>
          {!req ? <T v="small" style={{ color: colors.orange }}>Без реквизитов выплата невозможна — начисления при этом сохраняются.</T> : null}
          <T v="small">Выплаты получают только самозанятые и ИП. С каждой выплаты формируй чек (самозанятый — в «Мой налог»).</T>
          <Choice options={data.legal_statuses} value={form.legal_status} onChange={(legal_status) => setForm({ ...form, legal_status })} />
          <TextInput value={form.full_name} onChangeText={(full_name) => setForm({ ...form, full_name })} placeholder="ФИО полностью"
            placeholderTextColor={colors.muted} accessibilityLabel="ФИО" maxLength={120} style={inputStyle} />
          <TextInput value={form.inn} onChangeText={(inn) => setForm({ ...form, inn })} placeholder="ИНН (12 цифр)" keyboardType="number-pad"
            placeholderTextColor={colors.muted} accessibilityLabel="ИНН" maxLength={12} style={inputStyle} />
          <Choice options={data.methods} value={form.method} onChange={(method) => setForm({ ...form, method })} />
          <TextInput value={form.details} onChangeText={(details) => setForm({ ...form, details })} placeholder={HINTS[form.method]}
            placeholderTextColor={colors.muted} accessibilityLabel="Реквизиты для перевода" maxLength={200} style={inputStyle} />
          {formError ? <T v="small" style={{ color: colors.orange }}>{formError}</T> : null}
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <Button title="Сохранить реквизиты" small loading={busy} style={{ flex: 1 }} onPress={save} />
            {req ? <Button title="Отмена" small variant="ghost" onPress={() => setEditing(false)} /> : null}
          </View>
        </Card>
      )}

      {data.payouts.length ? <T v="h2">Выплаты</T> : null}
      {data.payouts.map((p) => (
        <Card key={p.id} style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <View style={{ flex: 1, gap: 2 }}>
            <T style={{ fontFamily: fonts.bold }}>{rub(p.amount)}</T>
            <T v="small" style={{ fontSize: 12 }}>№{p.id} · {(p.paid || p.created).split('-').reverse().join('.')}</T>
          </View>
          <T v="small" style={{ color: p.status === 'paid' ? colors.accent : colors.orange, fontFamily: fonts.bold }}>
            {p.status === 'paid' ? 'Выплачено' : 'В обработке'}
          </T>
        </Card>
      ))}

      <T v="h2">История начислений</T>
      {data.commissions.length === 0 ? <Card><T v="small">Начислений пока нет. Они появятся, когда подопечные или приглашённые оплатят подписку.</T></Card> : null}
      {data.commissions.map((c) => (
        <Card key={c.id} style={{ flexDirection: 'row', alignItems: 'center', gap: 10, opacity: c.status === 'cancelled' ? 0.5 : 1 }}>
          <View style={{ flex: 1, gap: 2 }}>
            <T style={{ fontFamily: fonts.bold }}>{c.client || 'Пользователь'}</T>
            <T v="small" style={{ fontSize: 12 }}>
              {c.date.split('-').reverse().join('.')} · {TYPES[c.type]} {c.percent}% от {rub(Math.abs(c.base))}
              {c.status === 'pending' ? ` · доступно с ${c.available_at.split('-').reverse().join('.')}` : ''}
            </T>
          </View>
          <View style={{ alignItems: 'flex-end', gap: 2 }}>
            <T style={{ fontFamily: fonts.extrabold, color: c.amount < 0 ? colors.orange : colors.text }}>{rub(c.amount)}</T>
            <T v="small" style={{ fontSize: 11 }}>{STATUSES[c.status]}</T>
          </View>
        </Card>
      ))}
    </Screen>
  );
}
