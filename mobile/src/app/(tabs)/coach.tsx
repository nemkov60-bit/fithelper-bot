import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert, Platform, Pressable, TextInput, View } from 'react-native';

import { Icon } from '../../components/Icon';
import { Stars } from '../../components/Stars';
import { TrainerAvatar } from '../../components/TrainerAvatar';
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
        <Card accent style={{ gap: 10, borderRadius: 28, padding: 20 }}>
          <T v="h2" style={{ color: colors.onAccent }}>Занимайся с тренером</T>
          <T style={{ color: colors.onAccent }}>
            Персональная программа, контроль техники, корректировки и поддержка. Выбери тренера по рейтингу и отзывам.
          </T>
          <Button title="Выбрать тренера" variant="dark" icon="arrow" onPress={() => router.push('/trainers')} />
        </Card>
        {data.pending.map((r) => (
          <Card key={r.id} style={{ gap: 8 }}>
            <T v="h3">Заявка отправлена</T>
            <T v="small">Тренер {r.trainer_name} скоро ответит. Ответ придёт в Telegram.</T>
            <Button title="Открыть профиль тренера" variant="ghost" small onPress={() => router.push(`/trainers/${r.trainer_id}`)} />
          </Card>
        ))}
        <Card style={{ gap: 6 }}>
          <T v="h3">Уже есть тренер?</T>
          <T v="small">Попроси у него ссылку-приглашение и открой её в Telegram — тренер появится здесь.</T>
        </Card>
      </Screen>
    );
  }

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
        <TrainerAvatar name={data.trainer.name} url={data.trainer.photo_url} />
        <Pressable style={{ flex: 1, gap: 4 }} accessibilityRole="button" onPress={() => router.push(`/trainers/${data.trainer!.id}`)}>
          <T v="h3" style={{ fontSize: 17 }}>{data.trainer.name}</T>
          {data.trainer.rating ? <Stars value={data.trainer.rating} size={14} /> : <T v="small">Персональный тренер</T>}
        </Pressable>
      </Card>
      {data.can_review && !data.my_review ? (
        <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <T v="small" style={{ flex: 1, color: colors.text }}>Как тебе занятия? Оцени тренера — это поможет другим выбрать.</T>
          <Button title="Оценить" small onPress={() => router.push(`/trainers/${data.trainer!.id}`)} />
        </Card>
      ) : null}

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
      <Button title="Отключиться от тренера" variant="ghost" small onPress={() => confirmLeave(async () => {
        await api('/api/coach/leave', { method: 'POST' });
        await load();
      })} />
    </Screen>
  );
}

function confirmLeave(onYes: () => void) {
  const text = 'Отключиться от тренера? Он перестанет видеть твой прогресс, назначенные тренировки отменятся.';
  if (Platform.OS === 'web') {
    if (globalThis.confirm?.(text)) onYes();
    return;
  }
  Alert.alert('Отключиться от тренера?', text, [{ text: 'Отмена', style: 'cancel' }, { text: 'Отключиться', style: 'destructive', onPress: onYes }]);
}
