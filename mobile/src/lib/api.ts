// Клиент API сервера FitHelper (api.py). Веб-версия ходит на тот же домен,
// мобильная сборка — на адрес из EXPO_PUBLIC_API_URL.
import { Platform } from 'react-native';

export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? (Platform.OS === 'web' ? '' : 'http://localhost:8080')).replace(/\/$/, '');

let token: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setToken(value: string | null) {
  token = value;
}

export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function photoUrl(path: string) {
  return API_URL + path;
}

export async function api<T = any>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(API_URL + path, {
    method: options.method ?? (options.body ? 'POST' : 'GET'),
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 401) {
    onUnauthorized?.();
  }
  if (!res.ok) {
    let message = 'Ошибка сервера';
    try {
      const data = await res.json();
      message = typeof data.detail === 'string' ? data.detail : message;
    } catch {
      // ответ не JSON
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

// ---------- Типы ответов ----------

export type Me = {
  id: number;
  name: string;
  profile_complete: boolean;
  profile: {
    gender: string | null;
    age: string | null;
    goal: string | null;
    level: string | null;
    days: number | null;
    place: string | null;
    cycle_tracking: number | null;
    target_weight: number | null;
    rest_timer: number | null;
  };
  subscription_until: string | null;
  is_trainer: boolean;
  is_admin: boolean;
  trainer: { id: number; name: string } | null;
  version: string;
};

export type Meta = {
  genders: Record<string, string>;
  ages: Record<string, string>;
  goals: Record<string, string>;
  levels: Record<string, string>;
  places: Record<string, string>;
  day_options: number[];
  groups: Record<string, string>;
  group_types: Record<string, string>;
};

export type PlannedExercise = {
  id: string;
  name: string;
  group: string;
  group_name: string;
  places: string[];
  compound: boolean;
  bodyweight: boolean;
  unit: 'reps' | 'sec';
  tip: string;
  equipment: { key: string; name: string; hint: string; steps: number[] };
  start_weight: string;
  role: string;
  sets: number;
  lo: number;
  hi: number;
  rest: number;
  plan_text: string;
  rep_options: number[];
  prev: [number, number][];
  advice: string;
  weight: number;
};

export type DayPlan = { title: string; groups: string[]; note: string; exercises: PlannedExercise[] };

export type Assignment = {
  id: number;
  date: string;
  date_label: string;
  title: string;
  note: string;
  status: string;
  items: { id: string; name: string; sets: number; lo: number; hi: number; weight: number | null; unit: string }[];
};

export type WeekDay = { label: string; date: string; done: boolean; today: boolean };

export type Today = {
  day_index: number;
  days: number;
  place: string;
  default_place: string;
  plan: DayPlan;
  notes: string[];
  light_day: boolean;
  cycle: { day: number; length: number; phase: string; phase_name: string; tip: string; days_left: number } | null;
  program_days: string[];
  week: { done: number; plan: number; strip: WeekDay[] };
  streak: number;
  assignments: Assignment[];
};

export type CardioInfo = {
  phase: 'warmup' | 'cooldown';
  minutes: { lo: number; hi: number; default: number };
  pulse: { lo: number; hi: number };
  options: { id: string; name: string; how: string }[];
  joint_warmup: string[];
  stretches: string[];
};

export type Progress = {
  total: number;
  month: number;
  week: number;
  plan: number;
  streak: number;
  tonnage_month: number;
  cardio_week: number;
  groups_month: { count: number; minutes: number };
  records: { id: string; name: string; text: string; date: string; e1rm: number | null }[];
  body_weight: { date: string; weight: number }[];
  target_weight: number | null;
  week_strip: WeekDay[];
};

export type Exercise = PlannedExercise & {
  frames: number;
  technique: { secondary: string; setup: string; steps: string[]; breath: string; mistakes: string[] };
  photos: { n: number; caption: string; url: string | null }[];
};

export type Coach = {
  trainer: { id: number; name: string; rating: number | null; photo_url: string | null } | null;
  can_review?: boolean;
  my_review?: { rating: number; text: string } | null;
  pending: { id: number; trainer_id: number; trainer_name: string }[];
  assignments: Assignment[];
  done: Assignment[];
  messages: { mine: boolean; text: string; at: string }[];
};

export type HistoryItem = {
  id: number;
  title: string;
  date: string;
  kind: string;
  minutes: number;
  exercises: { name: string; sets: string[] }[];
  cardio: string[];
};
