import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, type ScrollViewInstance, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon } from '../../components/Icon';
import { TrainerAvatar } from '../../components/TrainerAvatar';
import { ErrorBox, IconButton, Loading, T } from '../../components/ui';
import { api, type Chat, type ChatMessage } from '../../lib/api';
import { colors, fonts } from '../../lib/theme';
import { goBack } from '../../lib/nav';

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

function dayLabel(iso: string) {
  const d = iso.slice(0, 10);
  const today = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  const ymd = (x: Date) => `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}`;
  if (d === ymd(today)) return 'Сегодня';
  if (d === ymd(new Date(today.getTime() - 86400000))) return 'Вчера';
  const [y, m, day] = d.split('-').map(Number);
  return `${day} ${MONTHS[m - 1]}${y !== today.getFullYear() ? ` ${y}` : ''}`;
}

// Чат тренера и подопечного в стиле мессенджера. Новые сообщения подгружаются каждые 5 секунд,
// собеседнику дополнительно приходит уведомление в Telegram.
export default function ChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const [chat, setChat] = useState<Chat | null>(null);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const scroll = useRef<ScrollViewInstance>(null);
  const lastId = useRef(0);

  const load = useCallback(async (full = false) => {
    try {
      const r = await api<Chat>(`/api/chat/${id}?after=${full ? 0 : lastId.current}`);
      setChat((prev) => {
        if (full || !prev) return r;
        // Новые сообщения + обновлённые отметки «прочитано» у своих.
        const fresh = r.messages.filter((m) => !prev.messages.some((p) => p.id === m.id));
        return fresh.length ? { ...r, messages: [...prev.messages, ...fresh] } : prev;
      });
      if (r.messages.length) lastId.current = Math.max(lastId.current, r.messages[r.messages.length - 1].id);
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить чат');
    }
  }, [id]);

  useFocusEffect(useCallback(() => {
    load(true);
    const t = setInterval(() => load(true), 5000); // полная загрузка — чтобы обновлялись галочки «прочитано»
    return () => clearInterval(t);
  }, [load]));

  useEffect(() => {
    setTimeout(() => scroll.current?.scrollToEnd({ animated: false }), 50);
  }, [chat?.messages.length]);

  if (error) return <View style={{ flex: 1, padding: 20, paddingTop: insets.top + 20, backgroundColor: colors.bg }}><ErrorBox message={error} onRetry={() => load(true)} /></View>;
  if (!chat) return <Loading />;

  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    setDraft('');
    try {
      const r = await api<{ message: ChatMessage }>(`/api/chat/${id}`, { body: { text } });
      setChat((prev) => (prev ? { ...prev, messages: [...prev.messages, r.message] } : prev));
      lastId.current = Math.max(lastId.current, r.message.id);
    } catch {
      setDraft(text);
    } finally {
      setSending(false);
    }
  };

  const { peer, messages } = chat;
  const isTrainer = peer.role === 'trainer';

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      {/* Шапка */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingTop: insets.top + 10, paddingBottom: 12,
        borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.bg }}>
        <IconButton icon="back" label="Назад" onPress={() => goBack(chat?.peer.role === 'client' ? '/trainer' : '/coach')} />
        <Pressable style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10 }} accessibilityRole="button"
          onPress={() => router.push(isTrainer ? `/trainers/${peer.id}` : `/trainer/client/${peer.id}`)}>
          <TrainerAvatar name={peer.name} url={peer.photo_url} size={42} />
          <View style={{ flex: 1 }}>
            <T v="h3" numberOfLines={1}>{peer.name}</T>
            <T v="small" style={{ fontSize: 12 }}>{isTrainer ? 'Твой тренер' : 'Подопечный'}</T>
          </View>
        </Pressable>
      </View>

      {/* Лента */}
      <ScrollView ref={scroll} contentContainerStyle={{ padding: 16, gap: 6, flexGrow: 1, justifyContent: messages.length ? 'flex-end' : 'center' }}
        onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: true })}>
        {messages.length === 0 ? (
          <View style={{ alignItems: 'center', gap: 8, paddingHorizontal: 24 }}>
            <Icon name="send" size={34} color={colors.accent} />
            <T v="h3" style={{ textAlign: 'center' }}>Начни разговор</T>
            <T v="small" style={{ textAlign: 'center' }}>
              {isTrainer ? 'Спроси тренера о технике, питании или расскажи, как прошла тренировка.' : 'Напиши подопечному — сообщение придёт ему и в Telegram.'}
            </T>
          </View>
        ) : null}
        {messages.map((m, i) => {
          const prev = messages[i - 1];
          const newDay = !prev || prev.at.slice(0, 10) !== m.at.slice(0, 10);
          const grouped = prev && !newDay && prev.mine === m.mine;
          return (
            <View key={m.id}>
              {newDay ? (
                <View style={{ alignSelf: 'center', marginVertical: 10, paddingHorizontal: 12, paddingVertical: 5, borderRadius: 999, backgroundColor: colors.surface2 }}>
                  <T v="small" style={{ fontSize: 12, fontFamily: fonts.bold }}>{dayLabel(m.at)}</T>
                </View>
              ) : null}
              <View style={{ flexDirection: 'row', justifyContent: m.mine ? 'flex-end' : 'flex-start', alignItems: 'flex-end', gap: 8, marginTop: grouped ? 0 : 6 }}>
                {!m.mine ? (
                  <View style={{ width: 30 }}>{!messages[i + 1] || messages[i + 1].mine || messages[i + 1].at.slice(0, 10) !== m.at.slice(0, 10)
                    ? <TrainerAvatar name={peer.name} url={peer.photo_url} size={30} /> : null}</View>
                ) : null}
                <View style={{
                  maxWidth: '78%', paddingHorizontal: 14, paddingTop: 9, paddingBottom: 7, borderRadius: 20,
                  backgroundColor: m.mine ? colors.accent : colors.surface, borderWidth: m.mine ? 0 : 1, borderColor: colors.border,
                  borderBottomRightRadius: m.mine ? 6 : 20, borderBottomLeftRadius: m.mine ? 20 : 6,
                }}>
                  <T style={{ fontSize: 15, lineHeight: 21, color: m.mine ? colors.onAccent : colors.text }}>{m.text}</T>
                  <View style={{ flexDirection: 'row', justifyContent: 'flex-end', alignItems: 'center', gap: 3, marginTop: 2 }}>
                    <T style={{ fontSize: 11, fontFamily: fonts.semibold, color: m.mine ? colors.onAccent : colors.muted, opacity: m.mine ? 0.7 : 1 }}>{m.at.slice(11, 16)}</T>
                    {m.mine ? <T style={{ fontSize: 11, fontFamily: fonts.bold, color: colors.onAccent, opacity: 0.7 }}>{m.read ? '✓✓' : '✓'}</T> : null}
                  </View>
                </View>
              </View>
            </View>
          );
        })}
      </ScrollView>

      {/* Поле ввода */}
      <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 8, paddingHorizontal: 12, paddingTop: 10, paddingBottom: insets.bottom + 10,
        borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.bg }}>
        <TextInput value={draft} onChangeText={setDraft} placeholder="Написать сообщение…" placeholderTextColor={colors.muted}
          accessibilityLabel="Сообщение" multiline maxLength={2000} onSubmitEditing={send} blurOnSubmit={false}
          onKeyPress={(e: any) => { if (Platform.OS === 'web' && e.nativeEvent.key === 'Enter' && !e.nativeEvent.shiftKey) { e.preventDefault?.(); send(); } }}
          style={{ flex: 1, minWidth: 0, minHeight: 46, maxHeight: 120, borderRadius: 23, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
            color: colors.text, paddingHorizontal: 16, paddingTop: 12, paddingBottom: 12, fontFamily: fonts.semibold, fontSize: 15 }} />
        <Pressable accessibilityRole="button" accessibilityLabel="Отправить" onPress={send} disabled={!draft.trim() || sending}
          style={{ width: 46, height: 46, borderRadius: 23, backgroundColor: colors.accent, alignItems: 'center', justifyContent: 'center', opacity: draft.trim() ? 1 : 0.5 }}>
          <Icon name="send" size={20} color={colors.onAccent} strokeWidth={2.4} />
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}
