import * as Haptics from 'expo-haptics';
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Modal, Platform, Pressable, ScrollView, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Icon } from '../components/Icon';
import { Badge, Button, Card, Chip, IconButton, Loading, ProgressBar, Screen, T } from '../components/ui';
import { api, type CardioInfo, type DayPlan, type PlannedExercise } from '../lib/api';
import { colors, fonts } from '../lib/theme';

type Stage = 'warmup' | 'main' | 'cooldown' | 'summary';
type LoggedSet = { weight: number; reps: number };
type Summary = { cancelled: boolean; minutes: number; sets: number; exercises: number; tonnage: number; records: string[]; cardio: string[]; week: { done: number; plan: number } };

const fmt = (n: number) => String(Math.round(n * 100) / 100).replace('.', ',');

function confirm(title: string, message: string, onYes: () => void) {
  if (Platform.OS === 'web') {
    if (globalThis.confirm?.(`${title}\n\n${message}`)) onYes();
    return;
  }
  Alert.alert(title, message, [{ text: 'Отмена', style: 'cancel' }, { text: 'Да', style: 'destructive', onPress: onYes }]);
}

export default function Workout() {
  const params = useLocalSearchParams<{ place?: string; day?: string; assignment?: string }>();
  const [wid, setWid] = useState<number | null>(null);
  const [assignmentId, setAssignmentId] = useState<number | null>(null);
  const [plan, setPlan] = useState<DayPlan | null>(null);
  const [place, setPlace] = useState('gym');
  const [dayIndex, setDayIndex] = useState(0);
  const [notes, setNotes] = useState<string[]>([]);
  const [stage, setStage] = useState<Stage>('warmup');
  const [pos, setPos] = useState(0);
  const [logged, setLogged] = useState<Record<string, LoggedSet[]>>({});
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [reps, setReps] = useState<Record<string, number>>({});
  const [rest, setRest] = useState(0);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [swapOpen, setSwapOpen] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        const body = params.assignment ? { assignment_id: Number(params.assignment) }
          : { place: params.place, day: params.day !== undefined ? Number(params.day) : undefined };
        const r = await api<{ id: number; assignment_id: number | null; place: string; day_index?: number; plan: DayPlan; notes: string[] }>(
          '/api/workouts', { body });
        setWid(r.id);
        setAssignmentId(r.assignment_id);
        setPlan(r.plan);
        setPlace(r.place);
        setDayIndex(r.day_index ?? 0);
        setNotes(r.notes);
        setWeights(Object.fromEntries(r.plan.exercises.map((e) => [e.id, e.weight])));
        setReps(Object.fromEntries(r.plan.exercises.map((e) => [e.id, e.unit === 'sec' ? e.rep_options[1] ?? e.lo : e.hi])));
      } catch (e: any) {
        setError(e?.message ?? 'Не удалось начать тренировку');
      }
    })();
  }, [params.assignment, params.place, params.day]);

  useEffect(() => {
    if (rest <= 0) return;
    const t = setInterval(() => setRest((r) => {
      if (r <= 1) {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
        return 0;
      }
      return r - 1;
    }), 1000);
    return () => clearInterval(t);
  }, [rest > 0]);

  const finish = useCallback(async () => {
    if (!wid) return;
    setBusy(true);
    try {
      const r = await api<Summary>(`/api/workouts/${wid}/finish`, { body: { assignment_id: assignmentId } });
      if (r.cancelled) {
        router.back();
        return;
      }
      setSummary(r);
      setStage('summary');
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось завершить');
    } finally {
      setBusy(false);
    }
  }, [wid, assignmentId]);

  const groups = useMemo(() => [...new Set(plan?.exercises.map((e) => e.group) ?? [])].join(','), [plan]);

  if (error) {
    return <Screen><Card style={{ gap: 12 }}><T>{error}</T><Button title="Назад" variant="secondary" onPress={() => router.back()} /></Card></Screen>;
  }
  if (!plan || !wid) return <Loading />;

  const totalSets = plan.exercises.reduce((n, e) => n + e.sets, 0);
  const doneSets = Object.values(logged).reduce((n, l) => n + l.length, 0);

  const header = (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
      <IconButton icon="close" label="Прервать тренировку" onPress={() => confirm('Прервать тренировку?', 'Записанные подходы сохранятся, если их больше нуля.', async () => {
        if (doneSets > 0) {
          await finish();
        } else {
          await api(`/api/workouts/${wid}`, { method: 'DELETE' }).catch(() => undefined);
          router.back();
        }
      })} />
      <View style={{ alignItems: 'center', flex: 1 }}>
        <T v="h3" numberOfLines={1}>{plan.title}</T>
        <T v="small" style={{ fontSize: 12 }}>
          {stage === 'warmup' ? 'Разминка' : stage === 'cooldown' ? 'Заминка' : stage === 'summary' ? 'Готово' : `Упражнение ${pos + 1} из ${plan.exercises.length}`}
        </T>
      </View>
      <View style={{ width: 46 }} />
    </View>
  );

  if (stage === 'summary' && summary) {
    return (
      <Screen bottomInset={40}>
        {header}
        <Card accent style={{ gap: 6, borderRadius: 28, padding: 20 }}>
          <T v="h1" style={{ color: colors.onAccent }}>Тренировка завершена!</T>
          <T style={{ color: colors.onAccent }}>Отличная работа 💪</T>
        </Card>
        <View style={{ flexDirection: 'row', gap: 10 }}>
          <Card style={{ flex: 1 }}><T v="h2">{summary.minutes}</T><T v="small">минут</T></Card>
          <Card style={{ flex: 1 }}><T v="h2">{summary.sets}</T><T v="small">подходов</T></Card>
          <Card style={{ flex: 1 }}><T v="h2">{summary.tonnage}</T><T v="small">кг поднято</T></Card>
        </View>
        {summary.records.length ? (
          <Card style={{ gap: 6 }}>
            <T v="h3">Новые рекорды</T>
            {summary.records.map((r) => <T key={r} v="small" style={{ color: colors.accent }}>{r}</T>)}
          </Card>
        ) : null}
        {summary.cardio.length ? <Card style={{ gap: 6 }}>{summary.cardio.map((c) => <T key={c} v="small">{c}</T>)}</Card> : null}
        <Card style={{ gap: 8 }}>
          <T v="small">На этой неделе: {summary.week.done} из {summary.week.plan} тренировок</T>
          <ProgressBar value={summary.week.done / summary.week.plan} />
        </Card>
        <Button title="На главную" onPress={() => router.replace('/home')} />
      </Screen>
    );
  }

  if (stage === 'warmup' || stage === 'cooldown') {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['top', 'bottom']}>
        <ScrollView contentContainerStyle={{ padding: 20, gap: 14, paddingBottom: 40 }}>
          {header}
          {stage === 'warmup' && notes.map((n) => <Card key={n} style={{ backgroundColor: colors.surface2 }}><T v="small" style={{ color: colors.soft }}>{n}</T></Card>)}
          <CardioStage key={stage} phase={stage} place={place} groups={groups} wid={wid}
            onDone={() => (stage === 'warmup' ? setStage('main') : finish())} busy={busy} />
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ---------- Основная часть ----------
  const ex = plan.exercises[pos];
  const exLogged = logged[ex.id] ?? [];
  const setNo = exLogged.length + 1;
  const weight = weights[ex.id] ?? 0;
  const chosenReps = reps[ex.id] ?? ex.hi;
  const [small, big] = ex.equipment.steps;
  const allDone = exLogged.length >= ex.sets;

  const changeWeight = (delta: number) => setWeights({ ...weights, [ex.id]: Math.max(0, Math.round((weight + delta) * 100) / 100) });

  const logSet = async () => {
    setBusy(true);
    try {
      const w = ex.unit === 'sec' ? 0 : weight;
      await api(`/api/workouts/${wid}/sets`, { body: { exercise_id: ex.id, set_no: setNo, weight: w, reps: chosenReps } });
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => undefined);
      const next = [...exLogged, { weight: w, reps: chosenReps }];
      setLogged({ ...logged, [ex.id]: next });
      const lastOverall = next.length >= ex.sets && pos === plan.exercises.length - 1;
      if (!lastOverall) setRest(ex.rest);
      if (next.length >= ex.sets && pos < plan.exercises.length - 1) setPos(pos + 1);
    } catch (e: any) {
      setError(e?.message ?? 'Не удалось записать подход');
    } finally {
      setBusy(false);
    }
  };

  const undo = async () => {
    if (!exLogged.length) return;
    await api(`/api/workouts/${wid}/sets/last`, { method: 'DELETE' });
    setLogged({ ...logged, [ex.id]: exLogged.slice(0, -1) });
  };

  const goCooldown = () => {
    setRest(0);
    setStage('cooldown');
  };

  const replace = (alt: PlannedExercise) => {
    const exercises = plan.exercises.map((e, i) => (i === pos ? alt : e));
    setPlan({ ...plan, exercises });
    setWeights({ ...weights, [alt.id]: alt.weight });
    setReps({ ...reps, [alt.id]: alt.unit === 'sec' ? alt.rep_options[1] ?? alt.lo : alt.hi });
    setSwapOpen(false);
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['top', 'bottom']}>
      <ScrollView contentContainerStyle={{ padding: 20, gap: 14, paddingBottom: 40 }}>
        {header}
        <ProgressBar value={doneSets / totalSets} />

        <Card style={{ gap: 14, borderRadius: 28, padding: 18 }}>
          <View style={{ gap: 6 }}>
            <Badge label={allDone ? 'Все подходы выполнены' : `Подход ${setNo} из ${ex.sets}`} tone="dark" />
            <T v="h1" style={{ fontSize: 22 }}>{ex.name}</T>
            <T v="small">{ex.plan_text}</T>
          </View>
          <T v="small" style={{ color: colors.soft }}>💡 {ex.advice}</T>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <Button title="Техника" variant="ghost" small icon="book" style={{ flex: 1 }} onPress={() => router.push(`/exercise/${ex.id}`)} />
            {assignmentId ? null : <Button title="Заменить" variant="ghost" small icon="swap" style={{ flex: 1 }} onPress={() => setSwapOpen(true)} />}
          </View>

          {ex.unit === 'reps' ? (
            <View style={{ gap: 8 }}>
              <T v="label">ВЕС · {ex.equipment.hint.toUpperCase()}</T>
              <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
                <Chip label={`−${fmt(big)}`} onPress={() => changeWeight(-big)} style={{ flex: 0, width: 56 }} />
                <Chip label={`−${fmt(small)}`} onPress={() => changeWeight(-small)} style={{ flex: 0, width: 56 }} />
                <View style={{ flex: 1, height: 56, borderRadius: 18, borderWidth: 1, borderColor: colors.border, alignItems: 'center', justifyContent: 'center' }}>
                  <T style={{ fontFamily: fonts.extrabold, fontSize: 26 }}>{fmt(weight)} <T v="small">кг</T></T>
                </View>
                <Chip label={`+${fmt(small)}`} onPress={() => changeWeight(small)} style={{ flex: 0, width: 56 }} />
                <Chip label={`+${fmt(big)}`} onPress={() => changeWeight(big)} style={{ flex: 0, width: 56 }} />
              </View>
            </View>
          ) : null}

          <View style={{ gap: 8 }}>
            <T v="label">{ex.unit === 'sec' ? 'СЕКУНДЫ' : 'ПОВТОРЫ'}</T>
            <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
              {ex.rep_options.map((n) => (
                <Chip key={n} label={ex.unit === 'sec' ? `${n}с` : String(n)} on={n === chosenReps} onPress={() => setReps({ ...reps, [ex.id]: n })} />
              ))}
            </View>
          </View>

          <Button title={allDone ? 'Ещё подход' : 'Записать подход'} onPress={logSet} loading={busy} />
        </Card>

        {rest > 0 ? (
          <Card accent style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <View>
              <T v="small" style={{ color: colors.onAccent, fontFamily: fonts.bold }}>Отдых</T>
              <T v="big" style={{ color: colors.onAccent }}>{Math.floor(rest / 60)}:{String(rest % 60).padStart(2, '0')}</T>
            </View>
            <Button title="Пропустить" variant="dark" small onPress={() => setRest(0)} />
          </Card>
        ) : null}

        <Card style={{ gap: 8 }}>
          <View style={{ flexDirection: 'row' }}>
            <T v="label" style={{ width: 60 }}>ПОДХОД</T>
            <T v="label" style={{ flex: 1, textAlign: 'center' }}>{ex.unit === 'sec' ? 'СЕК' : 'ПОВТОРЫ'}</T>
            <T v="label" style={{ flex: 1, textAlign: 'center' }}>ВЕС</T>
            <View style={{ width: 24 }} />
          </View>
          {exLogged.length === 0 ? <T v="small">Подходов пока нет — выбери вес и повторы.</T> : null}
          {exLogged.map((sItem, i) => (
            <View key={i} style={{ flexDirection: 'row', alignItems: 'center', height: 40, borderTopWidth: 1, borderTopColor: colors.border }}>
              <T style={{ width: 60, color: colors.muted }}>{i + 1}</T>
              <T style={{ flex: 1, textAlign: 'center', fontFamily: fonts.bold }}>{sItem.reps}</T>
              <T style={{ flex: 1, textAlign: 'center', fontFamily: fonts.bold }}>{sItem.weight ? `${fmt(sItem.weight)} кг` : '—'}</T>
              <Icon name="check" size={22} color={colors.accent} strokeWidth={2.6} />
            </View>
          ))}
          {ex.prev.length ? <T v="small">Прошлый раз: {ex.prev.map(([w, r]) => (w ? `${fmt(w)}×${r}` : `${r}`)).join(', ')}</T> : null}
          {exLogged.length ? <Button title="Отменить последний подход" variant="ghost" small onPress={undo} /> : null}
        </Card>

        <View style={{ flexDirection: 'row', gap: 8 }}>
          <Button title="← Назад" variant="secondary" small style={{ flex: 1 }} disabled={pos === 0} onPress={() => setPos(pos - 1)} />
          {pos < plan.exercises.length - 1
            ? <Button title="Дальше →" variant="secondary" small style={{ flex: 1 }} onPress={() => { setRest(0); setPos(pos + 1); }} />
            : <Button title="К заминке" small style={{ flex: 1 }} onPress={goCooldown} />}
        </View>
        <Button title="Завершить тренировку" variant="ghost" small onPress={() => (doneSets ? goCooldown() : confirm('Нет записанных подходов', 'Завершить без подходов? Тренировка не сохранится.', finish))} />

        <View style={{ gap: 8 }}>
          <T v="h3">Все упражнения</T>
          {plan.exercises.map((e, i) => {
            const n = (logged[e.id] ?? []).length;
            return (
              <Pressable key={e.id + i} accessibilityRole="button" onPress={() => { setRest(0); setPos(i); }}>
                <View style={{ padding: 14, borderRadius: 20, backgroundColor: colors.surface, borderWidth: 1, borderColor: i === pos ? colors.accent : colors.border, flexDirection: 'row', justifyContent: 'space-between' }}>
                  <T style={{ fontFamily: fonts.bold, fontSize: 14, flex: 1 }} numberOfLines={1}>{e.name}</T>
                  <T v="small" style={{ color: n >= e.sets ? colors.accent : colors.muted }}>{n}/{e.sets}</T>
                </View>
              </Pressable>
            );
          })}
        </View>
      </ScrollView>

      <SwapModal open={swapOpen} onClose={() => setSwapOpen(false)} day={dayIndex} pos={pos} place={place} current={ex} onPick={replace} />
    </SafeAreaView>
  );
}

