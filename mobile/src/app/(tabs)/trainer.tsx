import * as Clipboard from 'expo-clipboard';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { Button, Card, ErrorBox, Loading, ProgressBar, Screen, Stat, T } from '../../components/ui';
import { api } from '../../lib/api';
import { colors, fonts } from '../../lib/theme';
import type { TrainerHome } from '../../lib/trainer';

// Кабинет тренера: уровень партнёрской программы, ссылки, подопечные.
export default function Trainer() {
  const [data, setData] = useState<TrainerHome | null>(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState('');
  const [adding, setAdding] = useState(false);
  const [showLevels, setShowLevels] = useState(false);

  const load = useCallback(async () => {
    setError('');
    try {
      setData(await api<TrainerHome>('/api/trainer'));
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось загрузить кабинет');
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!data && !error) return <Loading />;
  if (!data) return <Screen><ErrorBox message={error} onRetry={load} /></Screen>;

  const copy = async (url: string, code: string) => {
    await Clipboard.setStringAsync(url);
    setCopied(code);
  };
  const createLink = async () => {
    if (!newLabel.trim()) return;
    await api('/api/trainer/links', { body: { label: newLabel.trim() } });
    setNewLabel('');
    setAdding(false);
    await load();
  };

  return (
    <Screen>
      <View style={{ gap: 2 }}>
        <T v="small">Режим тренера</T>
        <T v="h1">Кабинет</T>
      </View>

      <Card accent style={{ gap: 12, borderRadius: 28, padding: 20 }}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 10 }}>
          <View style={{ flex: 1, gap: 4 }}>
            <T v="small" style={{ color: colors.onAccent, fontFamily: fonts.bold }}>Уровень партнёра</T>
            <T v="h1" style={{ color: colors.onAccent, fontSize: 26 }}>{data.level.name}</T>
            <T v="small" style={{ color: colors.onAccent }}>{data.level.description}</T>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <T style={{ color: colors.onAccent, fontFamily: fonts.extrabold, fontSize: 40, lineHeight: 44 }}>{data.level.percent}%</T>
            <T v="small" style={{ color: colors.onAccent, fontFamily: fonts.bold, fontSize: 12 }}>от подписки</T>
          </View>
        </View>
        {data.next ? (
          <>
            <ProgressBar value={data.next.progress} color={colors.onAccent} height={8} />
            <T v="small" style={{ color: colors.onAccent, fontFamily: fonts.bold }}>
              До {data.next.name} ({data.next.percent}%): ещё {data.next.left} подписчиков
            </T>
          </>
        ) : <T v="small" style={{ color: colors.onAccent, fontFamily: fonts.bold }}>У тебя максимальный уровень!</T>}
        <Pressable accessibilityRole="button" onPress={() => setShowLevels(!showLevels)}>
          <T v="small" style={{ color: colors.onAccent, textDecorationLine: 'underline' }}>{showLevels ? 'Скрыть уровни' : 'Все уровни программы'}</T>
        </Pressable>
      </Card>

      {showLevels ? (
        <Card style={{ gap: 10 }}>
          {data.levels.map((lv, i) => (
            <View key={lv.name} style={{ gap: 2, paddingTop: i ? 10 : 0, borderTopWidth: i ? 1 : 0, borderTopColor: colors.border }}>
              <T style={{ fontFamily: fonts.extrabold, color: lv.name === data.level.name ? colors.accent : colors.text }}>
                {lv.name} — {lv.percent}%{lv.name === data.level.name ? '  ← ты здесь' : ''}
              </T>
              <T v="small">{lv.from === 0 ? 'с первого подписчика' : `от ${lv.from} подписчиков`} · {lv.description}</T>
            </View>
          ))}
        </Card>
      ) : null}

      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Stat value={String(data.subscribers)} label="подписчиков" />
        <Stat value={String(data.invited)} label="пришло по ссылкам" />
        <Stat value={data.income !== null ? `${data.income} ₽` : String(data.clients.length)} label={data.income !== null ? 'доход в месяц' : 'подопечных'} />
      </View>

      <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <T v="h2">Ссылки</T>
        <Pressable accessibilityRole="button" onPress={() => setAdding(!adding)}>
          <T v="small" style={{ color: colors.accent }}>{adding ? 'Отмена' : '+ Новая ссылка'}</T>
        </Pressable>
      </View>
      {adding ? (
        <Card style={{ gap: 10 }}>
          <T v="small">Название видишь только ты — по нему понятно, откуда пришли люди.</T>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <TextInput value={newLabel} onChangeText={setNewLabel} placeholder="Instagram, зал на Ленина…" placeholderTextColor={colors.muted}
              accessibilityLabel="Название ссылки" maxLength={40}
              style={{ flex: 1, minWidth: 0, height: 48, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg, color: colors.text, paddingHorizontal: 14, fontFamily: fonts.semibold, fontSize: 15 }} />
            <Button title="Создать" small onPress={createLink} />
          </View>
        </Card>
      ) : null}
      {data.links.length === 0 && !adding ? <Card><T v="small">Ссылок пока нет — создай первую и отправь клиентам.</T></Card> : null}
      {data.links.map((l) => (
        <Card key={l.code} style={{ gap: 10 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 8 }}>
            <T style={{ fontFamily: fonts.extrabold, flex: 1 }}>{l.label}</T>
            <T v="small" style={{ fontSize: 12 }}>пришло {l.joined} · подписок {l.subs}</T>
          </View>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <View style={{ flex: 1, minWidth: 0, height: 46, paddingHorizontal: 14, borderRadius: 14, backgroundColor: colors.bg, borderWidth: 1, borderColor: colors.border, justifyContent: 'center' }}>
              <T v="small" numberOfLines={1} style={{ color: colors.soft }}>{l.url.replace('https://', '')}</T>
            </View>
            <Button title={copied === l.code ? 'Скопировано' : 'Копировать'} small variant={copied === l.code ? 'secondary' : 'primary'} onPress={() => copy(l.url, l.code)} />
          </View>
        </Card>
      ))}

      <T v="h2">Подопечные</T>
      {data.clients.length === 0 ? <Card><T v="small">Подопечных пока нет. Отправь клиенту ссылку — после его согласия он появится здесь.</T></Card> : null}
      {data.clients.map((c) => (
        <Card key={c.id} style={{ gap: 10, borderRadius: 22 }}>
          <Pressable accessibilityRole="button" onPress={() => router.push(`/trainer/client/${c.id}`)} style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <View style={{ width: 42, height: 42, borderRadius: 21, backgroundColor: colors.surface2, alignItems: 'center', justifyContent: 'center' }}>
              <T style={{ color: colors.accent, fontFamily: fonts.extrabold, fontSize: 14 }}>{c.name.split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase()}</T>
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <T style={{ fontFamily: fonts.bold }}>{c.name}</T>
              <T v="small" style={{ fontSize: 12 }}>{c.subscription ? 'подписка · ' : ''}{c.goal}{c.pending ? ` · назначено ${c.pending}` : ''}</T>
            </View>
            <T style={{ fontFamily: fonts.extrabold }}>{c.week}/{c.plan}</T>
          </Pressable>
          <ProgressBar value={c.plan ? c.week / c.plan : 0} color={c.week === 0 ? colors.orange : colors.accent} />
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <Button title="Назначить" small style={{ flex: 1 }} onPress={() => router.push(`/trainer/assign/${c.id}`)} />
            <Button title="Открыть" small variant="ghost" style={{ flex: 1 }} onPress={() => router.push(`/trainer/client/${c.id}`)} />
          </View>
        </Card>
      ))}
    </Screen>
  );
}
