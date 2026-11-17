import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { Icon } from '../../../components/Icon';
import { Badge, Button, Card, ErrorBox, IconButton, Loading, Screen, Segmented, Stat, T } from '../../../components/ui';
import { api } from '../../../lib/api';
import { useAuth } from '../../../lib/auth';
import { colors, fonts } from '../../../lib/theme';
import type { ClientCard } from '../../../lib/trainer';

const fmt = (n: number) => String(Math.round(n * 10) / 10).replace('.', ',');

// Карточка подопечного для тренера.
export default function ClientScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { meta } = useAuth();
  const [c, setC] = useState<ClientCard | null>(null);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    try {
      setC(await api<ClientCard>(`/api/trainer/clients/${id}`));
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить');
    }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (error) return <Screen><ErrorBox message={error} /></Screen>;
  if (!c || !meta) return <Loading />;

  const send = async () => {
    if (!draft.trim()) return;
    await api(`/api/trainer/clients/${id}/messages`, { body: { text: draft.trim() } });
    setDraft('');
    load();
  };
  const patch = async (body: Record<string, unknown>) => {
    const r = await api<{ changes: string[] }>(`/api/trainer/clients/${id}/program`, { method: 'PATCH', body });
    setNotice(r.changes.length ? `Сохранено: ${r.changes.join('; ')}. Подопечный получил уведомление.` : '');
    load();
  };
  const cancel = async (aid: number) => {
    await api(`/api/trainer/assignments/${aid}`, { method: 'DELETE' });
    load();
  };
  const weight = c.body_weight.length ? c.body_weight[c.body_weight.length - 1].weight : null;
  const weightDiff = c.body_weight.length > 1 ? weight! - c.body_weight[0].weight : null;

  return (
    <Screen bottomInset={40}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <IconButton icon="back" label="Назад" onPress={() => router.back()} />
        <View style={{ flex: 1 }}>
          <T v="h2">{c.name}</T>
          <T v="small" style={{ fontSize: 12 }}>{c.subscription_until ? `Подписка до ${c.subscription_until.split('-').reverse().join('.')}` : 'Без подписки'}</T>
        </View>
      </View>

      {c.labels ? (
        <Card style={{ gap: 4 }}>
          <T v="small">{c.labels.gender} · {c.labels.age}</T>
          <T style={{ fontFamily: fonts.bold }}>{c.labels.goal}</T>
          <T v="small">{c.labels.level} · {c.profile?.days} трен./нед. · {c.labels.place}</T>
        </Card>
      ) : <Card><T v="small">Подопечный ещё не заполнил анкету.</T></Card>}

      <Button title="Назначить тренировку" icon="calendar" onPress={() => router.push(`/trainer/assign/${c.id}`)} />

      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Stat value={`${c.week}/${c.profile?.days ?? '—'}`} label="за 7 дней" />
        <Stat value={String(c.month)} label={`за 30 дней${c.groups_month ? `, групп. ${c.groups_month}` : ''}`} />
        <Stat value={String(c.cardio_week)} label="мин кардио за неделю" />
      </View>
      {c.last ? <T v="small">Последняя тренировка: {c.last.date.split('-').reverse().join('.')} — {c.last.title}</T> : null}
      {weight !== null ? (
        <Card style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
          <T style={{ fontFamily: fonts.bold }}>Вес тела</T>
          <T style={{ fontFamily: fonts.extrabold }}>{fmt(weight)} кг{weightDiff !== null ? `  (${weightDiff > 0 ? '+' : ''}${fmt(weightDiff)})` : ''}</T>
        </Card>
      ) : null}

      {c.assignments.length ? (
        <Card style={{ gap: 10 }}>
          <T v="h3">Назначено</T>
          {c.assignments.map((a) => (
            <View key={a.id} style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
              <View style={{ flex: 1 }}>
                <T style={{ fontFamily: fonts.bold, fontSize: 14 }}>{a.title}</T>
                <T v="small" style={{ fontSize: 12 }}>{a.date_label} · {a.items.length} упр.</T>
              </View>
              <Button title="Отменить" small variant="ghost" onPress={() => cancel(a.id)} />
            </View>
          ))}
        </Card>
      ) : null}

      {c.records.length ? (
        <Card style={{ gap: 4 }}>
          <T v="h3" style={{ marginBottom: 6 }}>Рекорды</T>
          {c.records.map((r) => (
            <View key={r.name} style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 10, paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.border }}>
              <T style={{ flex: 1, fontSize: 14, fontFamily: fonts.bold }}>{r.name}</T>
              <T style={{ color: colors.accent, fontFamily: fonts.extrabold }}>{r.text}</T>
            </View>
          ))}
        </Card>
      ) : null}

      {c.profile ? (
        <Card style={{ gap: 10 }}>
          <Pressable accessibilityRole="button" onPress={() => setEditing(!editing)} style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <T v="h3">Изменить программу</T>
            <T v="small" style={{ color: colors.accent }}>{editing ? 'Скрыть' : 'Открыть'}</T>
          </Pressable>
          {notice ? <T v="small" style={{ color: colors.accent }}>{notice}</T> : null}
          {editing ? (
            <View style={{ gap: 12 }}>
              <T v="label">ЦЕЛЬ</T>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
                {Object.entries(meta.goals).map(([k, v]) => (
                  <Pressable key={k} accessibilityRole="button" onPress={() => patch({ goal: k })}
                    style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: c.profile!.goal === k ? colors.accent : colors.surface2 }}>
                    <T v="small" style={{ color: c.profile!.goal === k ? colors.onAccent : colors.text, fontFamily: fonts.bold }}>{v}</T>
                  </Pressable>
                ))}
              </View>
              <T v="label">ОПЫТ</T>
              <Segmented label="Опыт" value={c.profile.level} onChange={(level) => patch({ level })}
                options={[{ key: 'novice', label: 'Новичок' }, { key: 'mid', label: 'Средний' }, { key: 'pro', label: 'Опытный' }]} />
              <T v="label">ТРЕНИРОВОК В НЕДЕЛЮ</T>
              <Segmented label="Тренировок в неделю" value={String(c.profile.days)} onChange={(d) => patch({ days: Number(d) })}
                options={meta.day_options.map((d) => ({ key: String(d), label: String(d) }))} />
              <T v="label">МЕСТО</T>
              <Segmented label="Место" value={c.profile.place} onChange={(place) => patch({ place })}
                options={[{ key: 'gym', label: 'В зале' }, { key: 'home', label: 'Дома' }]} />
            </View>
          ) : null}
        </Card>
      ) : null}

      <Card style={{ gap: 10, borderRadius: 28 }}>
        <T v="h3">Сообщения</T>
        {c.messages.length === 0 ? <T v="small">Сообщение придёт подопечному в Telegram.</T> : null}
        {c.messages.map((m, i) => (
          <View key={i} style={{
            maxWidth: '82%', alignSelf: m.mine ? 'flex-end' : 'flex-start', paddingHorizontal: 14, paddingVertical: 10, borderRadius: 18,
            backgroundColor: m.mine ? colors.accent : colors.surface2,
          }}>
            <T style={{ fontSize: 14, color: m.mine ? colors.onAccent : colors.text }}>{m.text}</T>
          </View>
        ))}
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <TextInput value={draft} onChangeText={setDraft} placeholder="Написать подопечному…" placeholderTextColor={colors.muted}
            accessibilityLabel="Сообщение подопечному" onSubmitEditing={send}
            style={{ flex: 1, minWidth: 0, height: 48, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg, color: colors.text, paddingHorizontal: 16, fontFamily: fonts.semibold, fontSize: 14 }} />
          <Pressable accessibilityRole="button" accessibilityLabel="Отправить" onPress={send}
            style={{ width: 48, height: 48, borderRadius: 24, backgroundColor: colors.accent, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="send" size={20} color={colors.onAccent} strokeWidth={2.4} />
          </Pressable>
        </View>
      </Card>
      <Badge label={`ID ${c.id}`} tone="dark" />
    </Screen>
  );
}
