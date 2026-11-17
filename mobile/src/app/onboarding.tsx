import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { Button, Card, ProgressBar, Screen, T } from '../components/ui';
import { api, type Me } from '../lib/api';
import { useAuth } from '../lib/auth';
import { colors, fonts } from '../lib/theme';

type Answers = { gender?: string; age?: string; goal?: string; level?: string; days?: number; place?: string };

const STEPS = ['gender', 'age', 'goal', 'level', 'days', 'place'] as const;

const TITLES: Record<(typeof STEPS)[number], string> = {
  gender: 'Твой пол',
  age: 'Сколько тебе лет?',
  goal: 'Главная цель',
  level: 'Опыт тренировок',
  days: 'Сколько тренировок в неделю?',
  place: 'Где тренируешься?',
};

export default function Onboarding() {
  const { meta, refresh } = useAuth();
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Answers>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  if (!meta) {
    return <Screen><T>Загружаем…</T></Screen>;
  }
  const key = STEPS[step];
  const options: { value: string | number; label: string }[] =
    key === 'days' ? meta.day_options.map((d) => ({ value: d, label: `${d} ${d < 5 ? 'тренировки' : 'тренировок'}` })) :
    Object.entries(
      key === 'gender' ? meta.genders : key === 'age' ? meta.ages : key === 'goal' ? meta.goals :
      key === 'level' ? meta.levels : meta.places,
    ).map(([value, label]) => ({ value, label }));

  const choose = async (value: string | number) => {
    const next = { ...answers, [key]: value };
    setAnswers(next);
    if (step < STEPS.length - 1) {
      setStep(step + 1);
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api<Me>('/api/me/profile', { method: 'PUT', body: next });
      await refresh();
      router.replace('/home');
    } catch {
      setError('Не удалось сохранить анкету. Попробуй ещё раз.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen bottomInset={40}>
      <View style={{ gap: 10, marginTop: 8 }}>
        <T v="label">ШАГ {step + 1} ИЗ {STEPS.length}</T>
        <ProgressBar value={(step + 1) / STEPS.length} />
        <T v="h1" style={{ marginTop: 8 }}>{TITLES[key]}</T>
        {key === 'level' ? <T v="small">Новичкам дадим стартовые веса и период адаптации.</T> : null}
        {key === 'days' && answers.level === 'novice' ? <T v="small">Новичкам рекомендуем 2–3 тренировки — этого достаточно для прогресса.</T> : null}
      </View>
      <View style={{ gap: 10 }}>
        {options.map((o) => (
          <Pressable key={String(o.value)} accessibilityRole="button" onPress={() => choose(o.value)} disabled={busy}
            style={({ pressed }) => ({ opacity: pressed ? 0.85 : 1 })}>
            <Card style={{ paddingVertical: 18 }}>
              <T style={{ fontFamily: fonts.bold, fontSize: 16 }}>{o.label}</T>
            </Card>
          </Pressable>
        ))}
      </View>
      {step > 0 ? <Button title="Назад" variant="ghost" small onPress={() => setStep(step - 1)} /> : null}
      {error ? <T v="small" style={{ color: colors.danger }}>{error}</T> : null}
    </Screen>
  );
}
