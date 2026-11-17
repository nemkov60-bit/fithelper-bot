import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { Icon } from '../../components/Icon';
import { Badge, Button, Card, ErrorBox, Loading, Screen, Segmented, T } from '../../components/ui';
import { api, type Coach as CoachData } from '../../lib/api';
import { colors, fonts } from '../../lib/theme';

export default function Coach() {
  const [data, setData] = useState<CoachData | null>(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'up' | 'done'>('up');
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    setError('');
    try {
      setData(await api<CoachData>('/api/coach'));
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить');
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!data && !error) return <Loading />;
  if (!data) return <Screen><ErrorBox message={error} onRetry={load} /></Screen>;

  if (!data.trainer) {
    return (
      <Screen>
        <T v="big">Мой тренер</T>
        <Card style={{ gap: 10 }}>
          <T v="h3">Тренера пока нет</T>
          <T v="small">
            Занимайся по своей программе — она уже составлена под твою цель. Если у тебя есть тренер,
            попроси у него ссылку-приглашение и открой её в Telegram: тренер появится здесь, сможет
            назначать тренировки и писать тебе.
          </T>
        </Card>
      </Screen>
    );
  }

  const initials = data.trainer.name.split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase();
  const list = tab === 'up' ? data.assignments : data.done;

  const send = async () => {
    const text = draft.trim();
    if (!text) return;
    setSending(true);
    try {
      await api('/api/coach/messages', { body: { text } });
      setDraft('');
      await load();
    } finally {
      setSending(false);
    }
  };

  return (
    <Screen>
      <T v="big">Мой тренер</T>
      <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
        <View style={{ width: 56, height: 56, borderRadius: 28, backgroundColor: colors.accent, alignItems: 'center', justifyContent: 'center' }}>
          <T style={{ color: colors.onAccent, fontFamily: fonts.extrabold, fontSize: 19 }}>{initials}</T>
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <T v="h3" style={{ fontSize: 17 }}>{data.trainer.name}</T>
          <T v="small">Персональный тренер</T>
        </View>
      </Card>

      <Segmented label="Тренировки" value={tab} onChange={setTab}
        options={[{ key: 'up', label: 'Назначено' }, { key: 'done', label: 'Выполнено' }]} />

      {list.length === 0 ? (
        <Card><T v="small">{tab === 'up' ? 'Новых назначенных тренировок нет — занимайся по своей программе.' : 'Выполненных тренировок от тренера пока нет.'}</T></Card>
      ) : null}
      {list.map((a) => (
        <Card key={a.id} style={{ gap: 10, borderRadius: 28 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
            <T v="h3" style={{ flex: 1, fontSize: 17 }}>{a.title}</T>
            <Badge label={tab === 'up' ? a.date_label : 'выполнено'} tone={tab === 'up' ? 'outline' : 'accent'} />
          </View>
          {a.items.map((it, i) => (
            <T key={i} v="small" style={{ color: colors.soft }}>
              {i + 1}. {it.name} — {it.sets}×{it.lo === it.hi ? it.lo : `${it.lo}–${it.hi}`}{it.unit === 'sec' ? ' сек' : ''}{it.weight ? `, ${it.weight} кг` : ''}
            </T>
          ))}
          {a.note ? (
            <View style={{ padding: 12, borderRadius: 18, backgroundColor: colors.surface2 }}>
              <T style={{ fontSize: 14, color: colors.soft }}>«{a.note}»</T>
            </View>
          ) : null}
          {tab === 'up' ? (
            <Button title="Начать тренировку" small onPress={() => router.push({ pathname: '/workout', params: { assignment: String(a.id) } })} />
          ) : null}
        </Card>
      ))}

      <Card style={{ gap: 10, borderRadius: 28 }}>
        <T v="h3">Сообщения</T>
        {data.messages.length === 0 ? <T v="small">Напиши тренеру — он получит сообщение в Telegram.</T> : null}
        {data.messages.map((m, i) => (
          <View key={i} style={{
            maxWidth: '82%', alignSelf: m.mine ? 'flex-end' : 'flex-start', paddingHorizontal: 14, paddingVertical: 10,
            borderRadius: 18, backgroundColor: m.mine ? colors.accent : colors.surface2,
            borderBottomRightRadius: m.mine ? 6 : 18, borderBottomLeftRadius: m.mine ? 18 : 6,
          }}>
            <T style={{ fontSize: 14, color: m.mine ? colors.onAccent : colors.text }}>{m.text}</T>
          </View>
        ))}
        <View style={{ flexDirection: 'row', gap: 8, marginTop: 4 }}>
          <TextInput value={draft} onChangeText={setDraft} placeholder="Написать тренеру…" placeholderTextColor={colors.muted}
            accessibilityLabel="Сообщение тренеру" onSubmitEditing={send}
            style={{ flex: 1, minWidth: 0, height: 48, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg, color: colors.text, paddingHorizontal: 16, fontFamily: fonts.semibold, fontSize: 14 }} />
          <Pressable accessibilityRole="button" accessibilityLabel="Отправить" onPress={send} disabled={sending}
            style={{ width: 48, height: 48, borderRadius: 24, backgroundColor: colors.accent, alignItems: 'center', justifyContent: 'center', opacity: sending ? 0.6 : 1 }}>
            <Icon name="send" size={20} color={colors.onAccent} strokeWidth={2.4} />
          </Pressable>
        </View>
      </Card>
    </Screen>
  );
}
