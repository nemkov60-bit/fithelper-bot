import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useState } from 'react';
import { TextInput, View } from 'react-native';

import { Stars } from '../../components/Stars';
import { TrainerAvatar } from '../../components/TrainerAvatar';
import { Badge, Button, Card, ErrorBox, IconButton, Loading, Screen, Stat, T } from '../../components/ui';
import { api } from '../../lib/api';
import { plural, REVIEWS, YEARS } from '../../lib/format';
import { useAuth } from '../../lib/auth';
import { IOS_STORE } from '../../lib/platform';
import { colors, fonts } from '../../lib/theme';
import type { TrainerDetail } from '../../lib/trainer';
import { goBack } from '../../lib/nav';

const inputStyle = () => ({
  minWidth: 0, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg, color: colors.text,
  paddingHorizontal: 14, paddingTop: 12, fontFamily: fonts.semibold, fontSize: 15, height: 90, textAlignVertical: 'top' as const,
});

// Профиль тренера: о себе, специализации, отзывы, заявка на ведение и оценка.
export default function TrainerScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { refresh } = useAuth();
  const [t, setT] = useState<TrainerDetail | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [rating, setRating] = useState(0);
  const [review, setReview] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api<TrainerDetail>(`/api/trainers/${id}`);
      setT(d);
      if (d.my_review) {
        setRating(d.my_review.rating);
        setReview(d.my_review.text);
      }
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить');
    }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (error) return <Screen><ErrorBox message={error} /></Screen>;
  if (!t) return <Loading />;

  const sendRequest = async () => {
    setBusy(true);
    setNotice('');
    try {
      await api(`/api/trainers/${t.id}/requests`, { body: { message: message.trim() } });
      setNotice('Заявка отправлена! Тренер получит уведомление и ответит. Мы сообщим в Telegram.');
      await load();
    } catch (e: any) {
      setNotice(e?.message ?? 'Не удалось отправить заявку');
    } finally {
      setBusy(false);
    }
  };
  const cancelRequest = async () => {
    if (!t.my_request) return;
    await api(`/api/requests/${t.my_request.id}`, { method: 'DELETE' });
    setNotice('Заявка отменена');
    await load();
  };
  const sendReview = async () => {
    if (!rating) return;
    await api(`/api/trainers/${t.id}/review`, { body: { rating, text: review.trim() } });
    setNotice('Спасибо за отзыв!');
    await load();
    await refresh();
  };

  return (
    <Screen bottomInset={40}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <IconButton icon="back" label="Назад" onPress={() => goBack('/trainers')} />
        <T v="small" style={{ flex: 1 }}>Профиль тренера</T>
      </View>

      <View style={{ alignItems: 'center', gap: 10 }}>
        <TrainerAvatar name={t.name} url={t.photo_url} size={110} />
        <T v="h1" style={{ textAlign: 'center' }}>{t.name}</T>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          {t.rating ? <Stars value={t.rating} /> : null}
          <T v="small">{t.rating ? `${String(t.rating).replace('.', ',')} · ${t.reviews} ${plural(t.reviews, REVIEWS)}` : 'Пока без отзывов'}</T>
        </View>
        <T v="small">{[t.format_label, t.city].filter(Boolean).join(' · ')}</T>
      </View>

      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Stat value={t.experience_years ? `${t.experience_years}` : '—'} label={`${plural(t.experience_years ?? 5, YEARS)} стажа`} />
        <Stat value={String(t.clients)} label="подопечных" />
        <Stat value={String(t.reviews)} label={plural(t.reviews, REVIEWS)} />
      </View>

      {t.specializations.length ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
          {t.specializations.map((s) => <Badge key={s.key} label={s.label} />)}
        </View>
      ) : null}

      <Card style={{ gap: 8 }}>
        <T v="h3">О себе</T>
        <T style={{ color: colors.soft }}>{t.bio}</T>
      </Card>
      {t.certificates ? (
        <Card style={{ gap: 8 }}>
          <T v="h3">Образование и сертификаты</T>
          <T style={{ color: colors.soft }}>{t.certificates}</T>
        </Card>
      ) : null}

      {notice ? <Card style={{ backgroundColor: colors.surface2 }}><T v="small" style={{ color: colors.accent }}>{notice}</T></Card> : null}

      {t.is_my_trainer ? (
        <Card accent><T style={{ color: colors.onAccent, fontFamily: fonts.bold }}>Это твой тренер</T></Card>
      ) : t.my_request ? (
        <Card style={{ gap: 10 }}>
          <T v="h3">Заявка отправлена</T>
          <T v="small">Тренер посмотрит твою анкету и ответит. Ответ придёт в Telegram и появится в разделе «Тренер».</T>
          <Button title="Отменить заявку" variant="ghost" small onPress={cancelRequest} />
        </Card>
      ) : t.has_trainer ? (
        <Card><T v="small">У тебя уже есть тренер. Чтобы перейти к другому, сначала отключись от текущего в разделе «Тренер».</T></Card>
      ) : !t.has_room ? (
        <Card><T v="small" style={{ color: colors.orange }}>У тренера сейчас нет свободных мест.</T></Card>
      ) : (
        <Card style={{ gap: 10, borderColor: colors.accent }}>
          <T v="h3">Заниматься с тренером</T>
          <T v="small">
            Тренер составит программу, будет назначать тренировки, следить за техникой и прогрессом.
            {IOS_STORE ? '' : ' Тариф COACH — оплата подключится позже, сейчас ведение бесплатно.'}
          </T>
          <TextInput value={message} onChangeText={setMessage} multiline maxLength={500} placeholder="Расскажи о цели, травмах, опыте (необязательно)"
            placeholderTextColor={colors.muted} accessibilityLabel="Сообщение тренеру" style={inputStyle()} />
          <Button title="Отправить заявку" icon="send" loading={busy} onPress={sendRequest} />
        </Card>
      )}

      {t.can_review ? (
        <Card style={{ gap: 10 }}>
          <T v="h3">{t.my_review ? 'Твоя оценка' : 'Оцени тренера'}</T>
          <Stars value={rating} size={34} onChange={setRating} />
          <TextInput value={review} onChangeText={setReview} multiline maxLength={1000} placeholder="Что понравилось? (необязательно)"
            placeholderTextColor={colors.muted} accessibilityLabel="Отзыв" style={inputStyle()} />
          <Button title={t.my_review ? 'Обновить отзыв' : 'Оставить отзыв'} small disabled={!rating} onPress={sendReview} />
        </Card>
      ) : null}

      <T v="h2">Отзывы</T>
      {t.reviews_list.length === 0 ? <Card><T v="small">Отзывов пока нет. Оставить отзыв могут подопечные после 2 недель занятий.</T></Card> : null}
      {t.reviews_list.map((r, i) => (
        <Card key={i} style={{ gap: 6 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <T style={{ fontFamily: fonts.bold }}>{r.name}</T>
            <Stars value={r.rating} size={14} />
          </View>
          {r.text ? <T v="small" style={{ color: colors.soft }}>{r.text}</T> : null}
          <T v="small" style={{ fontSize: 11 }}>{r.date.split('-').reverse().join('.')}</T>
        </Card>
      ))}
    </Screen>
  );
}
