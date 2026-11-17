import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert, Platform, Pressable, View } from 'react-native';

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
  const last = data.messages[data.messages.length - 1];

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

      <Pressable accessibilityRole="button" accessibilityLabel="Чат с тренером" onPress={() => router.push(`/chat/${data.trainer!.id}`)}>
        <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 14, borderRadius: 24, borderColor: data.unread ? colors.accent : colors.border }}>
          <View style={{ width: 48, height: 48, borderRadius: 24, backgroundColor: colors.surface2, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="send" size={22} color={colors.accent} />
          </View>
          <View style={{ flex: 1, gap: 3 }}>
            <T v="h3">Чат с тренером</T>
            <T v="small" numberOfLines={1}>
              {last ? `${last.mine ? 'Ты: ' : ''}${last.text}` : 'Задай вопрос о технике, питании или самочувствии'}
            </T>
          </View>
          {data.unread ? (
            <View style={{ minWidth: 26, height: 26, borderRadius: 13, paddingHorizontal: 7, backgroundColor: colors.accent, alignItems: 'center', justifyContent: 'center' }}>
              <T style={{ fontSize: 13, fontFamily: fonts.extrabold, color: colors.onAccent }}>{data.unread}</T>
            </View>
          ) : <Icon name="arrow" size={20} color={colors.muted} />}
        </Card>
      </Pressable>

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
