// Типы ответов API кабинета тренера.
import type { Assignment } from './api';

export type TrainerHome = {
  level: { name: string; percent: number; description: string };
  next: { name: string; percent: number; left: number; progress: number } | null;
  subscribers: number;
  invited: number;
  income: number | null;
  levels: { name: string; from: number; percent: number; description: string }[];
  links: { code: string; label: string; joined: number; subs: number; url: string }[];
  clients: { id: number; name: string; week: number; plan: number; goal: string; subscription: boolean; pending: number }[];
};

export type ClientCard = {
  id: number;
  name: string;
  subscription_until: string | null;
  profile: { gender: string; age: string; goal: string; level: string; days: number; place: string } | null;
  labels: { gender: string; age: string; goal: string; level: string; place: string } | null;
  week: number;
  month: number;
  groups_month: number;
  cardio_week: number;
  last: { title: string; date: string } | null;
  records: { name: string; text: string; date: string }[];
  body_weight: { date: string; weight: number }[];
  assignments: Assignment[];
  messages: { mine: boolean; text: string; at: string }[];
  program_days: string[];
};

export type CatalogExercise = {
  id: string; name: string; group: string; places: string[]; unit: 'reps' | 'sec'; bodyweight: boolean; equipment: string;
};

export type Catalog = { groups: Record<string, string>; exercises: CatalogExercise[] };

export type BuilderItem = { ex: string; sets: number; lo: number; hi: number; w: number | null };