// ---------- Разминка / заминка ----------

function CardioStage({ phase, place, groups, wid, onDone, busy }: {
  phase: 'warmup' | 'cooldown'; place: string; groups: string; wid: number; onDone: () => void; busy: boolean;
}) {
  const [info, setInfo] = useState<CardioInfo | null>(null);
  const [kind, setKind] = useState<string | null>(null);

  useEffect(() => {
    api<CardioInfo>(`/api/cardio?phase=${phase}&place=${place}&groups=${groups}`).then(setInfo).catch(() => setInfo(null));
  }, [phase, place, groups]);

  if (!info) return <Loading />;
  const machine = info.options.find((o) => o.id === kind);
  const save = async (minutes: number) => {
    if (kind) await api(`/api/workouts/${wid}/cardio`, { body: { phase, kind, minutes } });
    onDone();
  };
  const mins = [...new Set([info.minutes.lo, info.minutes.default, info.minutes.hi])];

  return (
    <>
      <Card style={{ gap: 10, borderRadius: 28 }}>
        <T v="h2">{phase === 'warmup' ? '🔥 Разминка' : '🧊 Заминка'}</T>
        <T v="small" style={{ color: colors.soft }}>
          Кардио {info.minutes.lo}–{info.minutes.hi} мин, пульс ~{info.pulse.lo}–{info.pulse.hi} уд/мин.
          {phase === 'warmup' ? ' Темп лёгкий: можешь свободно говорить.' : ' Спокойный темп, постепенно замедляйся.'}
        </T>
      </Card>

      {machine ? (
        <Card style={{ gap: 12 }}>
          <T v="h3">{machine.name}</T>
          <T v="small">Как: {machine.how}.</T>
          <T v="label">СКОЛЬКО МИНУТ СДЕЛАЛ(А)</T>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            {mins.map((m) => <Chip key={m} label={`${m} мин`} onPress={() => save(m)} />)}
          </View>
          <Button title="Другой тренажёр" variant="ghost" small onPress={() => setKind(null)} />
        </Card>
      ) : (
        <View style={{ gap: 8 }}>
          <T v="h3">Выбери кардио</T>
          {info.options.map((o) => (
            <Pressable key={o.id} accessibilityRole="button" onPress={() => setKind(o.id)}>
              <Card style={{ paddingVertical: 16 }}><T style={{ fontFamily: fonts.bold }}>{o.name}</T></Card>
            </Pressable>
          ))}
        </View>
      )}

      {phase === 'warmup' ? (
        <Card style={{ gap: 6 }}>
          <T v="h3">Суставная гимнастика · 2–3 мин</T>
          {info.joint_warmup.map((j) => <T key={j} v="small">• {j}</T>)}
        </Card>
      ) : (
        <Card style={{ gap: 6 }}>
          <T v="h3">Растяжка · по 20–30 сек</T>
          {info.stretches.map((j) => <T key={j} v="small">• {j}</T>)}
        </Card>
      )}

      <Button title={phase === 'warmup' ? 'Пропустить разминку' : 'Завершить без заминки'} variant="ghost" small loading={busy} onPress={onDone} />
    </>
  );
}

