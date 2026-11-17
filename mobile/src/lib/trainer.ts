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
  rating: { value: number | null; count: number };
  profile_listed: boolean;
  requests: TrainerRequest[];
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

export type TrainerCard = {
  id: number;
  name: string;
  rating: number | null;
  reviews: number;
  clients: number;
  has_room: boolean;
  specializations: { key: string; label: string }[];
  experience_years: number | null;
  city: string;
  format: string;
  format_label: string;
  bio: string;
  certificates: string;
  photo_url: string | null;
};

export type TrainerDetail = TrainerCard & {
  reviews_list: { name: string; rating: number; text: string; date: string }[];
  is_my_trainer: boolean;
  has_trainer: boolean;
  my_request: { id: number; status: string } | null;
  can_review: boolean;
  my_review: { rating: number; text: string } | null;
};

export type TrainerProfile = {
  bio: string | null;
  specializations: string[];
  experience_years: number | null;
  certificates: string | null;
  city: string | null;
  format: string | null;
  max_clients: number | null;
  listed: boolean;
  photo_url: string | null;
  specializations_all: Record<string, string>;
  formats: Record<string, string>;
};

export type TrainerRequest = { id: number; name: string; message: string; goal: string; date: string };
