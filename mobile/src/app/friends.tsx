import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Image, Pressable, View } from 'react-native';

import { Button, Card, ErrorBox, IconButton, Loading, ProgressBar, Screen, Stat, T } from '../components/ui';
import { api, photoUrl } from '../lib/api';
import { plural } from '../lib/format';
import { IOS_STORE } from '../lib/platform';
import { shareCard, shareLink } from '../lib/share';
import { colors, fonts } from '../lib/theme';

type Friends = {
  invite_url: string; pair_url: string; friend_days: number; inviter_days: number;
  stats: { invited: number; paid: number; days: number };
  friends: { name: string; date: string; status: 'joined' | 'pending' | 'granted' | 'capped' | 'cancelled' }[];
  pair: { partner: string; goal: number; me: number; partner_done: number; streak: number; closed: boolean } | null;
  goals: number[]; card_url: string; has_workout: boolean;
};
const WEEKS: [string, string, string] = ['неделя', 'недели', 'недель'];
const FRIEND_STATUS: Record<string, string> = {
  joined: 'пришёл по ссылке', pending: 'оформил подписку · бонус скоро', granted: 'бонус получен', capped: 'лимит бонусов', cancelled: 'возврат',
};

// Друзья: личная ссылка, «Тренируйся с другом» и карточка результата.
export default function FriendsScreen() {
  const [d, setD] = useState<Friends | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setD(await api<Friends>('/api/friends'));
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить');
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (error) return <Screen><ErrorBox message={error} onRetry={load} /></Screen>;
  if (!d) return <Loading />;

  const cardPath = `${d.card_url}&gift=${IOS_STORE ? 0 : 1}`;
  const invite = async () => {
    const text = IOS_STORE ? 'Тренируйся со мной в FitHelper!' : `Тренируйся со мной в FitHelper — по ссылке +${d.friend_days} дней подписки в подарок:`;
    setNotice((await shareLink(text, d.invite_url)) === 'copied' ? 'Ссылка скопирована — отправь её другу' : '');
  };
  const invitePair = async () => {
    setNotice((await shareLink('Давай тренироваться вместе в FitHelper — общая цель на неделю и серия 🔥', d.pair_url)) === 'copied'
      ? 'Ссылка скопирована — когда друг её откроет, вы станете напарниками' : '');
  };
  const card = async () => {
    setBusy(true);
    try {
      setNotice((await shareCard(cardPath)) === 'downloaded' ? 'Карточка сохранена — выложи её в сторис' : '');
    } catch (e: any) {
      setNotice(e?.message ?? 'Не удалось поделиться');
    } finally {
      setBusy(false);
    }
  };
  const setGoal = async (goal: number) => setD(await api<Friends>('/api/friends/pair/goal', { body: { goal } }));
  const leave = async () => setD(await api<Friends>('/api/friends/pair', { method: 'DELETE' }));

  return (
    <Screen bottomInset={40}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <IconButton icon="back" label="Назад" onPress={() => router.back()} />
        <T v="h1" style={{ flex: 1 }}>Друзья</T>
      </View>
      {notice ? <Card style={{ backgroundColor: colors.surface2 }}><T v="small" style={{ color: colors.accent }}>{notice}</T></Card> : null}

      <Card accent style={{ gap: 10, borderRadius: 28, padding: 20 }}>
        <T v="h2" style={{ color: colors.onAccent }}>Пригласи друга</T>
        {IOS_STORE ? (
          <T v="small" style={{ color: colors.onAccent }}>Тренироваться вместе веселее — и бросить сложнее.</T>
        ) : (
          <T v="small" style={{ color: colors.onAccent }}>
            Друг сразу получит <T v="small" style={{ color: colors.onAccent, fontFamily: fonts.extrabold }}>+{d.friend_days} дней</T> подписки,
            а ты — <T v="small" style={{ color: colors.onAccent, fontFamily: fonts.extrabold }}>+{d.inviter_days} дней</T>, когда он оформит подписку.
          </T>
        )}
        <Button title="Пригласить друга" variant="dark" icon="send" onPress={invite} />
      </Card>
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Stat value={String(d.stats.invited)} label="пришло" />
        <Stat value={String(d.stats.paid)} label="с подпиской" />
        {IOS_STORE ? null : <Stat value={String(d.stats.days)} label="дней получено" />}
      </View>

      <T v="h2">Тренируйся с другом</T>
      {d.pair ? (
        <Card style={{ gap: 12 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <T v="h3">Ты и {d.pair.partner}</T>
            {d.pair.streak ? <T style={{ color: colors.orange, fontFamily: fonts.extrabold }}>🔥 {d.pair.streak} {plural(d.pair.streak, WEEKS)}</T> : null}
          </View>
          {[['Ты', d.pair.me], [d.pair.partner, d.pair.partner_done]].map(([name, n]) => (
            <View key={String(name)} style={{ gap: 6 }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                <T v="small" style={{ color: colors.text, fontFamily: fonts.bold }}>{name}</T>
                <T v="small">{n} из {d.pair!.goal}</T>
              </View>
              <ProgressBar value={Math.min(1, Number(n) / d.pair!.goal)} color={Number(n) >= d.pair!.goal ? colors.accent : colors.orange} />
            </View>
          ))}
          <T v="small">{d.pair.closed ? 'Неделя закрыта вместе — так держать!' : 'Закройте неделю оба — серия вырастет. Я сообщаю о тренировках друг друга.'}</T>
          <T v="small" style={{ color: colors.text, fontFamily: fonts.bold }}>Цель недели — тренировок каждому</T>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            {d.goals.map((g) => (
              <Pressable key={g} accessibilityRole="button" accessibilityLabel={`Цель ${g}`} accessibilityState={{ selected: d.pair!.goal === g }} onPress={() => setGoal(g)}
                style={{ flex: 1, height: 44, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: d.pair!.goal === g ? colors.accent : colors.surface2 }}>
                <T style={{ fontFamily: fonts.extrabold, color: d.pair!.goal === g ? colors.onAccent : colors.text }}>{g}</T>
              </Pressable>
            ))}
          </View>
          <Button title="Выйти из пары" variant="ghost" small onPress={leave} />
        </Card>
      ) : (
        <Card style={{ gap: 10 }}>
          <T v="small">Общая цель тренировок на неделю, прогресс друг друга и серия закрытых вместе недель 🔥 С напарником реже пропускают.</T>
          <Button title="Позвать напарника" icon="send" onPress={invitePair} />
        </Card>
      )}

      <T v="h2">Карточка результата</T>
      {d.has_workout ? (
        <Card style={{ gap: 12 }}>
          <Image source={{ uri: photoUrl(cardPath) }} accessibilityLabel="Карточка результата"
            style={{ width: '100%', aspectRatio: 1080 / 1350, borderRadius: 18, backgroundColor: colors.bg }} />
          <Button title="Поделиться карточкой" loading={busy} onPress={card} />
          <T v="small">На карточке QR-код с твоей ссылкой — его можно отсканировать прямо из сторис.</T>
        </Card>
      ) : <Card><T v="small">Заверши первую тренировку — и здесь появится карточка с результатом.</T></Card>}

      {d.friends.length ? <T v="h2">Приглашённые</T> : null}
      {d.friends.map((f, i) => (
        <Card key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <T style={{ flex: 1, fontFamily: fonts.bold }}>{f.name}</T>
          <T v="small" style={{ fontSize: 12, color: f.status === 'granted' ? colors.accent : colors.muted }}>
            {IOS_STORE ? f.date.split('-').reverse().join('.') : FRIEND_STATUS[f.status]}
          </T>
        </Card>
      ))}
    </Screen>
  );
}