// ---------- Замена упражнения ----------

function SwapModal({ open, onClose, day, pos, place, current, onPick }: {
  open: boolean; onClose: () => void; day: number; pos: number; place: string; current: PlannedExercise; onPick: (e: PlannedExercise) => void;
}) {
  const [alts, setAlts] = useState<PlannedExercise[] | null>(null);
  const [remember, setRemember] = useState(false);

  useEffect(() => {
    if (!open) return;
    setAlts(null);
    api<{ alternatives: PlannedExercise[] }>(`/api/alternatives?day=${day}&pos=${pos}&place=${place}`)
      .then((r) => setAlts(r.alternatives)).catch(() => setAlts([]));
  }, [open, day, pos, place]);

  const pick = async (e: PlannedExercise) => {
    if (remember) await api('/api/swaps', { body: { day, pos, place, exercise_id: e.id } }).catch(() => undefined);
    onPick(e);
  };

  return (
    <Modal visible={open} animationType="slide" transparent onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' }}>
        <View style={{ maxHeight: '80%', backgroundColor: colors.bg, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 20, gap: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <T v="h2" style={{ flex: 1 }}>Чем заменить «{current.name}»?</T>
            <IconButton icon="close" label="Закрыть" onPress={onClose} />
          </View>
          <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: remember }} onPress={() => setRemember(!remember)}
            style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
            <View style={{ width: 24, height: 24, borderRadius: 8, borderWidth: 2, borderColor: colors.accent, backgroundColor: remember ? colors.accent : 'transparent', alignItems: 'center', justifyContent: 'center' }}>
              {remember ? <Icon name="check" size={16} color={colors.onAccent} strokeWidth={3} /> : null}
            </View>
            <T v="small" style={{ color: colors.text }}>Запомнить замену в программе</T>
          </Pressable>
          <ScrollView contentContainerStyle={{ gap: 8, paddingBottom: 20 }}>
            {alts === null ? <T v="small">Загружаем варианты…</T> : null}
            {alts?.length === 0 ? <T v="small">Других вариантов для этой группы мышц здесь нет.</T> : null}
            {alts?.map((a) => (
              <Pressable key={a.id} accessibilityRole="button" onPress={() => pick(a)}>
                <Card style={{ gap: 4 }}>
                  <T style={{ fontFamily: fonts.bold }}>{a.name}</T>
                  <T v="small">{a.equipment.name} · {a.plan_text}</T>
                </Card>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}
