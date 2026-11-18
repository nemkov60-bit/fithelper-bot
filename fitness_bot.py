"""Фитнес-бот для Telegram: программа тренировок, дневник подходов, цели и прогресс.

Запуск:
    pip install -r fitness_bot/requirements.txt
    FITNESS_BOT_TOKEN=123:ABC python fitness_bot/fitness_bot.py

Токен можно положить в файл .env рядом с ботом (FITNESS_BOT_TOKEN=...).
"""
import asyncio
import html
import json
import logging
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup,
                      Update)
from telegram.constants import ParseMode
from telegram.error import Conflict
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, PicklePersistence, filters)

try:
    from exercise_images import EXERCISE_FRAMES, build_prompt
    from exercise_images_ru import build_prompt_ru
    from exercise_technique import TECHNIQUE
    from warmup import (CARDIO, JOINT_WARMUP, STRETCHES, cardio_minutes, cardio_options, pulse_range)
except ImportError:  # pragma: no cover
    from fitness_bot.exercise_images import EXERCISE_FRAMES, build_prompt
    from fitness_bot.exercise_images_ru import build_prompt_ru
    from fitness_bot.exercise_technique import TECHNIQUE
    from fitness_bot.warmup import (CARDIO, JOINT_WARMUP, STRETCHES, cardio_minutes, cardio_options,
                                    pulse_range)

ROOT = Path(__file__).resolve().parent
IMAGES_DIR = Path(os.environ.get('FITNESS_IMAGES', ROOT / 'images'))
if load_dotenv:
    load_dotenv(ROOT / '.env')

# Все данные бота — в одной папке (на хостинге её можно вынести на постоянный диск через FITNESS_DATA_DIR).
DATA_DIR = Path(os.environ.get('FITNESS_DATA_DIR', ROOT / 'data'))
DB_PATH = Path(os.environ.get('FITNESS_DB', DATA_DIR / 'fitness.db'))
STATE_PATH = Path(os.environ.get('FITNESS_STATE', DATA_DIR / 'fitness_state.pickle'))


def admin_ids():
    """ID администраторов из ADMIN_ID (можно несколько через запятую)."""
    ids = set()
    for part in re.split(r'[,;\s]+', os.environ.get('ADMIN_ID') or ''):
        if part.strip().isdigit():
            ids.add(int(part))
    return ids


def is_admin(uid):
    return uid in admin_ids()


TZ_NAME = os.environ.get('FITNESS_TZ', 'Europe/Moscow')

log = logging.getLogger('fitness_bot')

# Версия кода: видна в «🛠 Админ» и в логах запуска — по ней видно, обновился ли бот на хостинге.
BOT_VERSION = '2026-11-17 · шрифты, фото, объёмы, чат'


def now():
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(TZ_NAME)).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.now()


# ======================================================================
# Справочник упражнений
# ======================================================================

GROUPS = {
    'chest': 'Грудь', 'back': 'Спина', 'shoulders': 'Плечи', 'quads': 'Квадрицепс',
    'hams': 'Бицепс бедра', 'glutes': 'Ягодицы', 'biceps': 'Бицепс', 'triceps': 'Трицепс',
    'calves': 'Икры', 'core': 'Пресс',
}

GYM, HOME = 'gym', 'home'


@dataclass(frozen=True)
class Exercise:
    id: str
    name: str
    group: str
    places: tuple
    compound: bool = False
    bodyweight: bool = False
    unit: str = 'reps'  # reps | sec
    tip: str = ''
    auto: bool = True  # False — только для замены, в автоматическую программу не попадает


def _ex(id, name, group, places, compound=False, bodyweight=False, unit='reps', tip='', auto=True):
    return Exercise(id, name, group, tuple(places), compound, bodyweight, unit, tip, auto)


_EXERCISE_LIST = [
    # Грудь
    _ex('bench', 'Жим штанги лёжа', 'chest', [GYM], True, tip='Лопатки сведены, гриф опускается на низ груди.'),
    _ex('incline_db', 'Жим гантелей на наклонной скамье', 'chest', [GYM], True, tip='Угол скамьи 30°, локти под 45° к корпусу.'),
    _ex('db_fly', 'Разведение гантелей лёжа', 'chest', [GYM], tip='Локти слегка согнуты, растягивай грудь без боли в плечах.'),
    _ex('cable_cross', 'Сведение рук в кроссовере', 'chest', [GYM], tip='Своди руки перед собой, задержись на секунду.'),
    _ex('pushup', 'Отжимания от пола', 'chest', [HOME], True, True, tip='Тело — прямая линия, грудь касается пола.'),
    _ex('pushup_knee', 'Отжимания с колен', 'chest', [HOME], True, True, tip='Колени на коврике, корпус от коленей до головы — прямая.'),
    _ex('pushup_decline', 'Отжимания с ногами на опоре', 'chest', [HOME], True, True, tip='Ноги на стуле, корпус не прогибай.'),
    _ex('pushup_wide', 'Отжимания с широкой постановкой рук', 'chest', [HOME], bodyweight=True, tip='Медленно вниз за 2–3 секунды.'),
    # Спина
    _ex('pullup', 'Подтягивания', 'back', [GYM, HOME], True, True, tip='Тянись грудью к перекладине, без раскачки.'),
    _ex('lat_pulldown', 'Тяга верхнего блока к груди', 'back', [GYM], True, tip='Своди лопатки, не отклоняйся сильно назад.'),
    _ex('row_bb', 'Тяга штанги в наклоне', 'back', [GYM], True, tip='Спина прямая, тяни гриф к поясу.'),
    _ex('row_db', 'Тяга гантели одной рукой', 'back', [GYM], True, tip='Локоть идёт вдоль корпуса к бедру.'),
    _ex('seated_row', 'Тяга горизонтального блока', 'back', [GYM], tip='Грудь вперёд, в конце сведи лопатки.'),
    _ex('inverted_row', 'Австралийские подтягивания (под столом)', 'back', [HOME], True, True, tip='Тело прямое, касайся грудью края стола.'),
    _ex('backpack_row', 'Тяга рюкзака в наклоне', 'back', [HOME], True, tip='Спина прямая, тяни рюкзак к поясу, своди лопатки.'),
    _ex('superman', 'Супермен (лёжа на животе)', 'back', [HOME], bodyweight=True, tip='Подними руки и ноги, задержись на 2 секунды.'),
    # Плечи
    _ex('ohp', 'Жим штанги стоя', 'shoulders', [GYM], True, tip='Ягодицы и пресс напряжены, гриф над серединой стопы.'),
    _ex('db_press', 'Жим гантелей сидя', 'shoulders', [GYM], True, tip='Не сводь гантели вверху до удара.'),
    _ex('lat_raise', 'Махи гантелями в стороны', 'shoulders', [GYM], tip='Поднимай до уровня плеч, без рывков.'),
    _ex('rear_delt', 'Разведение в наклоне (задняя дельта)', 'shoulders', [GYM], tip='Лёгкий вес, работают задние дельты, а не спина.'),
    _ex('pike_pushup', 'Отжимания «уголком» (pike)', 'shoulders', [HOME], True, True, tip='Таз высоко, опускай голову между ладоней.'),
    _ex('backpack_press', 'Жим рюкзака или бутылок над головой', 'shoulders', [HOME], True, tip='Пресс напряжён, не прогибай поясницу.'),
    _ex('y_raise', 'Подъёмы рук буквой «Y» лёжа на животе', 'shoulders', [HOME], bodyweight=True, tip='Большие пальцы вверх, лопатки вниз.'),
    # Квадрицепс
    _ex('squat', 'Приседания со штангой', 'quads', [GYM], True, tip='Колени по направлению носков, глубина — до параллели и ниже.'),
    _ex('leg_press', 'Жим ногами', 'quads', [GYM], True, tip='Поясница прижата, колени не замыкай.'),
    _ex('lunge_db', 'Выпады с гантелями', 'quads', [GYM], True, tip='Шаг широкий, заднее колено почти касается пола.'),
    _ex('leg_ext', 'Разгибания ног в тренажёре', 'quads', [GYM], tip='Пауза в верхней точке на 1 секунду.'),
    _ex('bw_squat', 'Приседания', 'quads', [HOME], True, True, tip='Пятки на полу, спина прямая.'),
    _ex('split_squat', 'Болгарские сплит-приседания', 'quads', [HOME], True, True, tip='Задняя нога на стуле, корпус чуть вперёд.'),
    _ex('lunges', 'Выпады', 'quads', [HOME], True, True, tip='Чередуй ноги, держи равновесие.'),
    _ex('wall_sit', 'Стульчик у стены', 'quads', [HOME], bodyweight=True, unit='sec', tip='Бёдра параллельно полу.'),
    # Бицепс бедра
    _ex('rdl', 'Румынская тяга', 'hams', [GYM], True, tip='Таз назад, гриф скользит по ногам, спина прямая.'),
    _ex('deadlift', 'Становая тяга', 'hams', [GYM], True, tip='Гриф над серединой стопы, тяни ногами.'),
    _ex('leg_curl', 'Сгибания ног в тренажёре', 'hams', [GYM], tip='Медленно опускай, не отрывай таз.'),
    _ex('sl_rdl', 'Румынская тяга на одной ноге', 'hams', [HOME], True, True, tip='Корпус и свободная нога — одна линия.'),
    _ex('slider_curl', 'Сгибания ног лёжа (пятки по полу на полотенце)', 'hams', [HOME], bodyweight=True, tip='Таз поднят, подтягивай пятки к себе.'),
    # Ягодицы
    _ex('hip_thrust', 'Ягодичный мост со штангой', 'glutes', [GYM], True, tip='Подбородок к груди, вверху сожми ягодицы.'),
    _ex('cable_kickback', 'Отведение ноги в кроссовере', 'glutes', [GYM], tip='Корпус неподвижен, работает только ягодица.'),
    _ex('glute_bridge', 'Ягодичный мостик', 'glutes', [HOME], True, True, tip='Пауза 2 секунды в верхней точке.'),
    _ex('sl_bridge', 'Ягодичный мостик на одной ноге', 'glutes', [HOME], bodyweight=True, tip='Таз не перекашивай.'),
    # Бицепс
    _ex('bb_curl', 'Подъём штанги на бицепс', 'biceps', [GYM], tip='Локти прижаты, без раскачки корпусом.'),
    _ex('hammer', 'Молотки с гантелями', 'biceps', [GYM], tip='Ладони смотрят друг на друга.'),
    _ex('chinup', 'Подтягивания обратным хватом', 'biceps', [HOME], True, True, tip='Ладони к себе, медленно вниз.'),
    _ex('backpack_curl', 'Сгибания рук с рюкзаком или бутылками', 'biceps', [HOME], tip='Локти прижаты к корпусу, поднимай без рывков.'),
    _ex('towel_curl', 'Сгибание руки с полотенцем (изометрия)', 'biceps', [HOME], bodyweight=True, unit='sec', tip='Наступи на полотенце и тяни изо всех сил.'),
    # Трицепс
    _ex('pushdown', 'Разгибания рук на блоке', 'triceps', [GYM], tip='Локти прижаты, полностью выпрямляй руки.'),
    _ex('french', 'Французский жим', 'triceps', [GYM], tip='Локти смотрят вверх, не разводи их.'),
    _ex('dips', 'Отжимания на брусьях', 'triceps', [GYM], True, True, tip='Корпус вертикально — акцент на трицепс.'),
    _ex('bench_dips', 'Обратные отжимания от стула', 'triceps', [HOME], bodyweight=True, tip='Спина близко к стулу, плечи не поднимай.'),
    _ex('bottle_ext', 'Разгибание рук с бутылкой из-за головы', 'triceps', [HOME], tip='Локти смотрят вверх и не расходятся.'),
    _ex('diamond', 'Алмазные отжимания', 'triceps', [HOME], True, True, tip='Ладони вместе под грудью, локти вдоль корпуса.'),
    # Икры
    _ex('calf_machine', 'Подъёмы на носки в тренажёре', 'calves', [GYM], tip='Полная амплитуда, пауза вверху.'),
    _ex('calf_single', 'Подъёмы на носки на одной ноге', 'calves', [HOME], bodyweight=True, tip='Стой на краю ступеньки, опускай пятку ниже.'),
    # Пресс
    _ex('hanging_leg', 'Подъёмы ног в висе', 'core', [GYM], bodyweight=True, tip='Без раскачки, подкручивай таз.'),
    _ex('cable_crunch', 'Скручивания на блоке', 'core', [GYM], tip='Скручивайся позвоночником, а не руками.'),
    _ex('plank', 'Планка', 'core', [GYM, HOME], bodyweight=True, unit='sec', tip='Таз не проваливай, дыши ровно.'),
    _ex('crunch', 'Скручивания', 'core', [HOME], bodyweight=True, tip='Поясница прижата к полу.'),
    _ex('dead_bug', 'Мёртвый жук', 'core', [HOME], bodyweight=True, tip='Поясница прижата, двигайся медленно.'),
]

try:
    from extra_exercises import EXTRA as EXTRA_EXERCISES
except ImportError:  # pragma: no cover
    from fitness_bot.extra_exercises import EXTRA as EXTRA_EXERCISES
_EXERCISE_LIST += [_ex(d['id'], d['name'], d['group'], d['places'], d['compound'], d['bodyweight'], d['unit'],
                       d['tip'], auto=False) for d in EXTRA_EXERCISES]

EXERCISES = {e.id: e for e in _EXERCISE_LIST}



# Стартовые веса для новичков: (мужчины, женщины).
START_WEIGHTS = {
    'bench': ('20 кг (пустой гриф)', '10–20 кг (лёгкий или пустой гриф)'),
    'incline_db': ('гантели по 8–10 кг', 'гантели по 3–5 кг'),
    'db_fly': ('гантели по 5–6 кг', 'гантели по 2–3 кг'),
    'cable_cross': ('5–10 кг на блоке', '2.5–5 кг на блоке'),
    'lat_pulldown': ('30–35 кг', '15–25 кг'),
    'row_bb': ('20–30 кг', '15–20 кг'),
    'row_db': ('гантель 10–12 кг', 'гантель 5–7 кг'),
    'seated_row': ('30–35 кг', '15–25 кг'),
    'ohp': ('20 кг (пустой гриф)', '10–15 кг (лёгкий гриф)'),
    'db_press': ('гантели по 6–8 кг', 'гантели по 3–4 кг'),
    'lat_raise': ('гантели по 3–5 кг', 'гантели по 1–2 кг'),
    'rear_delt': ('гантели по 3–5 кг', 'гантели по 1–2 кг'),
    'squat': ('20 кг (пустой гриф)', '15–20 кг (гриф)'),
    'leg_press': ('40–60 кг', '20–40 кг'),
    'lunge_db': ('гантели по 6–8 кг', 'гантели по 2–4 кг'),
    'leg_ext': ('15–25 кг', '10–15 кг'),
    'rdl': ('20–30 кг', '15–20 кг'),
    'deadlift': ('30–40 кг', '20–30 кг'),
    'leg_curl': ('15–25 кг', '10–15 кг'),
    'hip_thrust': ('20–40 кг', '20–30 кг'),
    'cable_kickback': ('5 кг', '2.5–5 кг'),
    'bb_curl': ('15–20 кг', '7–10 кг'),
    'hammer': ('гантели по 6–8 кг', 'гантели по 3–4 кг'),
    'pushdown': ('15–20 кг', '7–10 кг'),
    'french': ('15–20 кг (EZ-гриф)', '7–10 кг'),
    'calf_machine': ('30–40 кг', '20–30 кг'),
    'cable_crunch': ('20–25 кг', '10–15 кг'),
    'backpack_curl': ('рюкзак 5–8 кг', 'бутылки по 1.5 л или рюкзак 3–4 кг'),
    'backpack_row': ('рюкзак 8–10 кг', 'рюкзак 4–6 кг'),
    'backpack_press': ('рюкзак 5–8 кг', 'бутылки по 1.5 л'),
    'bottle_ext': ('бутылка 5 л', 'бутылка 1.5–2 л'),
}


START_WEIGHTS.update({d['id']: d['start'] for d in EXTRA_EXERCISES if d['start']})


def start_weight(ex, user):
    pair = START_WEIGHTS.get(ex.id)
    if not pair:
        return ''
    text = pair[1] if user.get('gender') == 'f' else pair[0]
    if age_group(user.get('age')) in ('teen', 'senior'):
        text += ', начни с нижней границы'
    return text


# ======================================================================
# Программа тренировок
# ======================================================================

GENDERS = {'m': '👨 Мужской', 'f': '👩 Женский'}
AGES = {'teen': '14–17', '18': '18–29', '30': '30–39', '40': '40–49', '50': '50–59', '60': '60+'}
GOALS = {
    'mass': '💪 Набор мышечной массы',
    'strength': '🏋️ Сила',
    'fat_loss': '🔥 Похудение / рельеф',
    'fit': '🧘 Тонус и здоровье',
}
LEVELS = {'novice': '🌱 Новичок: впервые или до 6 мес.', 'mid': '📈 Средний: 6 мес. – 2 года', 'pro': '🏆 Опытный: 2+ года'}
PLACES = {GYM: '🏢 Тренажёрный зал', HOME: '🏠 Дома (свой вес, желателен турник)'}
DAY_OPTIONS = (2, 3, 4, 5)

# (подходы, мин. повторы, макс. повторы, отдых в секундах)
GOAL_PARAMS = {
    'strength': {'main': (4, 3, 6, 180), 'acc': (3, 6, 10, 120)},
    'mass': {'main': (4, 6, 10, 120), 'acc': (3, 10, 12, 75)},
    'fat_loss': {'main': (3, 10, 12, 60), 'acc': (3, 12, 15, 45)},
    'fit': {'main': (3, 8, 12, 90), 'acc': (3, 10, 15, 60)},
}
# Для упражнений с собственным весом диапазоны повторов шире.
BODYWEIGHT_REPS = {'strength': (5, 10), 'mass': (8, 15), 'fat_loss': (12, 20), 'fit': (10, 15)}
SECONDS_RANGE = (30, 60)

DAY_TEMPLATES = {
    'full': ('Всё тело', [('quads', 'main'), ('chest', 'main'), ('back', 'main'), ('hams', 'main'),
                          ('shoulders', 'acc'), ('core', 'acc')]),
    'push': ('Жимовой день: грудь, плечи, трицепс', [('chest', 'main'), ('shoulders', 'main'), ('chest', 'acc'),
                                                      ('shoulders', 'acc'), ('triceps', 'acc'), ('triceps', 'acc')]),
    'pull': ('Тяговый день: спина, бицепс', [('back', 'main'), ('back', 'main'), ('back', 'acc'),
                                              ('biceps', 'acc'), ('biceps', 'acc'), ('core', 'acc')]),
    'legs': ('Ноги', [('quads', 'main'), ('hams', 'main'), ('glutes', 'main'), ('quads', 'acc'),
                      ('calves', 'acc'), ('core', 'acc')]),
    'upper': ('Верх тела', [('chest', 'main'), ('back', 'main'), ('shoulders', 'main'), ('back', 'acc'),
                            ('biceps', 'acc'), ('triceps', 'acc')]),
    'lower': ('Низ тела', [('quads', 'main'), ('hams', 'main'), ('glutes', 'main'), ('quads', 'acc'),
                           ('calves', 'acc'), ('core', 'acc')]),
}
# Для женщин — больше работы на ноги и ягодицы (частый запрос), без потери баланса.
FEMALE_SLOT_SWAPS = {
    'full': {('shoulders', 'acc'): ('glutes', 'main')},
    'legs': {('calves', 'acc'): ('glutes', 'acc')},
    'lower': {('calves', 'acc'): ('glutes', 'acc')},
}

# Упражнения, которые убираем из готовой программы по возрасту и уровню.
EXCLUDE_BY_AGE = {
    'teen': {'deadlift'},
    'senior': {'deadlift', 'row_bb', 'ohp', 'squat', 'hanging_leg', 'dips', 'pullup', 'chinup',
               'pike_pushup', 'diamond'},
}
EXCLUDE_NOVICE = {'pullup', 'chinup', 'dips', 'deadlift', 'hanging_leg'}


def age_group(age):
    if age == 'teen':
        return 'teen'
    if age in ('40', '50'):
        return 'mature'
    if age == '60':
        return 'senior'
    return 'adult'


@dataclass(frozen=True)
class Prescription:
    sets: int
    lo: int
    hi: int
    rest: int
    unit: str = 'reps'

    def text(self):
        unit = ' сек' if self.unit == 'sec' else ''
        return f'{self.sets}×{self.lo}–{self.hi}{unit}, отдых {fmt_rest(self.rest)}'


@dataclass(frozen=True)
class PlannedExercise:
    exercise: Exercise
    role: str
    presc: Prescription


@dataclass(frozen=True)
class WorkoutDay:
    title: str
    exercises: tuple
    note: str

    @property
    def groups(self):
        seen = []
        for p in self.exercises:
            g = GROUPS[p.exercise.group]
            if g not in seen:
                seen.append(g)
        return seen


def split_for(days, level):
    """Список (шаблон, вариант) для заданного числа тренировок в неделю."""
    if days <= 2:
        return [('full', 0), ('full', 1)]
    if days == 3:
        if level == 'novice':
            return [('full', 0), ('full', 1), ('full', 2)]
        return [('push', 0), ('pull', 0), ('legs', 0)]
    if days == 4:
        return [('upper', 0), ('lower', 0), ('upper', 1), ('lower', 1)]
    return [('push', 0), ('pull', 0), ('legs', 0), ('upper', 1), ('lower', 1)]


def prescription(ex, role, goal, level, age='30'):
    if goal == 'strength' and age_group(age) in ('teen', 'senior'):
        goal = 'fit'  # силовой режим с околомаксимальными весами — не для подростков и 60+
    sets, lo, hi, rest = GOAL_PARAMS[goal][role]
    if level == 'novice':
        sets = max(2, sets - 1)
    elif level == 'pro' and role == 'main':
        sets += 1
    ag = age_group(age)
    if ex.unit == 'sec':
        lo, hi = SECONDS_RANGE
        rest = min(rest, 60)
    elif ex.bodyweight:
        lo, hi = BODYWEIGHT_REPS[goal]
    if ex.unit == 'reps':
        if ag in ('teen', 'senior'):
            # Без околомаксимальных весов: минимум 8 повторов в подходе.
            lo = max(lo, 8)
            hi = max(hi, lo + 4)
        elif ag == 'mature':
            lo = max(lo, 5)
            hi = max(hi, lo + 3)
    if ag == 'senior':
        sets = min(sets, 3)
        rest += 30
    elif ag == 'mature':
        rest += 15
    return Prescription(sets, lo, hi, rest, ex.unit)


def _pick(group, role, place, used, variant, excluded=frozenset()):
    base = [e for e in _EXERCISE_LIST if e.group == group and place in e.places and e.auto]
    allowed = [e for e in base if e.id not in excluded] or base
    pool = [e for e in allowed if e.id not in used] or allowed
    if role == 'main':
        candidates = [e for e in pool if e.compound] or pool
    else:
        candidates = [e for e in pool if not e.compound] + [e for e in pool if e.compound]
    return candidates[variant % len(candidates)]


def excluded_for(level, age, gender, place):
    excluded = set(EXCLUDE_BY_AGE.get(age_group(age), ()))
    if level == 'novice':
        excluded |= EXCLUDE_NOVICE
        if gender == 'f' and place == HOME:
            excluded.add('pushup')  # стартуем с отжиманий с колен
    if not (level == 'novice' and gender == 'f'):
        excluded.add('pushup_knee')
    return excluded


def day_note(goal, age):
    ag = age_group(age)
    warmup = 'Разминка 10–15 мин: суставная гимнастика и лёгкое кардио.' if ag in ('mature', 'senior') \
        else 'Разминка 5–10 мин: суставная гимнастика и лёгкое кардио.'
    if goal == 'fat_loss':
        return warmup + ' В конце — 15–20 мин кардио в спокойном темпе (быстрая ходьба, велотренажёр).'
    if goal == 'strength':
        return warmup + ' Перед первым упражнением — 2–3 разминочных подхода с лёгким весом.'
    return warmup


def build_program(goal, level, days, place, gender='m', age='30'):
    split = split_for(days, level)
    letters = 'ABC'
    multi = {t for t, _ in split if sum(1 for x, _ in split if x == t) > 1}
    excluded = excluded_for(level, age, gender, place)
    program = []
    for template, variant in split:
        title, slots = DAY_TEMPLATES[template]
        if gender == 'f':
            swaps = FEMALE_SLOT_SWAPS.get(template, {})
            slots = [swaps.get(slot, slot) for slot in slots]
        if template in multi:
            title = f'{title} {letters[variant]}'
        used = set()
        planned = []
        for group, role in slots:
            ex = _pick(group, role, place, used, variant, excluded)
            used.add(ex.id)
            planned.append(PlannedExercise(ex, role, prescription(ex, role, goal, level, age)))
        program.append(WorkoutDay(title, tuple(planned), day_note(goal, age)))
    return program


def base_program(user, place=None):
    """Программа по анкете, без замен пользователя."""
    return build_program(user['goal'], user['level'], user['days'], place or user['place'],
                         user.get('gender') or 'm', user.get('age') or '30')


def user_program(user, place=None, extra_swaps=None):
    """Программа пользователя с его заменами. place — место на сегодня (зал/дом), по умолчанию — из анкеты."""
    place = place or user['place']
    swaps = {**get_swaps(user.get('user_id'), place), **(extra_swaps or {})}
    return [apply_swaps(day, swaps, user, place) for day in base_program(user, place)]


def apply_swaps(day, swaps, user, place):
    """Заменяет упражнения дня: swaps = {id упражнения из программы: id замены}."""
    if not swaps:
        return day
    planned = list(day.exercises)
    for i, p in enumerate(planned):
        new_id = swaps.get(p.exercise.id)
        ex = EXERCISES.get(new_id)
        if not ex or new_id == p.exercise.id or place not in ex.places:
            continue
        if any(q.exercise.id == new_id for j, q in enumerate(planned) if j != i):
            continue
        presc = prescription(ex, p.role, user['goal'], user['level'], user.get('age') or '30')
        planned[i] = PlannedExercise(ex, p.role, presc)
    return WorkoutDay(day.title, tuple(planned), day.note)


def profile_complete(user):
    return bool(user and user.get('gender') and user.get('age') and user.get('goal'))


# ======================================================================
# Менструальный цикл
# ======================================================================

# ключ: (эмодзи, название, изменение подходов, доп. отдых, без прибавки веса, совет)
PHASES = {
    'menstrual': ('🩸', 'Менструация', -1, 30, True,
                  'Облегчённая тренировка: на 1 подход меньше, отдых дольше, веса не повышаем. '
                  'При сильной боли или слабости лучше заменить тренировку прогулкой или растяжкой.'),
    'follicular': ('🌱', 'Фолликулярная фаза', 0, 0, False,
                   'Энергии обычно больше — хорошее время пробовать новые веса и ставить рекорды.'),
    'ovulation': ('✨', 'Овуляция', 0, 0, False,
                  'Сила часто на пике. Тщательно разминайся и следи за коленями в приседаниях и выпадах.'),
    'luteal': ('🍂', 'Лютеиновая фаза', 0, 0, False,
               'Тренируйся в обычном режиме. Пей больше воды, аппетит может расти — это нормально.'),
    'pms': ('🌙', 'Перед менструацией', 0, 15, False,
            'Энергии может быть меньше, сон хуже. Держи рабочие веса, отдыхай чуть дольше, не гонись за рекордами.'),
}


def cycle_info(user, today=None):
    """Текущий день и фаза цикла. None — если цикл не отслеживается."""
    if not user or user.get('gender') != 'f' or not user.get('cycle_tracking') or not user.get('period_start'):
        return None
    today = today or now().date()
    start = date.fromisoformat(user['period_start'])
    length = int(user.get('cycle_len') or 28)
    period = int(user.get('period_len') or 5)
    delta = (today - start).days
    if delta < 0:
        return None
    day = delta % length + 1
    ovulation = length - 14
    if day <= period:
        phase = 'menstrual'
    elif day < ovulation - 1:
        phase = 'follicular'
    elif day <= ovulation + 1:
        phase = 'ovulation'
    elif day > length - 5:
        phase = 'pms'
    else:
        phase = 'luteal'
    next_start = start + timedelta(days=(delta // length + 1) * length)
    return {'day': day, 'length': length, 'phase': phase, 'next_start': next_start,
            'days_left': (next_start - today).days, 'stale': delta >= length + 7}


def cycle_text(info):
    emoji, name, _, _, _, tip = PHASES[info['phase']]
    text = (f'{emoji} День цикла {info["day"]} из {info["length"]} — {name}.\n{tip}')
    if info['stale']:
        text += '\nПохоже, данные устарели — отметь начало месячных в разделе «🌸 Цикл».'
    return text


def today_mods(user, finished_count=None, standard=False):
    """Поправки к программе на сегодня: адаптация новичка и фаза цикла."""
    mods = {'sets': 0, 'rest': 0, 'no_progress': False, 'notes': []}
    if finished_count is None:
        finished_count = len(finished_workouts(user['user_id'], kind='strength'))
    if user['level'] == 'novice' and finished_count < 2 * user['days']:
        mods['sets'] -= 1
        mods['notes'].append(
            f'🌱 Период адаптации (тренировка {finished_count + 1} из {2 * user["days"]}): '
            'на подход меньше, веса лёгкие, оставляй 3–4 повтора в запасе. Главное сейчас — техника.')
    info = cycle_info(user)
    if info:
        _, _, sets, rest, no_progress, _ = PHASES[info['phase']]
        if not standard:
            mods['sets'] += sets
            mods['rest'] += rest
            mods['no_progress'] = no_progress
        mods['notes'].append(cycle_text(info) if not standard
                             else f'{PHASES[info["phase"]][0]} День цикла {info["day"]}: обычная тренировка по самочувствию.')
    return mods


def apply_mods(day, mods):
    if not mods or (not mods['sets'] and not mods['rest']):
        return day
    planned = []
    for p in day.exercises:
        pr = p.presc
        new = Prescription(max(2, pr.sets + mods['sets']), pr.lo, pr.hi, pr.rest + mods['rest'], pr.unit)
        planned.append(PlannedExercise(p.exercise, p.role, new))
    return WorkoutDay(day.title, tuple(planned), day.note)


def plan_day(user, day_index, mods=None, place=None, extra_swaps=None):
    program = user_program(user, place, extra_swaps)
    return apply_mods(program[day_index % len(program)], mods)


def place_today(user, user_data):
    """Где тренируемся сегодня: выбор «только на сегодня» или место из анкеты."""
    choice = (user_data or {}).get('place_today') or {}
    if choice.get('date') == now().date().isoformat() and choice.get('place') in PLACES:
        return choice['place']
    return user['place']


def parse_date(text, today=None):
    """«12.03», «12.03.2026», «12/3» → date (не в будущем и не старше 90 дней)."""
    today = today or now().date()
    m = re.fullmatch(r'\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\s*', text or '')
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
    year = int(y) + (2000 if y and len(y) == 2 else 0) if y else today.year
    try:
        result = date(year, mo, d)
    except ValueError:
        return None
    if not y and result > today:
        try:
            result = date(year - 1, mo, d)
        except ValueError:
            return None
    if result > today or (today - result).days > 90:
        return None
    return result


# ======================================================================
# Форматирование и расчёты
# ======================================================================

def fmt_rest(sec):
    if sec >= 60 and sec % 60 == 0:
        return f'{sec // 60} мин'
    if sec > 60:
        return f'{sec // 60} мин {sec % 60} сек'
    return f'{sec} сек'


def fmt_w(w):
    w = round(float(w), 2)
    return str(int(w)) if w == int(w) else f'{w:g}'


def fmt_set(weight, reps, unit='reps'):
    tail = f'{reps} сек' if unit == 'sec' else str(reps)
    if weight:
        return f'{fmt_w(weight)} кг × {tail}'
    return tail if unit == 'sec' else f'{tail} повт.'


def parse_set(text):
    """«80 8», «80x8», «62,5×10», «12» → (вес, повторы). None — если не распознано."""
    t = (text or '').strip().lower().replace(',', '.')
    t = re.sub(r'(кг|kg|раз|повт\w*|сек\w*)', ' ', t)
    if not re.fullmatch(r'[\d.\sxх×*+/-]+', t):
        return None
    nums = re.findall(r'\d+(?:\.\d+)?', t)
    if len(nums) == 1:
        weight, reps = 0.0, nums[0]
    elif len(nums) == 2:
        weight, reps = float(nums[0]), nums[1]
    else:
        return None
    if '.' in reps:
        return None
    reps = int(reps)
    if not (0 < reps <= 600) or not (0 <= weight <= 1000):
        return None
    return weight, reps


def parse_weight(text):
    t = (text or '').strip().lower().replace(',', '.').replace('кг', '').replace('kg', '').strip()
    try:
        w = float(t)
    except ValueError:
        return None
    return w if 20 <= w <= 400 else None


def e1rm(weight, reps):
    """Оценка разового максимума по формуле Эпли (для упражнений без веса — повторы)."""
    if not weight:
        return float(reps)
    return weight * (1 + reps / 30) if reps > 1 else float(weight)


def weight_step(ex, gender='m'):
    big = ex.group in ('quads', 'hams', 'glutes') and ex.compound
    if gender == 'f':
        return 2.5 if big else 1.25
    return 5 if big else 2.5


def advice(ex, presc, prev_sets, gender='m', no_progress=False, start_hint=''):
    """Совет по прогрессии нагрузки на основе прошлой тренировки."""
    if no_progress:
        if prev_sets and max(w for w, _ in prev_sets):
            work_w = max(w for w, _ in prev_sets)
            return (f'Сегодня без прибавки: {fmt_w(work_w)} кг или на 10–20% легче, если тяжело. '
                    'Ориентируйся на самочувствие.')
        return 'Сегодня лёгкий режим: работай комфортно, без отказа. Ориентируйся на самочувствие.'
    if not prev_sets:
        if ex.bodyweight:
            return 'Первый раз: делай чисто, оставляя 1–2 повтора в запасе.'
        if start_hint:
            return (f'Первый раз: начни с {start_hint}. Если все повторы даются легко — '
                    'в следующем подходе добавь немного веса.')
        return 'Первый раз: подбери вес, с которым последние 1–2 повтора даются тяжело, но технично.'
    reps = [r for _, r in prev_sets]
    work_w = max(w for w, _ in prev_sets)
    unit = 'сек' if presc.unit == 'sec' else 'повторов'
    if len(prev_sets) >= presc.sets and min(reps) >= presc.hi:
        if work_w:
            step = weight_step(ex, gender)
            return (f'📈 В прошлый раз все подходы на верх диапазона — добавь {fmt_w(step)} кг '
                    f'(работай с {fmt_w(work_w + step)} кг).')
        if presc.unit == 'sec':
            return '📈 Отлично! Добавь 10–15 сек или усложни вариант.'
        return '📈 Отлично! Усложни вариант или добавь утяжеление (рюкзак).'
    if min(reps) < presc.lo:
        if work_w:
            return f'Оставь {fmt_w(work_w)} кг и добейся минимум {presc.lo} {unit} во всех подходах.'
        return f'Цель — минимум {presc.lo} {unit} в каждом подходе.'
    if work_w:
        return f'Тот же вес {fmt_w(work_w)} кг, цель — {presc.hi} {unit} во всех подходах.'
    return f'Цель — {presc.hi} {unit} во всех подходах.'


# ======================================================================
# База данных
# ======================================================================

# kind: 'strength' — тренировка по программе, 'group' — групповая (group_type, group_minutes).
WORKOUT_COLUMNS = {'kind': "TEXT DEFAULT 'strength'", 'group_type': 'TEXT', 'group_minutes': 'INTEGER'}

USER_COLUMNS = {
    'is_trainer': 'INTEGER DEFAULT 0', 'trainer_status': 'TEXT', 'trainer_id': 'INTEGER', 'referred_by': 'INTEGER',
    'ref_code': 'TEXT', 'sub_until': 'TEXT', 'invited_by': 'INTEGER', 'invite_code': 'TEXT', 'theme': 'TEXT',
    'gender': 'TEXT', 'age': 'TEXT', 'cycle_tracking': 'INTEGER DEFAULT 0', 'period_start': 'TEXT',
    'cycle_len': 'INTEGER DEFAULT 28', 'period_len': 'INTEGER DEFAULT 5',
}


def connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, name TEXT, goal TEXT, level TEXT, days INTEGER, place TEXT,
            day_index INTEGER DEFAULT 0, target_weight REAL, rest_timer INTEGER DEFAULT 1, created_at TEXT);
        CREATE TABLE IF NOT EXISTS workouts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, day_index INTEGER, title TEXT,
            started_at TEXT, finished_at TEXT);
        CREATE TABLE IF NOT EXISTS sets(
            id INTEGER PRIMARY KEY AUTOINCREMENT, workout_id INTEGER, user_id INTEGER, exercise_id TEXT,
            set_no INTEGER, weight REAL, reps INTEGER, created_at TEXT);
        CREATE TABLE IF NOT EXISTS body_weight(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, weight REAL, created_at TEXT);
        CREATE TABLE IF NOT EXISTS exercise_goals(
            user_id INTEGER, exercise_id TEXT, target REAL, PRIMARY KEY(user_id, exercise_id));
        CREATE TABLE IF NOT EXISTS cycle_log(
            user_id INTEGER, start_date TEXT, PRIMARY KEY(user_id, start_date));
        CREATE TABLE IF NOT EXISTS trainer_profiles(
            user_id INTEGER PRIMARY KEY, bio TEXT, specializations TEXT, experience_years INTEGER, certificates TEXT,
            city TEXT, format TEXT, max_clients INTEGER, listed INTEGER DEFAULT 1, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS trainer_photos(user_id INTEGER PRIMARY KEY, data BLOB, mime TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS reviews(
            trainer_id INTEGER, client_id INTEGER, rating INTEGER, text TEXT, created_at TEXT, updated_at TEXT,
            PRIMARY KEY(trainer_id, client_id));
        CREATE TABLE IF NOT EXISTS coach_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, trainer_id INTEGER, message TEXT,
            status TEXT DEFAULT 'pending', created_at TEXT, decided_at TEXT);
        CREATE TABLE IF NOT EXISTS coaching(
            id INTEGER PRIMARY KEY AUTOINCREMENT, trainer_id INTEGER, client_id INTEGER, started_at TEXT, ended_at TEXT);
        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, kind TEXT, days INTEGER,
            paid_at TEXT, source TEXT, note TEXT, refunded_at TEXT);
        CREATE TABLE IF NOT EXISTS commissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id INTEGER, trainer_id INTEGER, client_id INTEGER, type TEXT,
            base_amount REAL, percent REAL, amount REAL, status TEXT, created_at TEXT, available_at TEXT,
            payout_id INTEGER);
        CREATE TABLE IF NOT EXISTS payouts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, trainer_id INTEGER, amount REAL, status TEXT, created_at TEXT,
            paid_at TEXT, legal_status TEXT, full_name TEXT, inn TEXT, method TEXT, details TEXT);
        CREATE TABLE IF NOT EXISTS trainer_requisites(
            user_id INTEGER PRIMARY KEY, legal_status TEXT, full_name TEXT, inn TEXT, method TEXT, details TEXT,
            updated_at TEXT);
        CREATE INDEX IF NOT EXISTS commissions_trainer ON commissions(trainer_id, status);
        CREATE TABLE IF NOT EXISTS friend_rewards(
            id INTEGER PRIMARY KEY AUTOINCREMENT, inviter_id INTEGER, friend_id INTEGER UNIQUE, payment_id INTEGER,
            days INTEGER, status TEXT, created_at TEXT, available_at TEXT, granted_at TEXT);
        CREATE TABLE IF NOT EXISTS pairs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, a_id INTEGER, b_id INTEGER, goal INTEGER DEFAULT 3,
            created_at TEXT, ended_at TEXT);
        CREATE TABLE IF NOT EXISTS app_photos(
            slot TEXT, gender TEXT, data BLOB, mime TEXT, updated_at TEXT, PRIMARY KEY(slot, gender));
        CREATE TABLE IF NOT EXISTS body_measurements(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chest REAL, waist REAL, hips REAL, arm REAL,
            thigh REAL, created_at TEXT);
        CREATE TABLE IF NOT EXISTS login_codes(
            code TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT);
        CREATE TABLE IF NOT EXISTS api_sessions(
            token_hash TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT, last_seen TEXT);
        CREATE TABLE IF NOT EXISTS ref_links(
            code TEXT PRIMARY KEY, trainer_id INTEGER, label TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS trainer_invites(
            code TEXT PRIMARY KEY, created_by INTEGER, created_at TEXT, used_by INTEGER, used_at TEXT);
        CREATE TABLE IF NOT EXISTS assignments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, trainer_id INTEGER, client_id INTEGER, date TEXT, title TEXT,
            note TEXT, items TEXT, status TEXT DEFAULT 'pending', workout_id INTEGER, created_at TEXT);
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER, to_id INTEGER, text TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS user_swaps(
            user_id INTEGER, place TEXT, original_id TEXT, replacement_id TEXT,
            PRIMARY KEY(user_id, place, original_id));
        CREATE TABLE IF NOT EXISTS cardio(
            id INTEGER PRIMARY KEY AUTOINCREMENT, workout_id INTEGER, user_id INTEGER, phase TEXT, kind TEXT,
            minutes INTEGER, created_at TEXT);
        CREATE TABLE IF NOT EXISTS exercise_photos(
            exercise_id TEXT, frame INTEGER, gender TEXT, file_id TEXT, added_at TEXT,
            PRIMARY KEY(exercise_id, frame, gender));
        CREATE INDEX IF NOT EXISTS sets_user_ex ON sets(user_id, exercise_id);
        CREATE INDEX IF NOT EXISTS workouts_user ON workouts(user_id, finished_at);
        ''')
        have = {r['name'] for r in c.execute('PRAGMA table_info(users)')}
        for name, decl in USER_COLUMNS.items():
            if name not in have:
                c.execute(f'ALTER TABLE users ADD COLUMN {name} {decl}')
        have = {r['name'] for r in c.execute('PRAGMA table_info(workouts)')}
        for name, decl in WORKOUT_COLUMNS.items():
            if name not in have:
                c.execute(f'ALTER TABLE workouts ADD COLUMN {name} {decl}')
        c.execute('CREATE INDEX IF NOT EXISTS users_trainer ON users(trainer_id)')
        c.execute('CREATE INDEX IF NOT EXISTS users_referred ON users(referred_by)')
        c.execute('CREATE INDEX IF NOT EXISTS users_invited ON users(invited_by)')
        if 'read_at' not in {r['name'] for r in c.execute('PRAGMA table_info(messages)')}:
            c.execute('ALTER TABLE messages ADD COLUMN read_at TEXT')
        c.execute('CREATE INDEX IF NOT EXISTS messages_pair ON messages(from_id, to_id, id)')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_invite_code ON users(invite_code)')


def get_user(uid):
    with connect() as c:
        row = c.execute('SELECT * FROM users WHERE user_id=?', (uid,)).fetchone()
    return dict(row) if row else None


PROFILE_FIELDS = ('gender', 'age', 'goal', 'level', 'days', 'place', 'cycle_tracking', 'cycle_len', 'period_len')


def save_user(uid, name, profile):
    values = {k: profile.get(k) for k in PROFILE_FIELDS}
    values['cycle_tracking'] = 1 if profile.get('cycle_tracking') else 0
    values['cycle_len'] = profile.get('cycle_len') or 28
    values['period_len'] = profile.get('period_len') or 5
    cols = ', '.join(PROFILE_FIELDS)
    marks = ', '.join('?' for _ in PROFILE_FIELDS)
    updates = ', '.join(f'{k}=excluded.{k}' for k in PROFILE_FIELDS)
    with connect() as c:
        c.execute(f'''INSERT INTO users(user_id, name, {cols}, day_index, created_at)
                      VALUES(?, ?, {marks}, 0, ?)
                      ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, {updates}, day_index=0''',
                  (uid, name, *[values[k] for k in PROFILE_FIELDS], now().isoformat(timespec='seconds')))
    if profile.get('period_start'):
        log_period_start(uid, profile['period_start'])


def set_user_field(uid, field, value):
    assert field in ('day_index', 'target_weight', 'rest_timer', 'cycle_tracking', 'period_start',
                     'cycle_len', 'period_len', 'place', 'goal', 'level', 'days', 'trainer_status', 'trainer_id',
                     'sub_until', 'theme')
    with connect() as c:
        c.execute(f'UPDATE users SET {field}=? WHERE user_id=?', (value, uid))


def log_period_start(uid, start):
    """Записывает начало менструации и пересчитывает среднюю длину цикла."""
    start = start if isinstance(start, str) else start.isoformat()
    with connect() as c:
        c.execute('INSERT OR IGNORE INTO cycle_log(user_id,start_date) VALUES(?,?)', (uid, start))
        dates = [date.fromisoformat(r[0]) for r in c.execute(
            'SELECT start_date FROM cycle_log WHERE user_id=? ORDER BY start_date', (uid,))]
        latest = max(dates)
        c.execute('UPDATE users SET period_start=? WHERE user_id=?', (latest.isoformat(), uid))
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        gaps = [g for g in gaps if 20 <= g <= 45][-4:]
        if gaps:
            c.execute('UPDATE users SET cycle_len=? WHERE user_id=?', (round(sum(gaps) / len(gaps)), uid))


def start_workout(uid, day_index, title, kind='strength', group_type=None):
    with connect() as c:
        cur = c.execute('INSERT INTO workouts(user_id,day_index,title,started_at,kind,group_type) VALUES(?,?,?,?,?,?)',
                        (uid, day_index, title, now().isoformat(timespec='seconds'), kind, group_type))
        return cur.lastrowid


def set_group_minutes(wid, minutes):
    with connect() as c:
        c.execute('UPDATE workouts SET group_minutes=? WHERE id=?', (minutes, wid))


def log_past_group(uid, group_type, minutes):
    """Групповая тренировка, которая уже прошла: сразу завершённая запись."""
    end = now()
    start = end - timedelta(minutes=minutes)
    with connect() as c:
        cur = c.execute('''INSERT INTO workouts(user_id,day_index,title,started_at,finished_at,kind,group_type,group_minutes)
                           VALUES(?,?,?,?,?,?,?,?)''',
                        (uid, -1, GROUP_TYPES[group_type][0], start.isoformat(timespec='seconds'),
                         end.isoformat(timespec='seconds'), 'group', group_type, minutes))
        return cur.lastrowid


def add_set(wid, uid, ex_id, set_no, weight, reps):
    with connect() as c:
        c.execute('INSERT INTO sets(workout_id,user_id,exercise_id,set_no,weight,reps,created_at) VALUES(?,?,?,?,?,?,?)',
                  (wid, uid, ex_id, set_no, weight, reps, now().isoformat(timespec='seconds')))


def workout_sets(wid):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM sets WHERE workout_id=? ORDER BY id', (wid,))]


def previous_sets(uid, ex_id, exclude_wid=None):
    """Подходы упражнения с последней завершённой тренировки."""
    with connect() as c:
        row = c.execute('''SELECT s.workout_id FROM sets s JOIN workouts w ON w.id=s.workout_id
                           WHERE s.user_id=? AND s.exercise_id=? AND w.finished_at IS NOT NULL AND s.workout_id!=?
                           ORDER BY s.workout_id DESC LIMIT 1''', (uid, ex_id, exclude_wid or -1)).fetchone()
        if not row:
            return []
        return [(r['weight'], r['reps']) for r in c.execute(
            'SELECT weight,reps FROM sets WHERE workout_id=? AND exercise_id=? ORDER BY set_no', (row[0], ex_id))]


def best_e1rm(uid, ex_id, exclude_wid=None):
    with connect() as c:
        rows = c.execute('''SELECT s.weight,s.reps FROM sets s JOIN workouts w ON w.id=s.workout_id
                            WHERE s.user_id=? AND s.exercise_id=? AND w.finished_at IS NOT NULL AND s.workout_id!=?''',
                         (uid, ex_id, exclude_wid or -1)).fetchall()
    return max((e1rm(r['weight'], r['reps']) for r in rows), default=0.0)


def finish_workout_db(wid):
    with connect() as c:
        c.execute('UPDATE workouts SET finished_at=? WHERE id=?', (now().isoformat(timespec='seconds'), wid))


def get_swaps(uid, place):
    """Постоянные замены пользователя для места: {id из программы: id замены}."""
    if not uid:
        return {}
    try:
        with connect() as c:
            return {r['original_id']: r['replacement_id'] for r in c.execute(
                'SELECT original_id, replacement_id FROM user_swaps WHERE user_id=? AND place=?', (uid, place))}
    except sqlite3.OperationalError:
        return {}


def set_swap(uid, place, original_id, replacement_id):
    with connect() as c:
        if not replacement_id or replacement_id == original_id:
            c.execute('DELETE FROM user_swaps WHERE user_id=? AND place=? AND original_id=?', (uid, place, original_id))
        else:
            c.execute('INSERT OR REPLACE INTO user_swaps(user_id,place,original_id,replacement_id) VALUES(?,?,?,?)',
                      (uid, place, original_id, replacement_id))


def count_swaps(uid):
    with connect() as c:
        return c.execute('SELECT COUNT(*) FROM user_swaps WHERE user_id=?', (uid,)).fetchone()[0]


def clear_swaps(uid):
    with connect() as c:
        c.execute('DELETE FROM user_swaps WHERE user_id=?', (uid,))


def add_cardio(wid, uid, phase, kind, minutes):
    with connect() as c:
        c.execute('INSERT INTO cardio(workout_id,user_id,phase,kind,minutes,created_at) VALUES(?,?,?,?,?,?)',
                  (wid, uid, phase, kind, minutes, now().isoformat(timespec='seconds')))


def workout_cardio(wid):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM cardio WHERE workout_id=? ORDER BY id', (wid,))]


def cardio_minutes_since(uid, since):
    with connect() as c:
        row = c.execute('''SELECT SUM(k.minutes) FROM cardio k JOIN workouts w ON w.id=k.workout_id
                           WHERE k.user_id=? AND w.finished_at IS NOT NULL AND k.created_at>=?''',
                        (uid, since.isoformat(timespec='seconds'))).fetchone()
    return row[0] or 0


def cardio_line(row):
    name = CARDIO[row['kind']][0] if row['kind'] in CARDIO else row['kind']
    phase = '🔥 Разминка' if row['phase'] == 'warmup' else '🧊 Заминка'
    return f'{phase}: {name} — {row["minutes"]} мин'


def delete_workout(wid):
    with connect() as c:
        c.execute('DELETE FROM cardio WHERE workout_id=?', (wid,))
        c.execute('DELETE FROM sets WHERE workout_id=?', (wid,))
        c.execute('DELETE FROM workouts WHERE id=?', (wid,))


def finished_workouts(uid, since=None, limit=None, kind=None):
    q = 'SELECT * FROM workouts WHERE user_id=? AND finished_at IS NOT NULL'
    args = [uid]
    if kind:
        q += " AND COALESCE(kind, 'strength')=?"
        args.append(kind)
    if since:
        q += ' AND finished_at>=?'
        args.append(since.isoformat(timespec='seconds'))
    q += ' ORDER BY finished_at DESC'
    if limit:
        q += f' LIMIT {int(limit)}'
    with connect() as c:
        return [dict(r) for r in c.execute(q, args)]


def personal_records(uid):
    """Лучший подход (по оценке 1ПМ) для каждого упражнения."""
    with connect() as c:
        rows = c.execute('''SELECT s.exercise_id, s.weight, s.reps, s.created_at FROM sets s
                            JOIN workouts w ON w.id=s.workout_id
                            WHERE s.user_id=? AND w.finished_at IS NOT NULL''', (uid,)).fetchall()
    best = {}
    for r in rows:
        score = e1rm(r['weight'], r['reps'])
        if r['exercise_id'] not in best or score > best[r['exercise_id']][0]:
            best[r['exercise_id']] = (score, r['weight'], r['reps'], r['created_at'][:10])
    return best


def best_weight(uid, ex_id):
    with connect() as c:
        row = c.execute('''SELECT MAX(s.weight) FROM sets s JOIN workouts w ON w.id=s.workout_id
                           WHERE s.user_id=? AND s.exercise_id=? AND w.finished_at IS NOT NULL''', (uid, ex_id)).fetchone()
    return row[0] or 0.0


def add_body_weight(uid, w):
    with connect() as c:
        c.execute('INSERT INTO body_weight(user_id,weight,created_at) VALUES(?,?,?)',
                  (uid, w, now().isoformat(timespec='seconds')))


def body_weights(uid):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT weight,created_at FROM body_weight WHERE user_id=? ORDER BY id', (uid,))]


def exercise_goals(uid):
    with connect() as c:
        return {r['exercise_id']: r['target'] for r in c.execute('SELECT * FROM exercise_goals WHERE user_id=?', (uid,))}


def set_exercise_goal(uid, ex_id, target):
    with connect() as c:
        if target <= 0:
            c.execute('DELETE FROM exercise_goals WHERE user_id=? AND exercise_id=?', (uid, ex_id))
        else:
            c.execute('INSERT OR REPLACE INTO exercise_goals(user_id,exercise_id,target) VALUES(?,?,?)', (uid, ex_id, target))


# ======================================================================
# Тексты экранов
# ======================================================================

BTN_TODAY = '🏋️ Тренировка на сегодня'
BTN_PROGRAM = '📋 Моя программа'
BTN_PROGRESS = '📈 Прогресс'
BTN_WEIGHT = '⚖️ Вес тела'
BTN_GOALS = '🎯 Цели'
BTN_CYCLE = '🌸 Цикл'
BTN_SETTINGS = '⚙️ Настройки'
BTN_ADMIN = '🛠 Админ'
BTN_CABINET = '🎓 Кабинет тренера'
BTN_MY_COACH = '🎓 Мой тренер'
BTN_FRIENDS = '🤝 Друзья'


def menu_for(user):
    last = [BTN_FRIENDS, BTN_CYCLE, BTN_SETTINGS] if user and user.get('gender') == 'f' else [BTN_FRIENDS, BTN_SETTINGS]
    rows = [[BTN_TODAY], [BTN_PROGRAM, BTN_PROGRESS], [BTN_WEIGHT, BTN_GOALS], last]
    extra = []
    if user and user.get('trainer_id'):
        extra.append(BTN_MY_COACH)
    if user and user.get('is_trainer'):
        extra.append(BTN_CABINET)
    if user and is_admin(user.get('user_id')):
        extra.append(BTN_ADMIN)
    if extra:
        rows.append(extra)
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def kb(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


def progress_bar(fraction, width=10):
    fraction = max(0.0, min(1.0, fraction))
    full = round(fraction * width)
    return '▰' * full + '▱' * (width - full) + f' {round(fraction * 100)}%'


def age_note(user):
    ag = age_group(user.get('age'))
    if ag == 'teen':
        return ('👦 До 18 лет: работаем без максимальных весов (от 8 повторов), главное — техника. '
                'Первые тренировки желательно провести с тренером.')
    if ag == 'mature':
        return '🕐 40+: разминка дольше, отдых между подходами чуть больше, без работы «в отказ».'
    if ag == 'senior':
        return ('🕐 60+: щадящая программа — тренажёры вместо тяжёлой штанги, от 8 повторов, отдых дольше. '
                'При хронических заболеваниях перед началом проконсультируйся с врачом.')
    return ''


PLACE_SHORT = {GYM: '🏢 в зале', HOME: '🏠 дома'}


def day_overview_text(user, day_index, mods, place=None):
    days = user['days']
    place = place or user['place']
    day = plan_day(user, day_index, mods, place)
    where = PLACE_SHORT[place] + (' (только сегодня)' if place != user['place'] else '')
    lines = [f'<b>🏋️ День {day_index % days + 1} из {days} — {html.escape(day.title)}</b>',
             f'Группы мышц: <b>{", ".join(day.groups)}</b>', f'📍 Тренируемся {where}', '']
    for note in mods['notes']:
        lines += [note, '']
    for i, p in enumerate(day.exercises, 1):
        lines.append(f'{i}. <b>{p.exercise.name}</b> — {p.presc.text()}')
        prev = previous_sets(user['user_id'], p.exercise.id)
        if prev:
            lines.append('   прошлый раз: ' + ', '.join(fmt_set(w, r, p.presc.unit) for w, r in prev))
        elif user['level'] == 'novice' and start_weight(p.exercise, user):
            lines.append(f'   старт: {start_weight(p.exercise, user)}')
    lines += ['', f'ℹ️ {day.note}']
    return '\n'.join(lines)


NOVICE_GUIDE = ('<b>📖 Как читать программу</b>\n'
                '• <b>4×8–12</b> — 4 подхода по 8–12 повторений.\n'
                '• <b>Подход</b> — выполнение упражнения несколько раз подряд без перерыва.\n'
                '• <b>Отдых</b> — пауза между подходами.\n'
                '• Вес подбирай так, чтобы последние 2–3 повтора давались тяжело, но без потери техники.\n'
                '• Когда во всех подходах получается верхняя граница повторов — прибавляй вес, бот подскажет.\n'
                '• Мышцы растут во время отдыха: между тренировками — минимум день перерыва.')


def program_text(user):
    program = user_program(user)
    lines = ['<b>📋 Твоя программа</b>',
             f'Пол: {GENDERS.get(user.get("gender"), "—")}, возраст: {AGES.get(user.get("age"), "—")}',
             f'Цель: {GOALS[user["goal"]]}', f'Уровень: {LEVELS[user["level"]]}',
             f'Где: {PLACES[user["place"]]}', f'Тренировок в неделю: {user["days"]}']
    note = age_note(user)
    if note:
        lines += ['', note]
    if user.get('gender') == 'f':
        lines += ['', '🍑 Добавлен акцент на ноги и ягодицы.']
        if user.get('cycle_tracking'):
            lines.append('🌸 Нагрузка подстраивается под фазу цикла.')
    if user['level'] == 'novice':
        lines += ['', f'🌱 Первые {2 * user["days"]} тренировок — адаптация: на подход меньше и лёгкие веса.']
    lines.append('')
    base = base_program(user)
    for i, day in enumerate(program):
        mark = ' ← следующая' if i == user['day_index'] % len(program) else ''
        lines.append(f'<b>День {i + 1}. {html.escape(day.title)}</b>{mark}')
        for p, orig in zip(day.exercises, base[i].exercises):
            swapped = ' 🔄' if p.exercise.id != orig.exercise.id else ''
            line = f'• {p.exercise.name}{swapped} — {p.presc.text()}'
            if user['level'] == 'novice' and start_weight(p.exercise, user):
                line += f' (старт: {start_weight(p.exercise, user)})'
            lines.append(line)
        lines.append('')
    if user['level'] == 'novice':
        lines.append(NOVICE_GUIDE)
    else:
        lines.append('Между тренировками — минимум день отдыха для тех же мышц. '
                     'Вес увеличивай, когда во всех подходах получается верх диапазона повторов.')
    return '\n'.join(lines)


def exercise_card(user, wk):
    day = wk_day(user, wk)
    p = day.exercises[wk['ex_pos']]
    prev = previous_sets(user['user_id'], p.exercise.id, wk['wid'])
    done = [s for s in workout_sets(wk['wid']) if s['exercise_id'] == p.exercise.id]
    lines = [f'<b>Упражнение {wk["ex_pos"] + 1}/{len(day.exercises)}: {p.exercise.name}</b>',
             f'Мышцы: {GROUPS[p.exercise.group]}', f'План: <b>{p.presc.text()}</b>']
    if p.exercise.tip:
        lines.append(f'Техника: {p.exercise.tip}')
    if prev:
        lines.append('Прошлый раз: ' + ', '.join(fmt_set(w, r, p.presc.unit) for w, r in prev))
    mods = wk.get('mods') or {}
    lines.append('💡 ' + advice(p.exercise, p.presc, prev, user.get('gender') or 'm',
                               mods.get('no_progress', False), start_weight(p.exercise, user)))
    if done:
        lines.append('Сегодня: ' + ', '.join(fmt_set(s['weight'], s['reps'], p.presc.unit) for s in done))
    lines.append('')
    weight = current_weight(user, wk, p, done, prev)
    eq = equipment_of(p.exercise)
    if p.presc.unit == 'sec':
        lines.append(f'<b>Подход {wk["set_no"]}/{p.presc.sets}</b> — нажми время или отправь число секунд.')
    else:
        what = EQUIPMENT[eq][1]
        lines.append(f'⚖️ Вес: <b>{fmt_w(weight)} кг</b> — {what}. Меняй кнопками − / + или нажми на вес.')
        lines.append(f'<b>Подход {wk["set_no"]}/{p.presc.sets}</b> — нажми, сколько повторов сделал(а), '
                     f'или отправь <code>{fmt_w(weight) + " " if weight else ""}{p.presc.hi}</code>.')
    rows = set_buttons(p, weight, bool(done))
    if wk.get('items') is None:
        rows.append([('📖 Техника', f't:{p.exercise.id}'), ('🔄 Заменить', 'sw:l')])
    else:
        rows.append([('📖 Техника', f't:{p.exercise.id}')])
    rows.append([('⏭ Следующее упражнение', 'w:next'), ('🏁 Завершить', 'w:finish')])
    return '\n'.join(lines), kb(rows)


# Снаряды: (название, что вводить, (малый шаг, большой шаг) в кг)
EQUIPMENT = {
    'barbell': ('штанга', 'общий вес штанги вместе с грифом', (2.5, 5)),
    'ez': ('EZ-гриф', 'общий вес вместе с грифом', (1.25, 2.5)),
    'dumbbell': ('гантели', 'вес одной гантели', (1, 2)),
    'machine': ('тренажёр', 'вес, выставленный на тренажёре', (2.5, 5)),
    'plates': ('блины', 'вес блинов на платформе', (5, 10)),
    'smith': ('тренажёр Смита', 'общий вес: блины + гриф Смита (обычно 15–20 кг)', (2.5, 5)),
    'load': ('рюкзак/бутылки', 'вес рюкзака или бутылок', (0.5, 1)),
    'bodyweight': ('свой вес', 'дополнительный вес (пояс, жилет, рюкзак); 0 — без отягощения', (2.5, 5)),
}
EXERCISE_EQUIPMENT = {
    'barbell': ('bench', 'row_bb', 'ohp', 'squat', 'rdl', 'deadlift', 'hip_thrust', 'bb_curl'),
    'ez': ('french',),
    'dumbbell': ('incline_db', 'db_fly', 'row_db', 'db_press', 'lat_raise', 'rear_delt', 'lunge_db', 'hammer'),
    'machine': ('cable_cross', 'lat_pulldown', 'seated_row', 'leg_ext', 'leg_curl', 'cable_kickback', 'pushdown',
                'cable_crunch', 'calf_machine'),
    'plates': ('leg_press',),
    'load': ('backpack_curl', 'backpack_row', 'backpack_press', 'bottle_ext'),
}
_EQUIPMENT_BY_EX = {ex_id: eq for eq, ids in EXERCISE_EQUIPMENT.items() for ex_id in ids}
_EQUIPMENT_BY_EX.update({d['id']: d['equipment'] for d in EXTRA_EXERCISES})
BAR_WEIGHTS = (20, 15, 10, 7)


def equipment_of(ex):
    return _EQUIPMENT_BY_EX.get(ex.id, 'bodyweight')


def current_weight(user, wk, p, done=None, prev=None):
    """Рабочий вес для следующего подхода: выбранный, последний сегодня, прошлый раз или стартовый."""
    chosen = (wk.get('weights') or {}).get(p.exercise.id)
    if chosen is not None:
        return chosen
    if done is None:
        done = [s for s in workout_sets(wk['wid']) if s['exercise_id'] == p.exercise.id]
    if done:
        return done[-1]['weight']
    if prev is None:
        prev = previous_sets(user['user_id'], p.exercise.id, wk['wid'])
    if prev:
        return max(w for w, _ in prev)
    if equipment_of(p.exercise) == 'bodyweight':
        return 0.0
    hint = re.search(r'\d+(?:\.\d+)?', start_weight(p.exercise, user))
    return float(hint.group(0)) if hint else 0.0


def rep_options(presc):
    if presc.unit == 'sec':
        return [30, 45, 60, 90]
    lo, hi = presc.lo, presc.hi
    if hi - lo <= 4:
        return list(range(lo, hi + 1))
    step = max(1, round((hi - lo) / 4))
    values = list(range(lo, hi + 1, step))
    if values[-1] != hi:
        values[-1] = hi
    return values


def set_buttons(p, weight, has_sets):
    """Кнопки ввода подхода: вес − / + и повторы одним нажатием."""
    rows = []
    if p.presc.unit == 'reps':
        small, big = EQUIPMENT[equipment_of(p.exercise)][2]
        label = f'⚖️ {"+" if equipment_of(p.exercise) == "bodyweight" and weight else ""}{fmt_w(weight)} кг'
        rows.append([(f'−{fmt_w(big)}', f'ws:d:-{big}'), (f'−{fmt_w(small)}', f'ws:d:-{small}'),
                     (label, 'ws:in'),
                     (f'+{fmt_w(small)}', f'ws:d:{small}'), (f'+{fmt_w(big)}', f'ws:d:{big}')])
        if equipment_of(p.exercise) in ('barbell', 'ez'):
            rows.append([('🧮 Гриф + блины', 'ws:bar')])
    unit = 'с' if p.presc.unit == 'sec' else ''
    rows.append([(f'{n}{unit}', f'ws:r:{n}') for n in rep_options(p.presc)])
    if has_sets:
        rows.append([('🔁 Как прошлый подход', 'w:repeat')])
    return rows


def parse_weight_input(text):
    """«60», «62,5», «20+2*15», «10+10» → кг."""
    t = (text or '').lower().replace(',', '.').replace('кг', '').replace('kg', '').replace(' ', '')
    t = t.replace('х', '*').replace('x', '*').replace('×', '*')
    if not t or not re.fullmatch(r'[\d.+*]+', t):
        return None
    total = 0.0
    for term in t.split('+'):
        if not term:
            return None
        value = 1.0
        for factor in term.split('*'):
            try:
                value *= float(factor)
            except ValueError:
                return None
        total += value
    return round(total, 2) if 0 <= total <= 500 else None


def cycle_screen_text(user):
    lines = ['<b>🌸 Менструальный цикл</b>', '']
    if not user.get('cycle_tracking'):
        lines.append('Учёт цикла выключен. Включи, чтобы бот подстраивал нагрузку под фазу цикла.')
        return '\n'.join(lines)
    info = cycle_info(user)
    if not info:
        lines.append('Укажи дату начала последних месячных.')
        return '\n'.join(lines)
    lines.append(cycle_text(info))
    lines += ['', f'Средняя длина цикла: {info["length"]} дн., менструация: {user.get("period_len") or 5} дн.',
              f'Следующие месячные — примерно {info["next_start"].strftime("%d.%m")} '
              f'(через {info["days_left"]} дн.).', '',
              '<b>Как бот меняет тренировки</b>',
              '🩸 Менструация — на подход меньше, отдых дольше, без повышения весов.',
              '🌱 После менструации — лучшее время прибавлять веса.',
              '✨ Овуляция — сила на пике, особое внимание разминке и коленям.',
              '🌙 За 5 дней до менструации — держим веса, отдых чуть дольше.', '',
              'Это ориентир, а не правило: если чувствуешь себя хорошо — можно тренироваться в обычном режиме. '
              'При сильных болях, обильных или нерегулярных месячных — обратись к гинекологу.']
    return '\n'.join(lines)


def cycle_screen_kb(user):
    if not user.get('cycle_tracking'):
        return kb([[('✅ Включить учёт цикла', 'c:on')]])
    return kb([[('🩸 Месячные начались сегодня', 'c:today')],
               [('📅 Указать другую дату', 'c:date')],
               [('Длина цикла', 'c:len'), ('Длительность менструации', 'c:plen')],
               [('🔕 Выключить учёт', 'c:off')]])


def cycle_len_kb(prefix):
    return kb([[(str(n), f'{prefix}:{n}') for n in (21, 24, 26, 28)],
               [(str(n), f'{prefix}:{n}') for n in (30, 32, 35)],
               [('Не знаю — 28', f'{prefix}:28')]])


def period_len_kb(prefix):
    return kb([[(str(n), f'{prefix}:{n}') for n in (3, 4, 5, 6, 7)]])


def period_start_kb(prefix):
    return kb([[('Сегодня', f'{prefix}:0'), ('Вчера', f'{prefix}:1'), ('2 дня назад', f'{prefix}:2')],
               [('📅 Ввести дату', f'{prefix}:date')]])


# ======================================================================
# Иллюстрации техники
# ======================================================================

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp')
_photo_ids = {}  # путь к файлу → file_id в Telegram, чтобы не загружать повторно


def frame_count(ex_id):
    return len(EXERCISE_FRAMES.get(ex_id, (None, []))[1])


def db_photos(ex_id):
    """{(кадр, пол): file_id} — фото, загруженные администратором через бота."""
    with connect() as c:
        return {(r['frame'], r['gender']): r['file_id'] for r in c.execute(
            'SELECT frame, gender, file_id FROM exercise_photos WHERE exercise_id=?', (ex_id,))}


def save_photo(ex_id, frame, gender, file_id):
    with connect() as c:
        c.execute('INSERT OR REPLACE INTO exercise_photos(exercise_id,frame,gender,file_id,added_at) VALUES(?,?,?,?,?)',
                  (ex_id, frame, gender, file_id, now().isoformat(timespec='seconds')))


def delete_photo(ex_id, frame, gender):
    with connect() as c:
        c.execute('DELETE FROM exercise_photos WHERE exercise_id=? AND frame=? AND gender=?', (ex_id, frame, gender))


def _file_photo(ex_id, frame, gender):
    name = f'{ex_id}_{frame}' + ('_f' if gender == 'f' else '')
    return next((IMAGES_DIR / (name + ext) for ext in IMAGE_EXTS if (IMAGES_DIR / (name + ext)).is_file()), None)


def photo_source(ex_id, frame, gender, stored=None):
    """file_id из базы или путь к файлу в images/ для одного кадра (без запасного варианта по полу)."""
    stored = db_photos(ex_id) if stored is None else stored
    return stored.get((frame, gender)) or _file_photo(ex_id, frame, gender)


def photo_key(gender):
    """Ключ версии фото: '' — мужская, 'f' — женская."""
    return 'f' if gender == 'f' else ''


def exercise_photos(ex_id, gender='m'):
    """[(file_id или путь, подпись), ...]: мужчинам — мужские фото, девушкам — женские.
    Если для кадра нет версии своего пола, показываем другую, чтобы не оставлять кадр пустым."""
    frames = EXERCISE_FRAMES.get(ex_id, (None, []))[1]
    stored = db_photos(ex_id)
    photos = []
    for i, (caption, _) in enumerate(frames, 1):
        variants = ['f', ''] if gender == 'f' else ['', 'f']
        source = next((src for g in variants if (src := photo_source(ex_id, i, g, stored))), None)
        if source:
            photos.append((source, caption))
    return photos


def photo_coverage(ex_id, gender=''):
    """(кадров с фото этой версии, всего кадров). gender: '' — мужская, 'f' — женская."""
    stored = db_photos(ex_id)
    total = frame_count(ex_id)
    return sum(1 for i in range(1, total + 1) if photo_source(ex_id, i, gender, stored)), total


def coverage_label(ex_id):
    m, total = photo_coverage(ex_id, '')
    f, _ = photo_coverage(ex_id, 'f')
    return f'👨 {m}/{total} · 👩 {f}/{total}'


async def send_photos(message, ex, gender):
    photos = exercise_photos(ex.id, gender)
    if not photos:
        return False
    files = []
    try:
        media = []
        for i, (source, caption) in enumerate(photos):
            text = f'{ex.name}\n{i + 1}. {caption}' if i == 0 else f'{i + 1}. {caption}'
            if isinstance(source, Path):
                if str(source) in _photo_ids:
                    source = _photo_ids[str(source)]
                else:
                    source = open(source, 'rb')
                    files.append(source)
            media.append(InputMediaPhoto(source, caption=text))
        sent = await message.reply_media_group(media)
        for (source, _), msg in zip(photos, sent):
            if isinstance(source, Path) and msg.photo:
                _photo_ids[str(source)] = msg.photo[-1].file_id
        return True
    except Exception as exc:
        log.warning('Не удалось отправить картинки %s: %s', ex.id, exc)
        return False
    finally:
        for f in files:
            f.close()


def technique_text(ex, user=None):
    secondary, setup, steps, breath, mistakes = TECHNIQUE[ex.id]
    muscles = GROUPS[ex.group] + (f', {secondary}' if secondary else '')
    places = ' / '.join({GYM: 'зал', HOME: 'дом'}[p] for p in ex.places)
    lines = [f'<b>📖 {html.escape(ex.name)}</b>',
             f'💪 Работают: {muscles}', f'📍 Где: {places}', '',
             '<b>Подготовка</b>', setup, '',
             '<b>Выполнение</b>']
    lines += [f'{i}. {step}' for i, step in enumerate(steps, 1)]
    lines += ['', f'<b>🫁 Дыхание:</b> {breath}', '', '<b>⚠️ Частые ошибки</b>']
    lines += [f'• {m}' for m in mistakes]
    if ex.tip:
        lines += ['', f'💡 Главное: {ex.tip}']
    if user and user.get('level') == 'novice' and start_weight(ex, user):
        lines.append(f'🏁 Стартовый вес: {start_weight(ex, user)}')
    return '\n'.join(lines)


async def send_technique(message, ex, user):
    """Кнопка «Техника»: фото кадров + понятное описание."""
    gender = (user or {}).get('gender') or 'm'
    has_photos = await send_photos(message, ex, gender)
    text = technique_text(ex, user)
    rows = []
    if user and is_admin(user.get('user_id')):
        if not has_photos:
            text += '\n\n🖼 Фото пока не загружены.'
        rows.append([(f'🛠 Фото: {coverage_label(ex.id)}', f'ad:e:{ex.id}')])
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb(rows) if rows else None)


async def send_card(message, user, wk, prefix=''):
    """Карточка упражнения; перед первым подходом — картинки техники."""
    day = wk_day(user, wk)
    ex = day.exercises[wk['ex_pos']].exercise
    if wk['set_no'] == 1 and not prefix:
        await send_photos(message, ex, user.get('gender') or 'm')
    text, markup = exercise_card(user, wk)
    await message.reply_text(prefix + text, parse_mode=ParseMode.HTML, reply_markup=markup)


# ======================================================================
# Разминка и заминка
# ======================================================================

def cardio_card_text(user, wk, phase):
    ag = age_group(user.get('age'))
    lo, hi, _ = cardio_minutes(phase, user['goal'], ag)
    p_lo, p_hi = pulse_range(phase, user['goal'], user.get('age'))
    group = wk.get('kind') == 'group'
    day = None if group else wk_day(user, wk)
    if phase == 'warmup':
        lines = ['<b>🔥 Разминка — 2 шага</b>', '',
                 f'<b>1. Кардио {lo}–{hi} мин</b> — выбери тренажёр ниже.',
                 f'Темп лёгкий: можешь свободно говорить. Пульс ~{p_lo}–{p_hi} уд/мин.', '',
                 '<b>2. Суставная гимнастика</b> (2–3 мин):']
        lines += [f'• {item}' for item in JOINT_WARMUP]
        first = day.exercises[0] if day else None
        if group:
            lines += ['', f'💡 Потом — на занятие «{GROUP_TYPES[wk["group_type"]][0]}». Разминка поможет войти '
                          'в темп с первых минут.']
        elif equipment_of(first.exercise) != 'bodyweight':
            lines += ['', f'💡 Перед «{first.exercise.name}» сделай 1–2 разминочных подхода с лёгким весом.']
    else:
        tempo = ('ровный умеренный темп — это работа на жиросжигание' if user['goal'] == 'fat_loss'
                 else 'спокойный темп, постепенно замедляйся')
        lines = ['<b>🧊 Заминка — 2 шага</b>', '',
                 f'<b>1. Кардио {lo}–{hi} мин</b> — {tempo}. Пульс ~{p_lo}–{p_hi} уд/мин.', '',
                 '<b>2. Растяжка</b> мышц, которые работали сегодня — по 20–30 сек, без рывков:']
        groups = GROUP_TYPES[wk['group_type']][1] if group else \
            list(dict.fromkeys(p.exercise.group for p in day.exercises))
        lines += [f'• {STRETCHES[g]}' for g in groups if g in STRETCHES]
    lines += ['', 'Выбери тренажёр:']
    return '\n'.join(lines)


def cardio_kinds(user, wk, phase):
    kinds = cardio_options(wk.get('place') or user['place'], age_group(user.get('age')))
    if phase == 'cooldown':  # для заминки — без прыжков
        kinds = [k for k in kinds if not CARDIO[k][2]] or kinds
    return kinds


async def send_cardio_card(message, context, user, phase):
    wk = context.user_data['wk']
    kinds = cardio_kinds(user, wk, phase)
    buttons = [(CARDIO[k][0], f'wu:k:{k}') for k in kinds]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    skip = '⏭ Пропустить разминку' if phase == 'warmup' else '🏁 Завершить без заминки'
    rows.append([(skip, 'wu:skip')])
    await message.reply_text(cardio_card_text(user, wk, phase), parse_mode=ParseMode.HTML, reply_markup=kb(rows))


async def start_cardio_stage(message, context, user, phase):
    wk = context.user_data['wk']
    cancel_rest(user['user_id'])
    wk['stage'] = phase
    wk.pop('cardio_kind', None)
    context.user_data['wk'] = wk
    if phase == 'cooldown' and wk.get('kind') == 'group':
        await message.reply_text('💪 Занятие позади! Осталась заминка — она ускорит восстановление.')
    elif phase == 'cooldown':
        await message.reply_text('💪 Основная часть позади! Осталась заминка — она ускорит восстановление.')
    elif wk.get('kind') == 'group':
        await message.reply_text('Отлично! 🔥 Перед групповой тренировкой — короткая разминка.')
    else:
        await message.reply_text('Поехали! 🔥 Начинаем с разминки — она разогреет мышцы и суставы и снизит риск травм.')
    await send_cardio_card(message, context, user, phase)


async def finish_cardio(message, context, user, minutes):
    wk = context.user_data['wk']
    phase, kind = wk.get('stage'), wk.get('cardio_kind')
    if kind and minutes:
        add_cardio(wk['wid'], user['user_id'], phase, kind, minutes)
    await end_cardio_stage(message, context, user)


async def end_cardio_stage(message, context, user):
    wk = context.user_data['wk']
    phase = wk.get('stage')
    wk.pop('cardio_kind', None)
    if phase == 'warmup' and wk.get('kind') == 'group':
        wk['stage'] = 'group'
        context.user_data['wk'] = wk
        await send_group_card(message, wk)
    elif phase == 'warmup':
        wk['stage'] = 'main'
        context.user_data['wk'] = wk
        await message.reply_text('✅ Разминка готова. Переходим к основной части!')
        await send_card(message, user, wk)
    else:
        await finish_workout(message, context, user['user_id'])


async def cardio_callback(data, update, context):
    message = update.callback_query.message
    wk = context.user_data.get('wk')
    user = get_user(update.effective_user.id)
    if not wk or not profile_complete(user) or wk.get('stage') not in ('warmup', 'cooldown'):
        return
    phase = wk['stage']
    parts = data.split(':')
    if parts[1] == 'k' and len(parts) == 3 and parts[2] in CARDIO:
        kind = parts[2]
        wk['cardio_kind'] = kind
        context.user_data['wk'] = wk
        name, _, _, how = CARDIO[kind]
        lo, hi, default = cardio_minutes(phase, user['goal'], age_group(user.get('age')))
        p_lo, p_hi = pulse_range(phase, user['goal'], user.get('age'))
        tempo = 'в лёгком темпе' if phase == 'warmup' else 'в спокойном темпе, к концу замедляйся'
        await message.reply_text(
            f'<b>{name}</b> — {lo}–{hi} мин {tempo}.\nКак: {how}.\nПульс ~{p_lo}–{p_hi} уд/мин.\n\n'
            'Когда закончишь — нажми кнопку с минутами или отправь своё число.',
            parse_mode=ParseMode.HTML,
            reply_markup=kb([[(f'✅ {m} мин', f'wu:done:{m}') for m in sorted({lo, default, hi})],
                             [('🔀 Другой тренажёр', 'wu:menu'), ('⏭ Пропустить', 'wu:skip')]]))
    elif parts[1] == 'done' and len(parts) == 3 and parts[2].isdigit() and wk.get('cardio_kind'):
        await finish_cardio(message, context, user, int(parts[2]))
    elif parts[1] == 'menu':
        await send_cardio_card(message, context, user, phase)
    elif parts[1] == 'skip':
        await end_cardio_stage(message, context, user)


# ======================================================================
# Групповые тренировки
# ======================================================================

# id: (название, мышцы для растяжки после занятия)
GROUP_TYPES = {
    'yoga': ('🧘 Йога', ['back', 'hams', 'shoulders', 'core']),
    'pilates': ('🤸 Пилатес', ['core', 'glutes', 'back']),
    'stretch': ('🙆 Стретчинг', ['hams', 'quads', 'back', 'shoulders']),
    'functional': ('🏋️ Функциональный тренинг', ['quads', 'glutes', 'chest', 'back', 'core']),
    'hiit': ('🔥 Кроссфит / HIIT', ['quads', 'glutes', 'shoulders', 'back', 'core']),
    'pump': ('💪 Body Pump / силовая аэробика', ['quads', 'chest', 'back', 'shoulders']),
    'cycle': ('🚴 Сайкл', ['quads', 'hams', 'glutes', 'calves']),
    'dance': ('💃 Танцы / Зумба', ['quads', 'calves', 'glutes', 'core']),
    'step': ('🪜 Степ-аэробика', ['quads', 'glutes', 'calves']),
    'boxing': ('🥊 Бокс / единоборства', ['shoulders', 'chest', 'back', 'core']),
    'trx': ('🧗 TRX', ['back', 'chest', 'core', 'glutes']),
    'aqua': ('🏊 Аквааэробика / бассейн', ['shoulders', 'back', 'quads']),
    'other': ('👥 Другая групповая', ['quads', 'back', 'shoulders', 'core']),
}
GROUP_MINUTES = (30, 45, 55, 60, 90)


def group_types_kb():
    buttons = [(name, f'gr:t:{key}') for key, (name, _) in GROUP_TYPES.items()]
    return kb([buttons[i:i + 2] for i in range(0, len(buttons), 2)])


async def send_group_card(message, wk, resume=False):
    name = GROUP_TYPES[wk['group_type']][0]
    head = (f'👥 Идёт занятие <b>{html.escape(name)}</b>.' if resume
            else f'✅ Разминка готова. Иди на занятие <b>{html.escape(name)}</b> 💪')
    await message.reply_text(
        f'{head}\n\n'
        'Пей воду и работай в своём темпе. Когда занятие закончится — нажми его длительность '
        '(или отправь число минут), и перейдём к заминке.',
        parse_mode=ParseMode.HTML,
        reply_markup=kb([[(f'{m} мин', f'gr:m:{m}') for m in GROUP_MINUTES]]))


async def end_group_class(message, context, user, minutes):
    wk = context.user_data['wk']
    set_group_minutes(wk['wid'], minutes)
    wk['group_minutes'] = minutes
    context.user_data['wk'] = wk
    await start_cardio_stage(message, context, user, 'cooldown')


async def finish_group_workout(message, wk, user, cardio):
    name = GROUP_TYPES[wk['group_type']][0]
    if not wk.get('group_minutes') and not cardio:
        delete_workout(wk['wid'])
        await message.reply_text('Групповая тренировка отменена — ничего не отмечено.', reply_markup=menu_for(user))
        return
    finish_workout_db(wk['wid'])
    lines = ['<b>🏁 Групповая тренировка засчитана! Отличная работа 💪</b>', '',
             f'{name} — {wk.get("group_minutes") or "?"} мин']
    lines += [cardio_line(r) for r in cardio]
    await message.reply_text('\n'.join(lines + ['', week_progress_line(user)]), parse_mode=ParseMode.HTML,
                             reply_markup=menu_for(user))
    await after_workout_social(message, message.get_bot(), user['user_id'], wk['wid'])


def week_progress_line(user):
    week = finished_workouts(user['user_id'], since=now() - timedelta(days=7))
    return f'На этой неделе: {len(week)} из {user["days"]} тренировок {progress_bar(len(week) / user["days"])}'


async def save_past_group(message, uid, group_type, minutes):
    user = get_user(uid)
    log_past_group(uid, group_type, minutes)
    await message.reply_text(
        f'✅ Отметил: <b>{html.escape(GROUP_TYPES[group_type][0])}</b> — {minutes} мин.\n\n{week_progress_line(user)}',
        parse_mode=ParseMode.HTML, reply_markup=menu_for(user))
    await social_after_workout(message.get_bot(), uid)


async def after_workout_social(message, bot, uid, wid):
    await message.reply_text('📸 Поделись результатом — друг по твоей ссылке получит подарок.',
                             reply_markup=kb([[('📸 Карточка результата', f'fr:card:{wid}')]]))
    await social_after_workout(bot, uid)


async def group_callback(data, update, context):
    """gr:menu → gr:t:<тип> → gr:go:<тип> (сейчас, с разминкой) | gr:log:<тип> (уже прошла) → минуты."""
    message = update.callback_query.message
    uid = update.effective_user.id
    user = get_user(uid)
    if not profile_complete(user):
        return
    parts = data.split(':')
    wk = context.user_data.get('wk')
    if data == 'gr:menu':
        if wk:
            await message.reply_text('Сначала заверши текущую тренировку.')
            return
        await message.reply_text('👥 Какая групповая тренировка?', reply_markup=group_types_kb())
    elif parts[1] == 't' and len(parts) == 3 and parts[2] in GROUP_TYPES:
        name = GROUP_TYPES[parts[2]][0]
        await message.reply_text(f'<b>{html.escape(name)}</b>', parse_mode=ParseMode.HTML, reply_markup=kb(
            [[('▶️ Иду сейчас — с разминкой и заминкой', f'gr:go:{parts[2]}')],
             [('✅ Уже была — просто отметить', f'gr:log:{parts[2]}')]]))
    elif parts[1] == 'go' and len(parts) == 3 and parts[2] in GROUP_TYPES:
        if wk:
            await message.reply_text('Сначала заверши текущую тренировку.')
            return
        name = GROUP_TYPES[parts[2]][0]
        wid = start_workout(uid, -1, name, kind='group', group_type=parts[2])
        context.user_data['wk'] = {'wid': wid, 'kind': 'group', 'group_type': parts[2], 'day': user['day_index'],
                                   'place': place_today(user, context.user_data), 'stage': 'warmup',
                                   'ex_pos': 0, 'set_no': 1, 'started': now().isoformat(timespec='seconds')}
        context.user_data.pop('await', None)
        await start_cardio_stage(message, context, user, 'warmup')
    elif parts[1] == 'log' and len(parts) == 3 and parts[2] in GROUP_TYPES:
        context.user_data['await'] = f'group_log:{parts[2]}'
        await message.reply_text('Сколько длилось занятие? Нажми или отправь число минут.', reply_markup=kb(
            [[(f'{m} мин', f'gr:lm:{parts[2]}:{m}') for m in GROUP_MINUTES]]))
    elif parts[1] == 'lm' and len(parts) == 4 and parts[2] in GROUP_TYPES and parts[3].isdigit():
        context.user_data.pop('await', None)
        await save_past_group(message, uid, parts[2], int(parts[3]))
    elif parts[1] == 'm' and len(parts) == 3 and parts[2].isdigit() and wk and wk.get('stage') == 'group':
        await end_group_class(message, context, user, int(parts[2]))


# ======================================================================
# Замена упражнений
# ======================================================================

PLACE_CODE = {'g': GYM, 'h': HOME}


def alternatives(day, pos, place):
    """Упражнения на ту же группу мышц, доступные в этом месте и ещё не входящие в день."""
    current = day.exercises[pos]
    used = {p.exercise.id for p in day.exercises}
    pool = [e for e in _EXERCISE_LIST if e.group == current.exercise.group and place in e.places and e.id not in used]
    # Для базового упражнения сначала базовые варианты, для изолирующего — изолирующие.
    pool.sort(key=lambda e: e.compound != current.exercise.compound)
    return pool


def alternative_label(ex):
    eq = EQUIPMENT[equipment_of(ex)][0]
    return f'{ex.name} · {eq}'


async def swap_callback(data, update, context):
    """Замена упражнения во время тренировки: sw:l — список, sw:p:<id> — выбор, sw:t/sw:f:<id> — сегодня/навсегда."""
    message = update.callback_query.message
    uid = update.effective_user.id
    wk = context.user_data.get('wk')
    user = get_user(uid)
    if not wk or wk.get('stage', 'main') != 'main' or not profile_complete(user):
        return
    if wk.get('items') is not None:
        await message.reply_text('Эту тренировку составил тренер — заменить упражнение можно, написав ему.')
        return
    place = wk.get('place') or user['place']
    day = plan_day(user, wk['day'], wk.get('mods'), place, wk.get('swaps'))
    base_ex = base_program(user, place)[wk['day'] % user['days']].exercises[wk['ex_pos']].exercise
    current = day.exercises[wk['ex_pos']].exercise
    parts = data.split(':')
    if parts[1] == 'l':
        options = alternatives(day, wk['ex_pos'], place)
        rows = [[(alternative_label(e), f'sw:p:{e.id}')] for e in options]
        if current.id != base_ex.id:
            rows.insert(0, [(f'↩️ Как в программе: {base_ex.name}', f'sw:p:{base_ex.id}')])
        if not rows:
            await message.reply_text('Для этой группы мышц здесь нет других вариантов.')
            return
        await message.reply_text(f'🔄 Чем заменить «{current.name}»? ({GROUPS[current.group]})',
                                 reply_markup=kb(rows))
    elif parts[1] == 'p' and len(parts) == 3 and parts[2] in EXERCISES:
        new = EXERCISES[parts[2]]
        await message.reply_text(f'«{current.name}» → «{new.name}». Заменить:', reply_markup=kb(
            [[('📅 Только сегодня', f'sw:t:{new.id}'), ('♾ Навсегда в программе', f'sw:f:{new.id}')]]))
    elif parts[1] in ('t', 'f') and len(parts) == 3 and parts[2] in EXERCISES:
        new = EXERCISES[parts[2]]
        if place not in new.places:
            return
        swaps = dict(wk.get('swaps') or {})
        if parts[1] == 'f':
            set_swap(uid, place, base_ex.id, new.id)
            swaps.pop(base_ex.id, None)
            scope = 'навсегда — так будет и в следующих тренировках'
        else:
            swaps[base_ex.id] = new.id
            scope = 'только на эту тренировку'
        wk['swaps'] = swaps
        wk['set_no'] = 1
        context.user_data['wk'] = wk
        cancel_rest(uid)
        await message.reply_text(f'✅ Заменил «{current.name}» на «{new.name}» {scope}.')
        await send_card(message, user, wk)


async def replace_program_callback(data, update, context):
    """Замена в программе (вне тренировки): rp → день → упражнение → вариант → навсегда."""
    message = update.callback_query.message
    uid = update.effective_user.id
    user = get_user(uid)
    if not profile_complete(user):
        return
    parts = data.split(':')
    if data == 'rp':
        code = user['place'][0]
        await message.reply_text('🔄 В каком дне заменить упражнение?', reply_markup=kb(
            [[(f'День {i + 1}: {d.title}', f'rp:d:{i}:{code}')] for i, d in enumerate(user_program(user))]))
        return
    if len(parts) < 4 or not parts[2].isdigit() or parts[3] not in PLACE_CODE:
        return
    day_index, place = int(parts[2]) % user['days'], PLACE_CODE[parts[3]]
    day = user_program(user, place)[day_index]
    base = base_program(user, place)[day_index]
    if parts[1] == 'd':
        rows = [[(f'{i + 1}. {p.exercise.name}', f'rp:e:{day_index}:{parts[3]}:{i}')] for i, p in enumerate(day.exercises)]
        await message.reply_text(f'<b>{html.escape(day.title)}</b> ({PLACE_SHORT[place]}) — какое упражнение заменить?',
                                 parse_mode=ParseMode.HTML, reply_markup=kb(rows))
    elif parts[1] == 'e' and len(parts) == 5 and parts[4].isdigit() and int(parts[4]) < len(day.exercises):
        pos = int(parts[4])
        current, orig = day.exercises[pos].exercise, base.exercises[pos].exercise
        rows = [[(alternative_label(e), f'rp:n:{day_index}:{parts[3]}:{pos}:{e.id}')]
                for e in alternatives(day, pos, place)]
        if current.id != orig.id:
            rows.insert(0, [(f'↩️ Как в программе: {orig.name}', f'rp:n:{day_index}:{parts[3]}:{pos}:{orig.id}')])
        await message.reply_text(f'🔄 Чем заменить «{current.name}»? ({GROUPS[current.group]})', reply_markup=kb(rows))
    elif parts[1] == 'n' and len(parts) == 6 and parts[4].isdigit() and parts[5] in EXERCISES \
            and int(parts[4]) < len(day.exercises):
        pos, new = int(parts[4]), EXERCISES[parts[5]]
        if place not in new.places:
            return
        set_swap(uid, place, base.exercises[pos].exercise.id, new.id)
        await message.reply_text(f'✅ Готово: в программе ({PLACE_SHORT[place]}) теперь «{new.name}» вместо '
                                 f'«{day.exercises[pos].exercise.name}». Вернуть исходные — в «{BTN_SETTINGS}».')


# ======================================================================
# Ввод веса
# ======================================================================

def _current_planned(user, wk):
    return wk_day(user, wk).exercises[wk['ex_pos']]


async def set_current_weight(message, context, uid, weight, note=''):
    wk = context.user_data.get('wk')
    user = get_user(uid)
    if not wk or wk.get('stage', 'main') != 'main' or not profile_complete(user):
        return
    p = _current_planned(user, wk)
    wk.setdefault('weights', {})[p.exercise.id] = max(0.0, round(weight, 2))
    context.user_data['wk'] = wk
    rows = set_buttons(p, wk['weights'][p.exercise.id], bool(workout_sets(wk['wid'])))
    rows.append([('⏭ Следующее', 'w:next'), ('🏁 Завершить', 'w:finish')])
    head = (note or f'Вес: <b>{fmt_w(wk["weights"][p.exercise.id])} кг</b>')
    await message.reply_text(f'{head} — {html.escape(p.exercise.name)}.\n'
                             f'Подход {wk["set_no"]}/{p.presc.sets}: нажми, сколько повторов сделал(а).',
                             parse_mode=ParseMode.HTML, reply_markup=kb(rows))


async def weight_callback(data, update, context):
    message = update.callback_query.message
    uid = update.effective_user.id
    wk = context.user_data.get('wk')
    user = get_user(uid)
    if not wk or wk.get('stage', 'main') != 'main' or not profile_complete(user):
        return
    p = _current_planned(user, wk)
    parts = data.split(':')
    if parts[1] == 'r' and len(parts) == 3 and parts[2].isdigit():
        weight = current_weight(user, wk, p) if p.presc.unit == 'reps' else 0.0
        await log_set(update, context, weight, int(parts[2]))
    elif parts[1] == 'd' and len(parts) == 3:
        try:
            delta = float(parts[2])
        except ValueError:
            return
        await set_current_weight(message, context, uid, current_weight(user, wk, p) + delta)
    elif data == 'ws:in':
        context.user_data['await'] = 'ws_weight'
        what = EQUIPMENT[equipment_of(p.exercise)][1]
        await message.reply_text(f'⚖️ Отправь вес для «{p.exercise.name}» в кг — {what}.\n'
                                 'Например: 42.5. Можно сложить: 20+10+10.')
    elif data == 'ws:bar':
        await message.reply_text('🧮 Какой гриф?', reply_markup=kb(
            [[(f'Гриф {b} кг', f'ws:bar:{b}') for b in BAR_WEIGHTS], [('Без грифа (только блины)', 'ws:bar:0')]]))
    elif parts[1] == 'bar' and len(parts) == 3 and parts[2].isdigit():
        context.user_data['await'] = f'ws_bar:{parts[2]}'
        await message.reply_text('Сколько блинов на ОДНОЙ стороне? Отправь их вес, например: 10 или 10+5+2.5.\n'
                                 'Бот посчитает общий вес: гриф + 2 стороны.')


# ======================================================================
# Таймер отдыха
# ======================================================================

_rest_tasks = {}


def cancel_rest(uid):
    task = _rest_tasks.pop(uid, None)
    if task and not task.done():
        task.cancel()


def schedule_rest(bot, chat_id, uid, seconds, text):
    cancel_rest(uid)

    async def _timer():
        try:
            await asyncio.sleep(seconds)
            await bot.send_message(chat_id, text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover
            log.warning('Таймер отдыха: %s', exc)
        finally:
            if _rest_tasks.get(uid) is asyncio.current_task():
                _rest_tasks.pop(uid, None)

    _rest_tasks[uid] = asyncio.create_task(_timer())


# ======================================================================
# Анкета
# ======================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    context.user_data.pop('await', None)
    payload = (context.args or [''])[0] if getattr(context, 'args', None) else ''
    if payload.startswith('login_'):
        await handle_app_login(update, context, payload[6:])
        return
    if payload.startswith('coach_'):
        await handle_coach_invite(update, context, payload[6:])
        if not profile_complete(get_user(uid)):
            return
    elif payload.startswith('ref_'):
        await handle_ref_start(update, context, payload[4:])
    elif payload.startswith('u_'):
        await handle_friend_start(update, context, payload[2:])
    elif payload.startswith('pair_'):
        await handle_friend_start(update, context, payload[5:], pair=True)
    user = get_user(uid)
    if profile_complete(user):
        await update.effective_message.reply_text(
            f'С возвращением, {html.escape(update.effective_user.first_name or "атлет")}! 💪\n'
            f'Следующая тренировка — день {user["day_index"] % user["days"] + 1}. Жми «{BTN_TODAY}».',
            reply_markup=menu_for(user), parse_mode=ParseMode.HTML)
        return
    await update.effective_message.reply_text(
        'Привет! Я фитнес-бот 🤖💪\n\n'
        'Дам готовую программу тренировок — даже если ты впервые в зале: какие мышцы тренируем, '
        'какие упражнения, сколько подходов и повторов, с какого веса начать. '
        'Буду записывать результаты и подсказывать, когда прибавлять вес.\n\n'
        'Программа учитывает пол, возраст, цель и опыт, а для девушек — ещё и фазу цикла. '
        'Ответь на несколько вопросов — это меньше минуты.')
    await ask_gender(update.effective_message, context)


async def ask_gender(message, context):
    context.user_data['onb'] = {}
    await message.reply_text('Твой пол?', reply_markup=kb([[(v, f'sx:{k}') for k, v in GENDERS.items()]]))


async def finish_onboarding(message, context, update):
    uid = update.effective_user.id
    onb = context.user_data.get('onb') or {}
    if not all(k in onb for k in ('gender', 'age', 'goal', 'level', 'days', 'place')):
        await ask_gender(message, context)
        return
    save_user(uid, update.effective_user.first_name or '', onb)
    context.user_data.pop('onb', None)
    context.user_data.pop('wk', None)
    context.user_data.pop('await', None)
    user = get_user(uid)
    await message.reply_text('✅ Готовая программа составлена!', reply_markup=menu_for(user))
    await message.reply_text(program_text(user), parse_mode=ParseMode.HTML)
    await message.reply_text(f'Когда будешь на тренировке — жми «{BTN_TODAY}». Я проведу по каждому упражнению: '
                             'покажу технику, подходы, повторы и вес, а ты будешь отправлять результаты.')


async def onboarding_callback(data, update, context):
    """Шаги анкеты. Возвращает True, если callback обработан."""
    message = update.callback_query.message
    onb = context.user_data.setdefault('onb', {})
    if data.startswith('sx:') and data[3:] in GENDERS:
        onb.clear()
        onb['gender'] = data[3:]
        await message.edit_text(f'Пол: {GENDERS[onb["gender"]]}\n\nСколько тебе лет?',
                                reply_markup=kb([[(v, f'a:{k}') for k, v in list(AGES.items())[:3]],
                                                 [(v, f'a:{k}') for k, v in list(AGES.items())[3:]]]))
    elif data.startswith('a:') and data[2:] in AGES:
        onb['age'] = data[2:]
        await message.edit_text(f'Возраст: {AGES[onb["age"]]}\n\nКакая у тебя главная цель?',
                                reply_markup=kb([[(v, f'g:{k}')] for k, v in GOALS.items()]))
    elif data.startswith('g:') and data[2:] in GOALS:
        onb['goal'] = data[2:]
        await message.edit_text(f'Цель: {GOALS[onb["goal"]]}\n\nТвой опыт тренировок?',
                                reply_markup=kb([[(v, f'l:{k}')] for k, v in LEVELS.items()]))
    elif data.startswith('l:') and data[2:] in LEVELS:
        onb['level'] = data[2:]
        hint = '\n\nНовичкам рекомендуем 2–3 тренировки — этого достаточно для прогресса.' if onb['level'] == 'novice' else ''
        await message.edit_text(f'Опыт: {LEVELS[onb["level"]]}\n\nСколько тренировок в неделю готов делать?{hint}',
                                reply_markup=kb([[(str(d), f'd:{d}') for d in DAY_OPTIONS]]))
    elif data.startswith('d:') and data[2:].isdigit() and int(data[2:]) in DAY_OPTIONS:
        onb['days'] = int(data[2:])
        await message.edit_text(f'Тренировок в неделю: {onb["days"]}\n\nГде тренируешься?',
                                reply_markup=kb([[(v, f'p:{k}')] for k, v in PLACES.items()]))
    elif data.startswith('p:') and data[2:] in PLACES:
        onb['place'] = data[2:]
        if onb.get('gender') == 'f':
            await message.edit_text(
                f'Где: {PLACES[onb["place"]]}\n\n🌸 Учитывать менструальный цикл?\n'
                'В дни менструации бот даст облегчённую тренировку, а в «сильные» фазы — подскажет прибавить веса. '
                'Данные видишь только ты.',
                reply_markup=kb([[('✅ Да, учитывать', 'oc:yes')],
                                 [('Нет (не нужно / гормональные контрацептивы / менопауза)', 'oc:no')]]))
        else:
            await message.edit_text(f'Где: {PLACES[onb["place"]]}')
            await finish_onboarding(message, context, update)
    elif data == 'oc:no':
        onb['cycle_tracking'] = 0
        await message.edit_text('Учёт цикла выключен — его можно включить позже в разделе «🌸 Цикл».')
        await finish_onboarding(message, context, update)
    elif data == 'oc:yes':
        onb['cycle_tracking'] = 1
        await message.edit_text('Когда начались последние месячные?', reply_markup=period_start_kb('op'))
    elif data.startswith('op:'):
        arg = data[3:]
        if arg == 'date':
            context.user_data['await'] = 'onb_period'
            await message.edit_text('Отправь дату начала последних месячных, например <code>03.11</code>.',
                                    parse_mode=ParseMode.HTML)
        elif arg.isdigit():
            onb['period_start'] = (now().date() - timedelta(days=int(arg))).isoformat()
            await ask_cycle_len(message, edit=True)
    elif data.startswith('ol:') and data[3:].isdigit():
        onb['cycle_len'] = int(data[3:])
        await message.edit_text(f'Длина цикла: {onb["cycle_len"]} дн.\n\nСколько дней обычно длится менструация?',
                                reply_markup=period_len_kb('opl'))
    elif data.startswith('opl:') and data[4:].isdigit():
        onb['period_len'] = int(data[4:])
        await message.edit_text(f'Менструация: {onb["period_len"]} дн. Спасибо! 🌸')
        await finish_onboarding(message, context, update)
    else:
        return False
    return True


async def ask_cycle_len(message, edit=False):
    text = ('Какая обычно длина цикла (от первого дня одних месячных до первого дня следующих)? '
            'Бот будет уточнять её сам по твоим отметкам.')
    if edit:
        await message.edit_text(text, reply_markup=cycle_len_kb('ol'))
    else:
        await message.reply_text(text, reply_markup=cycle_len_kb('ol'))


# ======================================================================
# Экраны
# ======================================================================

async def need_profile(update, context):
    """Если анкета не заполнена — запускает её и возвращает None."""
    user = get_user(update.effective_user.id)
    if profile_complete(user):
        return user
    await update.effective_message.reply_text('Сначала заполним короткую анкету, чтобы составить программу.')
    await ask_gender(update.effective_message, context)
    return None


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await need_profile(update, context)
    if not user:
        return
    timer = '🔔 вкл' if user['rest_timer'] else '🔕 выкл'
    sub = f'активна до {date.fromisoformat(user["sub_until"]):%d.%m.%Y}' if has_subscription(user) else 'нет'
    trainer_row = [] if is_trainer(user) else [[('🎓 Я тренер — партнёрская программа', 'tr:apply')]]
    await update.effective_message.reply_text(
        f'<b>⚙️ Настройки</b>\nПол: {GENDERS[user["gender"]]}\nВозраст: {AGES[user["age"]]}\n'
        f'Цель: {GOALS[user["goal"]]}\nОпыт: {LEVELS[user["level"]]}\n'
        f'Где: {PLACES[user["place"]]}\nТренировок в неделю: {user["days"]}\nТаймер отдыха: {timer}\n'
        f'💳 Подписка: {sub}\nТвой ID: <code>{user["user_id"]}</code>',
        parse_mode=ParseMode.HTML,
        reply_markup=kb([[('🔄 Заполнить анкету заново', 's:redo')],
                         [(f'📍 Место по умолчанию: {PLACE_SHORT[user["place"]]}', 's:place')],
                         [(f'Таймер отдыха: {timer}', 's:timer')]]
                        + ([[(f'↩️ Вернуть исходные упражнения ({count_swaps(user["user_id"])})', 's:unswap')]]
                           if count_swaps(user['user_id']) else [])
                        + trainer_row))


async def show_today(update: Update, context: ContextTypes.DEFAULT_TYPE, day_index=None):
    user = await need_profile(update, context)
    if not user:
        return
    wk = context.user_data.get('wk')
    if wk:
        if wk.get('stage', 'main') in ('warmup', 'cooldown'):
            await update.effective_message.reply_text('Тренировка уже идёт — продолжаем!')
            await send_cardio_card(update.effective_message, context, user, wk['stage'])
        elif wk.get('stage') == 'group':
            await send_group_card(update.effective_message, wk, resume=True)
        else:
            await send_card(update.effective_message, user, wk, prefix='Тренировка уже идёт — продолжаем!\n\n')
        return
    due = client_assignments(user['user_id'], until=today_iso()) if user.get('trainer_id') else []
    if due and day_index is None:
        rows = [[(f'▶️ {a["title"]} ({date_label(a["date"])})', f'cl:go:{a["id"]}')] for a in due[:3]]
        rows.append([('📋 Своя программа на сегодня', f'w:show:{user["day_index"] % user["days"]}')])
        lines = ['<b>🎯 Тренировка от тренера на сегодня</b>', '']
        for a in due[:3]:
            lines.append(f'<b>{html.escape(a["title"])}</b>')
            lines += [item_line(i, it) for i, it in enumerate(a['items'], 1)]
            if a['note']:
                lines.append(f'💬 {html.escape(a["note"])}')
            lines.append('')
        await update.effective_message.reply_text('\n'.join(lines), parse_mode=ParseMode.HTML, reply_markup=kb(rows))
        return
    if day_index is None:
        day_index = user['day_index']
    day_index %= user['days']
    mods = today_mods(user)
    place = place_today(user, context.user_data)
    rows = [[('▶️ Начать тренировку', f'w:start:{day_index}')]]
    info = cycle_info(user)
    if info and PHASES[info['phase']][2]:
        rows = [[('▶️ Начать облегчённую', f'w:start:{day_index}')],
                [('💪 Чувствую себя отлично — обычная', f'w:start:{day_index}:std')]]
    other = HOME if place == GYM else GYM
    rows.append([({GYM: '🏢 Сегодня в зале', HOME: '🏠 Сегодня дома'}[other], f'w:place:{day_index}:{other}')])
    rows.append([('🔀 Выбрать другой день', 'w:pick'), ('👥 Групповая', 'gr:menu')])
    rows += technique_rows(plan_day(user, day_index, place=place))
    rows.append([('🔄 Заменить упражнение', f'rp:d:{day_index}:{place[0]}')])
    await update.effective_message.reply_text(day_overview_text(user, day_index, mods, place), parse_mode=ParseMode.HTML,
                                              reply_markup=kb(rows))


def technique_rows(day):
    """Кнопки «📖 Техника» для каждого упражнения дня (по две в ряд)."""
    buttons = []
    for i, p in enumerate(day.exercises, 1):
        name = p.exercise.name if len(p.exercise.name) <= 22 else p.exercise.name[:21] + '…'
        buttons.append((f'📖 {i}. {name}', f't:{p.exercise.id}'))
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


async def show_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await need_profile(update, context)
    if user:
        await update.effective_message.reply_text(program_text(user), parse_mode=ParseMode.HTML,
                                                  reply_markup=kb([[('📖 Техника упражнений', 'tp')],
                                                                   [('🔄 Заменить упражнение', 'rp')]]))


async def show_cycle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await need_profile(update, context)
    if not user:
        return
    if user['gender'] != 'f':
        await update.effective_message.reply_text('Этот раздел доступен для женского профиля.')
        return
    await update.effective_message.reply_text(cycle_screen_text(user), parse_mode=ParseMode.HTML,
                                              reply_markup=cycle_screen_kb(user))


async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await need_profile(update, context)
    if not user:
        return
    uid = user['user_id']
    t = now()
    total = finished_workouts(uid)
    week = finished_workouts(uid, since=t - timedelta(days=7))
    month = finished_workouts(uid, since=t - timedelta(days=30))
    group_month = [w for w in month if w.get('kind') == 'group']
    group_total = sum(1 for w in total if w.get('kind') == 'group')
    lines = ['<b>📈 Прогресс</b>', '',
             f'Тренировок всего: <b>{len(total)}</b>' + (f' (из них групповых: {group_total})' if group_total else ''),
             f'За 30 дней: <b>{len(month)}</b>',
             f'За 7 дней: <b>{len(week)}</b> из {user["days"]} запланированных',
             progress_bar(len(week) / user['days'])]
    if group_month:
        counts = {}
        for w in group_month:
            counts[w.get('group_type')] = counts.get(w.get('group_type'), 0) + 1
        kinds = ', '.join(f'{GROUP_TYPES.get(k, ("👥 Групповая",))[0]} ×{n}' for k, n in counts.items())
        minutes = sum(w.get('group_minutes') or 0 for w in group_month)
        lines.append(f'👥 Групповые за 30 дней: <b>{len(group_month)}</b> ({minutes} мин) — {kinds}')
    lines += [
             f'🏃 Кардио за 7 дней: <b>{cardio_minutes_since(uid, t - timedelta(days=7))} мин</b>', '']
    if total and total[0].get('kind') == 'group':
        last = total[0]
        lines += [f'Последняя тренировка: {last["finished_at"][:10]} — {html.escape(last["title"])}, '
                  f'{last.get("group_minutes") or "?"} мин', '']
    elif total:
        last = total[0]
        sets = workout_sets(last['id'])
        tonnage = sum(s['weight'] * s['reps'] for s in sets
                      if s['exercise_id'] in EXERCISES and EXERCISES[s['exercise_id']].unit == 'reps')
        lines.append(f'Последняя тренировка: {last["finished_at"][:10]} — {html.escape(last["title"])}, '
                     f'{len(sets)} подходов, тоннаж {fmt_w(tonnage)} кг')
        lines.append('')
    prs = personal_records(uid)
    if prs:
        lines.append('<b>🏆 Личные рекорды</b>')
        ranked = sorted(prs.items(), key=lambda kv: (EXERCISES[kv[0]].bodyweight if kv[0] in EXERCISES else True, -kv[1][0]))
        for ex_id, (score, w, r, day) in ranked[:10]:
            ex = EXERCISES.get(ex_id)
            if not ex:
                continue
            extra = f' (≈1ПМ {fmt_w(round(score, 1))} кг)' if w and r > 1 else ''
            lines.append(f'• {ex.name}: {fmt_set(w, r, ex.unit)}{extra} — {day}')
        lines.append('')
    bw = body_weights(uid)
    if bw:
        cur, first = bw[-1]['weight'], bw[0]['weight']
        diff = cur - first
        sign = '+' if diff > 0 else ''
        change = f' ({sign}{fmt_w(diff)} кг от старта)' if len(bw) > 1 else ''
        lines.append(f'⚖️ Вес тела: <b>{fmt_w(cur)} кг</b>{change}')
    if not total:
        lines.append(f'Пока нет завершённых тренировок. Жми «{BTN_TODAY}» и начнём!')
    await update.effective_message.reply_text('\n'.join(lines), parse_mode=ParseMode.HTML,
                                              reply_markup=kb([[('📜 История тренировок', 'h:list')]]))


def history_text(uid):
    workouts = finished_workouts(uid, limit=5)
    if not workouts:
        return 'История пока пуста.'
    lines = ['<b>📜 Последние тренировки</b>', '']
    for w in workouts:
        start_dt, end_dt = datetime.fromisoformat(w['started_at']), datetime.fromisoformat(w['finished_at'])
        minutes = max(1, int((end_dt - start_dt).total_seconds() // 60))
        lines.append(f'<b>{w["finished_at"][:10]} — {html.escape(w["title"])}</b> ({minutes} мин)')
        if w.get('kind') == 'group':
            lines.append(f'• Занятие: {w.get("group_minutes") or "?"} мин')
        by_ex = {}
        for s in workout_sets(w['id']):
            by_ex.setdefault(s['exercise_id'], []).append(s)
        for ex_id, sets in by_ex.items():
            ex = EXERCISES.get(ex_id)
            name = ex.name if ex else ex_id
            unit = ex.unit if ex else 'reps'
            lines.append(f'• {name}: ' + ', '.join(fmt_set(s['weight'], s['reps'], unit) for s in sets))
        lines += [cardio_line(r) for r in workout_cardio(w['id'])]
        lines.append('')
    return '\n'.join(lines)


def weight_text(uid):
    user = get_user(uid)
    bw = body_weights(uid)
    lines = ['<b>⚖️ Вес тела</b>']
    if bw:
        lines.append('')
        for row in bw[-7:]:
            lines.append(f'{row["created_at"][:10]} — {fmt_w(row["weight"])} кг')
        if len(bw) > 1:
            diff = bw[-1]['weight'] - bw[0]['weight']
            sign = '+' if diff > 0 else ''
            lines.append(f'\nИзменение от старта: <b>{sign}{fmt_w(diff)} кг</b>')
        target = user and user.get('target_weight')
        if target:
            lines.append(goal_weight_line(bw, target))
    else:
        lines.append('Записей пока нет.')
    tip = 'Лучше взвешиваться утром натощак.'
    if user and user.get('gender') == 'f' and user.get('cycle_tracking'):
        tip += ' Перед и во время месячных вес может быть выше на 0.5–2 кг из-за воды — это не жир.'
    lines.append(f'\nОтправь текущий вес числом, например <code>78.4</code>. {tip}')
    return '\n'.join(lines)


def goal_weight_line(bw, target):
    start_w, cur = bw[0]['weight'], bw[-1]['weight']
    frac = 1.0 if abs(start_w - target) < 0.05 else (start_w - cur) / (start_w - target)
    return f'Цель {fmt_w(target)} кг: {progress_bar(frac)}, осталось {fmt_w(abs(target - cur))} кг'


async def show_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['await'] = 'bw'
    await update.effective_message.reply_text(weight_text(update.effective_user.id), parse_mode=ParseMode.HTML,
                                              reply_markup=kb([[('📏 Объёмы тела', 'ms:show')]]))


def goals_text(uid):
    user = get_user(uid)
    lines = ['<b>🎯 Цели</b>', '', f'Главная цель: {GOALS[user["goal"]]}', '']
    bw = body_weights(uid)
    if user.get('target_weight'):
        if bw:
            lines.append('⚖️ ' + goal_weight_line(bw, user['target_weight']))
        else:
            lines.append(f'⚖️ Цель по весу тела: {fmt_w(user["target_weight"])} кг (запиши текущий вес в «{BTN_WEIGHT}»)')
    else:
        lines.append('⚖️ Цель по весу тела не задана.')
    goals = exercise_goals(uid)
    if goals:
        lines.append('')
        for ex_id, target in goals.items():
            ex = EXERCISES.get(ex_id)
            if not ex:
                continue
            best = best_weight(uid, ex_id)
            lines.append(f'🏋️ {ex.name}: {fmt_w(best)} / {fmt_w(target)} кг\n   {progress_bar(best / target if target else 0)}')
    else:
        lines.append('🏋️ Целей по упражнениям пока нет (например, «Жим лёжа 100 кг»).')
    return '\n'.join(lines)


async def show_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await need_profile(update, context):
        return
    await update.effective_message.reply_text(
        goals_text(update.effective_user.id), parse_mode=ParseMode.HTML,
        reply_markup=kb([[('⚖️ Цель по весу тела', 'goal:bw')], [('🏋️ Цель по упражнению', 'goal:ex')]]))


# ======================================================================
# Тренировка
# ======================================================================

async def finish_workout(message, context, uid):
    wk = context.user_data.pop('wk', None)
    cancel_rest(uid)
    user = get_user(uid)
    if not wk:
        await message.reply_text('Активной тренировки нет.', reply_markup=menu_for(user))
        return
    sets = workout_sets(wk['wid'])
    cardio = workout_cardio(wk['wid'])
    if wk.get('kind') == 'group':
        await finish_group_workout(message, wk, user, cardio)
        return
    if not sets and not cardio:
        delete_workout(wk['wid'])
        await message.reply_text('Тренировка отменена — ни одного подхода не записано.', reply_markup=menu_for(user))
        return
    records = []
    for ex_id in dict.fromkeys(s['exercise_id'] for s in sets):
        before = best_e1rm(uid, ex_id, wk['wid'])
        today = max(e1rm(s['weight'], s['reps']) for s in sets if s['exercise_id'] == ex_id)
        if before and today > before:
            records.append(EXERCISES[ex_id].name if ex_id in EXERCISES else ex_id)
    finish_workout_db(wk['wid'])
    if not wk.get('assigned'):
        set_user_field(uid, 'day_index', (wk['day'] + 1) % user['days'])
    started = datetime.fromisoformat(wk['started'])
    minutes = max(1, int((now() - started).total_seconds() // 60))
    tonnage = sum(s['weight'] * s['reps'] for s in sets
                  if EXERCISES.get(s['exercise_id']) and EXERCISES[s['exercise_id']].unit == 'reps')
    exercises_done = len({s['exercise_id'] for s in sets})
    lines = ['<b>🏁 Тренировка завершена! Отличная работа 💪</b>', '',
             f'⏱ Длительность: {minutes} мин', f'🏋️ Упражнений: {exercises_done}, подходов: {len(sets)}',
             f'📦 Тоннаж: {fmt_w(tonnage)} кг']
    lines += [cardio_line(r) for r in cardio]
    if records:
        lines += ['', '🏆 <b>Новые рекорды:</b> ' + ', '.join(records)]
    week = finished_workouts(uid, since=now() - timedelta(days=7))
    if wk.get('assigned'):
        set_assignment_status(wk['assigned'], 'done', wk['wid'])
        a = get_assignment(wk['assigned'])
        if a:
            details = '\n'.join(f'• {EXERCISES[e].name if e in EXERCISES else e}: '
                                + ', '.join(fmt_set(s['weight'], s['reps'], EXERCISES[e].unit if e in EXERCISES else 'reps')
                                            for s in sets if s['exercise_id'] == e)
                                for e in dict.fromkeys(s['exercise_id'] for s in sets))
            await notify(context.bot, a['trainer_id'],
                         f'✅ <b>{html.escape(display_name(user))}</b> выполнил(а) тренировку '
                         f'«{html.escape(a["title"])}» за {minutes} мин.\n\n{details}'
                         + (f'\n🏆 Рекорды: {html.escape(", ".join(records))}' if records else ''),
                         kb([[('👤 Открыть', f'tr:c:{uid}')]]))
        lines += ['', f'На этой неделе: {len(week)} из {user["days"]} тренировок {progress_bar(len(week) / user["days"])}',
                  'Тренер получил отчёт о тренировке 📨']
    else:
        lines += ['', f'На этой неделе: {len(week)} из {user["days"]} тренировок {progress_bar(len(week) / user["days"])}',
                  f'Следующая — день {(wk["day"] + 1) % user["days"] + 1}. Не забудь про сон и белок 🍗']
    await message.reply_text('\n'.join(lines), parse_mode=ParseMode.HTML, reply_markup=menu_for(user))
    await after_workout_social(message, context.bot, uid, wk['wid'])


async def log_set(update: Update, context: ContextTypes.DEFAULT_TYPE, weight, reps):
    uid = update.effective_user.id
    wk = context.user_data['wk']
    user = get_user(uid)
    day = wk_day(user, wk)
    p = day.exercises[wk['ex_pos']]
    add_set(wk['wid'], uid, p.exercise.id, wk['set_no'], weight, reps)
    wk.setdefault('weights', {})[p.exercise.id] = weight
    msg = f'✅ Подход {wk["set_no"]}: {fmt_set(weight, reps, p.presc.unit)}'
    if p.presc.unit == 'reps' and reps < p.presc.lo:
        msg += f'\nМеньше плана ({p.presc.lo}+) — в следующем подходе можно снизить вес на 5–10%.'
    elif p.presc.unit == 'reps' and reps > p.presc.hi + 2 and weight:
        msg += '\nСлишком легко — прибавь вес в следующем подходе.'
    wk['set_no'] += 1
    context.user_data['wk'] = wk
    message = update.effective_message
    if wk['set_no'] > p.presc.sets:
        msg += f'\n\n✔️ «{p.exercise.name}» выполнено!'
        await message.reply_text(msg)
        await next_exercise(message, context, uid, rest=p.presc.rest)
        return
    msg += f'\n⏱ Отдых {fmt_rest(p.presc.rest)}. Дальше — подход {wk["set_no"]}/{p.presc.sets}.'
    rows = set_buttons(p, current_weight(user, wk, p), True)
    rows.append([('⏭ Следующее', 'w:next'), ('🏁 Завершить', 'w:finish')])
    await message.reply_text(msg, reply_markup=kb(rows))
    if user['rest_timer']:
        schedule_rest(context.bot, message.chat_id, uid, p.presc.rest,
                      f'⏰ Отдых окончен — подход {wk["set_no"]}/{p.presc.sets}: {p.exercise.name}')


async def next_exercise(message, context, uid, rest=None):
    wk = context.user_data.get('wk')
    if not wk:
        return
    user = get_user(uid)
    day = wk_day(user, wk)
    wk['ex_pos'] += 1
    wk['set_no'] = 1
    context.user_data['wk'] = wk
    if wk['ex_pos'] >= len(day.exercises):
        await start_cardio_stage(message, context, user, 'cooldown')
        return
    await send_card(message, user, wk)
    if rest and user['rest_timer']:
        schedule_rest(context.bot, message.chat_id, uid, rest,
                      f'⏰ Отдых окончен — переходим к «{day.exercises[wk["ex_pos"]].exercise.name}»')


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ''
    uid = update.effective_user.id
    message = q.message
    await q.answer()

    if await onboarding_callback(data, update, context):
        return

    # --- Настройки ---
    if data == 's:redo':
        await ask_gender(message, context)
    elif data == 's:unswap':
        clear_swaps(uid)
        await message.edit_text(f'↩️ Все замены отменены — программа снова как по анкете. Смотри «{BTN_PROGRAM}».')
    elif data.startswith('sw:'):
        await swap_callback(data, update, context)
    elif data == 'rp' or data.startswith('rp:'):
        await replace_program_callback(data, update, context)
    elif data == 's:place':
        user = get_user(uid)
        if profile_complete(user) and not context.user_data.get('wk'):
            new = HOME if user['place'] == GYM else GYM
            set_user_field(uid, 'place', new)
            context.user_data.pop('place_today', None)
            await message.edit_text(f'📍 Теперь по умолчанию тренируемся {PLACE_SHORT[new]}. '
                                    f'Программа пересобрана под это место — смотри «{BTN_PROGRAM}».')
    elif data == 's:timer':
        user = get_user(uid)
        if user:
            set_user_field(uid, 'rest_timer', 0 if user['rest_timer'] else 1)
            await message.edit_text('Таймер отдыха ' + ('выключен 🔕' if user['rest_timer'] else 'включён 🔔'))

    # --- Цикл ---
    elif data.startswith('c:'):
        await cycle_callback(data, update, context)

    # --- Тренировка ---
    elif data == 'w:pick':
        user = get_user(uid)
        if not profile_complete(user):
            return
        program = user_program(user)
        await message.reply_text('Какой день показать?', reply_markup=kb(
            [[(f'День {i + 1}: {d.title}', f'w:show:{i}')] for i, d in enumerate(program)]))
    elif data.startswith('w:show:'):
        await show_today(update, context, int(data.split(':')[2]))
    elif data.startswith('w:place:'):
        parts = data.split(':')
        if len(parts) == 4 and parts[2].isdigit() and parts[3] in PLACES and not context.user_data.get('wk'):
            context.user_data['place_today'] = {'date': now().date().isoformat(), 'place': parts[3]}
            await message.reply_text(f'Ок, сегодня тренируемся {PLACE_SHORT[parts[3]]}. '
                                     'Программа дня та же, упражнения подобраны под это место.')
            await show_today(update, context, int(parts[2]))
    elif data.startswith('w:start:'):
        user = get_user(uid)
        if not profile_complete(user):
            return
        if context.user_data.get('wk'):
            await show_today(update, context)
            return
        parts = data.split(':')
        day_index = int(parts[2]) % user['days']
        mods = today_mods(user, standard=len(parts) > 3 and parts[3] == 'std')
        place = place_today(user, context.user_data)
        day = plan_day(user, day_index, mods, place)
        title = day.title + (' (дома)' if place == HOME else ' (в зале)') if place != user['place'] else day.title
        wid = start_workout(uid, day_index, title)
        context.user_data['wk'] = {'wid': wid, 'day': day_index, 'ex_pos': 0, 'set_no': 1, 'mods': mods,
                                   'place': place, 'stage': 'warmup', 'weights': {},
                                   'started': now().isoformat(timespec='seconds')}
        context.user_data.pop('await', None)
        await start_cardio_stage(message, context, user, 'warmup')
    elif data == 'w:photos':  # кнопка из старых сообщений
        wk = context.user_data.get('wk')
        user = get_user(uid)
        if wk and profile_complete(user):
            ex = wk_day(user, wk).exercises[wk['ex_pos']].exercise
            await send_technique(message, ex, user)

    # --- Техника ---
    elif data.startswith('t:'):
        ex = EXERCISES.get(data[2:])
        if ex:
            await send_technique(message, ex, get_user(uid))
    elif data == 'tp':
        user = get_user(uid)
        if profile_complete(user):
            await message.reply_text('Техника упражнений — выбери день:', reply_markup=kb(
                [[(f'День {i + 1}: {d.title}', f'td:{i}')] for i, d in enumerate(user_program(user))]))
    elif data.startswith('td:') and data[3:].isdigit():
        user = get_user(uid)
        if profile_complete(user):
            day = plan_day(user, int(data[3:]))
            await message.reply_text(f'<b>{html.escape(day.title)}</b> — выбери упражнение:', parse_mode=ParseMode.HTML,
                                     reply_markup=kb(technique_rows(day)))

    # --- Админ ---
    elif data.startswith('ad:'):
        await admin_callback(data, update, context)
    elif data == 'w:next':
        if context.user_data.get('wk'):
            cancel_rest(uid)
            await next_exercise(message, context, uid)
    elif data == 'w:repeat':
        wk = context.user_data.get('wk')
        if not wk:
            return
        sets = workout_sets(wk['wid'])
        if sets:
            last = sets[-1]
            await log_set(update, context, last['weight'], last['reps'])
    elif data == 'w:finish':
        wk = context.user_data.get('wk')
        if wk and wk.get('stage', 'main') == 'main' and workout_sets(wk['wid']):
            await start_cardio_stage(message, context, get_user(uid), 'cooldown')
        else:
            await finish_workout(message, context, uid)
    elif data.startswith('gr:'):
        await group_callback(data, update, context)
    elif data.startswith('tr:'):
        await trainer_callback(data, update, context)
    elif data.startswith('fr:'):
        await friends_callback(data, update, context)
    elif data == 'ms:show':
        context.user_data['await'] = 'measure'
        await update.callback_query.message.reply_text(measurements_text(update.effective_user.id), parse_mode=ParseMode.HTML)
    elif data.startswith('cl:'):
        await client_callback(data, update, context)
    elif data.startswith('wu:'):
        await cardio_callback(data, update, context)
    elif data.startswith('ws:'):
        await weight_callback(data, update, context)

    # --- История ---
    elif data == 'h:list':
        await message.reply_text(history_text(uid), parse_mode=ParseMode.HTML)

    # --- Цели ---
    elif data == 'goal:bw':
        context.user_data['await'] = 'target_bw'
        await message.reply_text('Какой вес тела хочешь достичь? Отправь число, например <code>75</code>. '
                                 '0 — удалить цель.', parse_mode=ParseMode.HTML)
    elif data == 'goal:ex':
        user = get_user(uid)
        if not profile_complete(user):
            return
        ids = []
        for day in user_program(user):
            for p in day.exercises:
                if not p.exercise.bodyweight and p.exercise.id not in ids:
                    ids.append(p.exercise.id)
        if not ids:
            await message.reply_text('В твоей программе нет упражнений с отягощением. '
                                     'Следи за рекордами повторов в «Прогрессе».')
            return
        await message.reply_text('Выбери упражнение:', reply_markup=kb(
            [[(EXERCISES[i].name, f'goal:ex:{i}')] for i in ids]))
    elif data.startswith('goal:ex:'):
        ex_id = data.split(':', 2)[2]
        if ex_id in EXERCISES:
            context.user_data['await'] = f'target_ex:{ex_id}'
            best = best_weight(uid, ex_id)
            await message.reply_text(
                f'{EXERCISES[ex_id].name}: твой лучший вес — {fmt_w(best)} кг.\n'
                'Какой рабочий вес хочешь взять? Отправь число в кг (0 — удалить цель).')


async def cycle_callback(data, update, context):
    uid = update.effective_user.id
    message = update.callback_query.message
    user = get_user(uid)
    if not profile_complete(user) or user['gender'] != 'f':
        return
    if data == 'c:on':
        set_user_field(uid, 'cycle_tracking', 1)
        if not user.get('period_start'):
            await message.reply_text('Когда начались последние месячные?', reply_markup=period_start_kb('cs'))
            return
    elif data == 'c:off':
        set_user_field(uid, 'cycle_tracking', 0)
    elif data == 'c:today':
        log_period_start(uid, now().date())
    elif data == 'c:date':
        context.user_data['await'] = 'period_date'
        await message.reply_text('Отправь дату начала месячных, например <code>03.11</code>.', parse_mode=ParseMode.HTML)
        return
    elif data == 'c:len':
        await message.reply_text('Средняя длина цикла (дней):', reply_markup=cycle_len_kb('c:setlen'))
        return
    elif data == 'c:plen':
        await message.reply_text('Сколько дней длится менструация?', reply_markup=period_len_kb('c:setplen'))
        return
    elif data.startswith('c:setlen:'):
        set_user_field(uid, 'cycle_len', int(data.rsplit(':', 1)[1]))
    elif data.startswith('c:setplen:'):
        set_user_field(uid, 'period_len', int(data.rsplit(':', 1)[1]))
    else:
        return
    user = get_user(uid)
    await message.reply_text(cycle_screen_text(user), parse_mode=ParseMode.HTML, reply_markup=cycle_screen_kb(user))


async def cs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Дата начала месячных при включении учёта из раздела «Цикл» (cs:<дней назад>|date)."""
    q = update.callback_query
    await q.answer()
    arg = q.data[3:]
    if arg == 'date':
        context.user_data['await'] = 'period_date'
        await q.message.reply_text('Отправь дату начала месячных, например <code>03.11</code>.', parse_mode=ParseMode.HTML)
        return
    if arg.isdigit():
        uid = update.effective_user.id
        log_period_start(uid, now().date() - timedelta(days=int(arg)))
        user = get_user(uid)
        await q.message.reply_text(cycle_screen_text(user), parse_mode=ParseMode.HTML, reply_markup=cycle_screen_kb(user))


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or '').strip()
    uid = update.effective_user.id
    routes = {BTN_TODAY: show_today, BTN_PROGRAM: show_program, BTN_PROGRESS: show_progress,
              BTN_WEIGHT: show_weight, BTN_GOALS: show_goals, BTN_SETTINGS: settings, BTN_CYCLE: show_cycle,
              BTN_ADMIN: admin_panel, BTN_CABINET: trainer_cabinet, BTN_MY_COACH: show_my_coach,
              BTN_FRIENDS: show_friends}
    if text in routes:
        if text != BTN_WEIGHT:
            context.user_data.pop('await', None)
        await routes[text](update, context)
        return
    awaiting = context.user_data.get('await')
    message = update.effective_message
    if awaiting and awaiting.startswith('photo:'):
        await message.reply_text('Жду фото для упражнения — отправь картинку или /cancel.')
        return
    if awaiting == 'link_label':
        user = get_user(uid)
        if is_trainer(user):
            context.user_data.pop('await', None)
            code = create_ref_link(uid, text[:40])
            url = f'https://t.me/{context.bot.username}?start=ref_{code}'
            await message.reply_text(f'✅ Ссылка «{html.escape(text[:40])}» готова:\n<code>{url}</code>\n\n'
                                     'Нажми, чтобы скопировать, и отправь клиентам.', parse_mode=ParseMode.HTML,
                                     reply_markup=kb([[('🔗 Все ссылки', 'tr:links'), ('⬅️ Кабинет', 'tr:home')]]),
                                     disable_web_page_preview=True)
        return
    if awaiting == 'build_weight' and context.user_data.get('build'):
        value = parse_weight_input(text)
        if value is None:
            await message.reply_text('Отправь вес числом, например 40, или нажми «Без веса».')
            return
        context.user_data.pop('await', None)
        await add_build_item(message, context, value or None)
        return
    if awaiting == 'build_note' and context.user_data.get('build'):
        context.user_data.pop('await', None)
        context.user_data['build']['note'] = text[:500]
        await show_builder(message, context)
        return
    if awaiting and awaiting.startswith('msg_to:'):
        context.user_data.pop('await', None)
        await deliver_message(update, context, int(awaiting.split(':')[1]), text[:2000])
        return
    if awaiting in ('req_name', 'req_inn', 'req_details') and isinstance(context.user_data.get('req'), dict):
        req = context.user_data['req']
        if awaiting == 'req_name':
            if len(text.split()) < 2:
                await message.reply_text('Нужны фамилия и имя (и отчество, если есть).')
                return
            req['full_name'] = text.strip()[:120]
            context.user_data['await'] = 'req_inn'
            await message.reply_text('ИНН — 12 цифр.')
        elif awaiting == 'req_inn':
            inn = re.sub(r'\D', '', text)
            if not valid_inn(inn, req.get('legal_status')):
                await message.reply_text('ИНН не прошёл проверку — проверь 12 цифр и отправь ещё раз.')
                return
            req['inn'] = inn
            context.user_data.pop('await', None)
            await message.reply_text('Куда переводить?', reply_markup=kb([[(v, f'tr:rm:{k}')] for k, v in PAYOUT_METHODS.items()]))
        else:
            req['details'] = text.strip()[:200]
            context.user_data.pop('await', None)
            context.user_data.pop('req', None)
            if all(req.get(k) for k in ('legal_status', 'full_name', 'inn', 'method')):
                save_requisites(uid, req['legal_status'], req['full_name'], req['inn'], req['method'], req['details'])
                await message.reply_text('✅ Реквизиты сохранены. Выплата придёт в ближайший расчётный период.',
                                         reply_markup=kb([[('💰 Начисления', 'tr:money')]]))
        return
    if awaiting == 'ad_sub' and is_admin(uid):
        if await grant_subscription(message, context, text):
            context.user_data.pop('await', None)
        return
    if awaiting in ('onb_period', 'period_date'):
        d = parse_date(text)
        if not d:
            await message.reply_text('Не понял дату. Формат ДД.ММ, например 03.11 (не позже сегодня и не раньше 90 дней назад).')
            return
        context.user_data.pop('await', None)
        if awaiting == 'onb_period':
            context.user_data.setdefault('onb', {})['period_start'] = d.isoformat()
            await ask_cycle_len(message)
        else:
            log_period_start(uid, d)
            user = get_user(uid)
            await message.reply_text(cycle_screen_text(user), parse_mode=ParseMode.HTML,
                                     reply_markup=cycle_screen_kb(user))
        return
    if awaiting == 'measure':
        values = parse_measurements(text)
        if not values:
            await message.reply_text('Не понял. Отправь до 5 чисел в см через пробел: грудь талия бёдра рука бедро, '
                                     'например <code>100 80 95 35 55</code> («-» — пропустить) или /cancel.',
                                     parse_mode=ParseMode.HTML)
            return
        add_measurements(uid, values)
        context.user_data.pop('await', None)
        await message.reply_text('Записал ✅\n\n' + measurements_text(uid).split('\n\nНовый замер')[0],
                                 parse_mode=ParseMode.HTML)
        return
    if awaiting == 'bw':
        w = parse_weight(text)
        if w is None:
            await message.reply_text('Не понял вес. Отправь число от 20 до 400, например 78.4 (или /cancel).')
            return
        add_body_weight(uid, w)
        context.user_data.pop('await', None)
        await message.reply_text('Записал ✅\n\n' + weight_text(uid).rsplit('\n\n', 1)[0], parse_mode=ParseMode.HTML)
        return
    if awaiting == 'target_bw':
        t = text.replace(',', '.')
        w = 0.0 if t == '0' else parse_weight(t)
        if w is None:
            await message.reply_text('Отправь число от 20 до 400 (или 0, чтобы удалить цель).')
            return
        set_user_field(uid, 'target_weight', w or None)
        context.user_data.pop('await', None)
        await message.reply_text(goals_text(uid), parse_mode=ParseMode.HTML)
        return
    if awaiting and awaiting.startswith('target_ex:'):
        ex_id = awaiting.split(':', 1)[1]
        try:
            target = float(text.replace(',', '.').replace('кг', '').strip())
        except ValueError:
            target = -1
        if not 0 <= target <= 1000:
            await message.reply_text('Отправь число в кг, например 100 (или 0, чтобы удалить цель).')
            return
        set_exercise_goal(uid, ex_id, target)
        context.user_data.pop('await', None)
        await message.reply_text(goals_text(uid), parse_mode=ParseMode.HTML)
        return
    if awaiting in ('ws_weight',) or (awaiting or '').startswith('ws_bar:'):
        wk = context.user_data.get('wk')
        value = parse_weight_input(text)
        if wk is None:
            context.user_data.pop('await', None)
        elif value is None:
            await message.reply_text('Не понял вес. Отправь число в кг, например 42.5 (или /cancel).')
            return
        else:
            if awaiting.startswith('ws_bar:'):
                bar = float(awaiting.split(':')[1])
                total = bar + 2 * value
                note = f'Гриф {fmt_w(bar)} + 2 × {fmt_w(value)} = <b>{fmt_w(total)} кг</b>'
            else:
                total, note = value, f'Вес: <b>{fmt_w(value)} кг</b>'
            context.user_data.pop('await', None)
            await set_current_weight(message, context, uid, total, note)
            return
    if (awaiting or '').startswith('group_log:'):
        group_type = awaiting.split(':', 1)[1]
        if text.isdigit() and 5 <= int(text) <= 300 and group_type in GROUP_TYPES:
            context.user_data.pop('await', None)
            await save_past_group(message, uid, group_type, int(text))
        else:
            await message.reply_text('Отправь длительность в минутах, например 55 (или /cancel).')
        return
    wk = context.user_data.get('wk')
    if wk and wk.get('stage') == 'group':
        if text.isdigit() and 5 <= int(text) <= 300:
            await end_group_class(message, context, get_user(uid), int(text))
        else:
            await message.reply_text('Когда занятие закончится — нажми кнопку с минутами или отправь число, например 55.')
        return
    if wk and wk.get('stage', 'main') in ('warmup', 'cooldown'):
        if wk.get('cardio_kind') and text.isdigit() and 1 <= int(text) <= 180:
            await finish_cardio(message, context, get_user(uid), int(text))
        else:
            await message.reply_text('Выбери тренажёр кнопкой выше, отправь число минут или нажми «⏭ Пропустить».')
        return
    if wk:
        parsed = parse_set(text)
        if parsed and parsed[0] == 0 and '.' not in text and ',' not in text:
            # Одно число — это повторы с текущим выбранным весом.
            user = get_user(uid)
            p = wk_day(user, wk).exercises[wk['ex_pos']]
            parsed = (current_weight(user, wk, p), parsed[1])
        if not parsed:
            await message.reply_text('Не понял подход. Нажми кнопку с числом повторов или отправь «вес повторы», '
                                     'например <code>60 10</code>.', parse_mode=ParseMode.HTML)
            return
        await log_set(update, context, *parsed)
        return
    user = await need_profile(update, context)
    if user:
        await message.reply_text(f'Выбери действие в меню. Чтобы начать тренировку — «{BTN_TODAY}».',
                                 reply_markup=menu_for(user))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('await', None)
    await update.effective_message.reply_text('Ок, отменил ввод.', reply_markup=menu_for(get_user(update.effective_user.id)))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        '<b>Как пользоваться</b>\n\n'
        f'• «{BTN_TODAY}» — какие мышцы тренируем, упражнения, подходы, повторы, отдых и стартовые веса. '
        'Тренировка идёт по шагам: 🔥 разминка (кардио + суставная гимнастика) → упражнения → '
        '🧊 заминка (кардио + растяжка). Вес выбирай кнопками − / + (или 🧮 «Гриф + блины»), '
        'повторы — одной кнопкой. Можно и текстом: <code>60 10</code> — вес и повторы.\n'
        'Там же кнопка «🏠 Сегодня дома» / «🏢 Сегодня в зале» — упражнения подберутся под место '
        'только на сегодня.\n'
        '«👥 Групповая» — отметить групповое занятие (йога, пилатес, сайкл, зумба и др.): сейчас — '
        'с кардио-разминкой и заминкой, или уже прошедшее. Засчитывается в прогресс. Команда /group.\n'
        f'• «{BTN_PROGRAM}» — вся недельная программа.\n'
        f'• «{BTN_PROGRESS}» — статистика, личные рекорды, история.\n'
        f'• «{BTN_WEIGHT}» — дневник веса тела.\n'
        f'• «{BTN_GOALS}» — цели по весу тела и рабочим весам.\n'
        f'• «{BTN_CYCLE}» — учёт цикла (женский профиль): нагрузка подстраивается под фазу.\n'
        f'• «{BTN_SETTINGS}» — заполнить анкету заново, таймер отдыха.\n'
        '• «📖 Техника» — у каждого упражнения: как выполнять, дыхание, частые ошибки и фото.\n'
        '• «🔄 Заменить» — замени упражнение на другое для той же группы мышц (например, жим лёжа — на жим '
        'в тренажёре): только сегодня или навсегда. Вернуть исходные — в настройках.\n\n'
        'Команды: /today /group /program /progress /weight /goals /cycle /settings /finish /cancel',
        parse_mode=ParseMode.HTML, reply_markup=menu_for(get_user(update.effective_user.id)))


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Резервная копия базы — только для администратора (ADMIN_ID)."""
    if not is_admin(update.effective_user.id):
        return
    await send_backup(update.effective_message)


async def send_backup(message):
    if not DB_PATH.is_file():
        await message.reply_text('База ещё не создана.')
        return
    backup = DATA_DIR / f'backup_{now():%Y%m%d_%H%M}.db'
    with connect() as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    try:
        with open(backup, 'rb') as f:
            await message.reply_document(f, filename=backup.name,
                                                          caption=f'Резервная копия базы. Пользователей: {count_users()}')
    finally:
        backup.unlink(missing_ok=True)


def count_users():
    with connect() as c:
        return c.execute('SELECT COUNT(*) FROM users').fetchone()[0]


# ======================================================================
# Админ-панель: загрузка фото техники
# ======================================================================

GENDER_ICON = {'': '👨', 'f': '👩'}


def admin_stats_text():
    with connect() as c:
        users = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        workouts = c.execute('SELECT COUNT(*) FROM workouts WHERE finished_at IS NOT NULL').fetchone()[0]
        week = c.execute('SELECT COUNT(DISTINCT user_id) FROM workouts WHERE finished_at>=?',
                         ((now() - timedelta(days=7)).isoformat(timespec='seconds'),)).fetchone()[0]
    lines = ['<b>🛠 Админ-панель</b>', f'Версия бота: <code>{BOT_VERSION}</code>', '',
             f'👥 Пользователей: <b>{users}</b>',
             f'🏋️ Завершённых тренировок: <b>{workouts}</b>',
             f'🔥 Активных за 7 дней: <b>{week}</b>', '', '<b>📸 Фото техники</b>']
    for g, title in (('', 'Мужские'), ('f', 'Женские')):
        done = total = 0
        for ex in _EXERCISE_LIST:
            d, t = photo_coverage(ex.id, g)
            done, total = done + d, total + t
        lines.append(f'{GENDER_ICON[g]} {title}: <b>{done} из {total}</b>  {progress_bar(done / total if total else 0)}')
    return '\n'.join(lines)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.pop('await', None)
    await update.effective_message.reply_text(admin_stats_text(), parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())


def admin_menu_kb():
    return kb([[('📸 Фото упражнений', 'ad:groups')],
               [('🎓 Тренеры', 'ad:tr'), ('💳 Выдать подписку', 'ad:sub')],
               [('💸 Выплаты тренерам', 'ad:pay'), ('🖼 Фото для приложения', 'ad:hero')],
               [('💾 Резервная копия базы', 'ad:backup')]])


def coverage_mark(ex_id):
    total = frame_count(ex_id)
    done = photo_coverage(ex_id, '')[0] + photo_coverage(ex_id, 'f')[0]
    return '✅' if done == 2 * total else ('◐' if done else '▫️')


def admin_groups_kb():
    rows = []
    for key, name in GROUPS.items():
        exs = [e for e in _EXERCISE_LIST if e.group == key]
        total = sum(frame_count(e.id) for e in exs)
        m = sum(photo_coverage(e.id, '')[0] for e in exs)
        f = sum(photo_coverage(e.id, 'f')[0] for e in exs)
        rows.append([(f'{name} — 👨 {m}/{total} · 👩 {f}/{total}', f'ad:g:{key}')])
    rows.append([('⬅️ Назад', 'ad:menu')])
    return kb(rows)


def admin_group_kb(group):
    rows = [[(f'{coverage_mark(e.id)} {e.name}', f'ad:e:{e.id}')] for e in _EXERCISE_LIST if e.group == group]
    rows.append([('⬅️ К группам мышц', 'ad:groups')])
    return kb(rows)


def admin_exercise_text(ex):
    stored = db_photos(ex.id)
    lines = [f'<b>📸 {html.escape(ex.name)}</b> (<code>{ex.id}</code>)', '',
             'Для каждого кадра нужны два реалистичных фото: 👨 с мужчиной и 👩 с женщиной. '
             'Мужчины увидят в «Технике» мужские фото, девушки — женские.', '',
             'Нажми «📤 Кадр N 👨/👩» — бот пришлёт промт этого кадра, потом отправь сгенерированное фото.', '']
    for i, (caption, _) in enumerate(EXERCISE_FRAMES[ex.id][1], 1):
        status = '  ·  '.join(f'{GENDER_ICON[g]} {"✅" if photo_source(ex.id, i, g, stored) else "▫️"}' for g in ('', 'f'))
        lines += [f'<b>Кадр {i}.</b> {html.escape(caption)}', status, '']
    lines.append('Все промты сразу — кнопками ниже.')
    return '\n'.join(lines)


def admin_prompts_text(ex, lang, gender):
    """Промты всех кадров упражнения: lang — 'ru' или 'en', gender — '' (мужчина) или 'f' (женщина)."""
    female = gender == 'f'
    title = f'{GENDER_ICON[gender]} {"Женщина" if female else "Мужчина"} · {"русский" if lang == "ru" else "English"}'
    lines = [f'<b>{html.escape(ex.name)}</b> — {title}', '']
    for i, (caption, _) in enumerate(EXERCISE_FRAMES[ex.id][1], 1):
        prompt = build_prompt_ru(ex.id, i - 1, female) if lang == 'ru' else build_prompt(ex.id, i - 1, female)
        lines += [f'<b>Кадр {i}.</b> {html.escape(caption)}', f'<code>{html.escape(prompt)}</code>', '']
    lines.append('Нажми на промт, чтобы скопировать.')
    return '\n'.join(lines)


def admin_exercise_kb(ex):
    stored = db_photos(ex.id)
    rows = []
    for i in range(1, frame_count(ex.id) + 1):
        rows.append([(f'📤 Кадр {i} 👨', f'ad:up:{ex.id}:{i}:'), (f'📤 Кадр {i} 👩', f'ad:up:{ex.id}:{i}:f')])
        dels = [(f'🗑 Кадр {i} {GENDER_ICON[g]}', f'ad:del:{ex.id}:{i}:{g}') for g in ('', 'f') if (i, g) in stored]
        if dels:
            rows.append(dels)
    rows.append([('📝 Промты 👨', f'ad:pr:{ex.id}:ru:'), ('📝 Промты 👩', f'ad:pr:{ex.id}:ru:f')])
    rows.append([('🇬🇧 Prompts 👨', f'ad:pr:{ex.id}:en:'), ('🇬🇧 Prompts 👩', f'ad:pr:{ex.id}:en:f')])
    rows.append([('👁 Как видит мужчина', f'ad:pv:{ex.id}:'), ('👁 Как видит девушка', f'ad:pv:{ex.id}:f')])
    rows.append([('⬅️ К упражнениям', f'ad:g:{ex.group}')])
    return kb(rows)


async def show_admin_exercise(message, ex):
    await message.reply_text(admin_exercise_text(ex), parse_mode=ParseMode.HTML, reply_markup=admin_exercise_kb(ex))


def ask_photo_text(ex, frame, gender):
    caption = EXERCISE_FRAMES[ex.id][1][frame - 1][0]
    female = gender == 'f'
    who = 'женская версия 👩' if female else 'мужская версия 👨'
    return (f'📤 Отправь фото для «{html.escape(ex.name)}», кадр {frame} ({who}):\n{html.escape(caption)}\n\n'
            f'🇷🇺 Промт:\n<code>{html.escape(build_prompt_ru(ex.id, frame - 1, female))}</code>\n\n'
            f'🇬🇧 Prompt:\n<code>{html.escape(build_prompt(ex.id, frame - 1, female))}</code>\n\n'
            'Можно обычным фото или файлом. /cancel — отменить.')


async def admin_callback(data, update, context):
    uid = update.effective_user.id
    message = update.callback_query.message
    if not is_admin(uid):
        return
    parts = data.split(':')
    if data == 'ad:menu':
        await message.reply_text(admin_stats_text(), parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    elif data == 'ad:backup':
        await send_backup(message)
    elif data == 'ad:tr':
        text, pending = admin_trainers_text()
        rows = [[(f'✅ {display_name(p)}', f'ad:tok:{p["user_id"]}'), ('❌', f'ad:tno:{p["user_id"]}')] for p in pending]
        rows.append([('🔗 Ссылка-приглашение для тренера', 'ad:tinv')])
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb(rows))
    elif data == 'ad:tinv':
        code = create_trainer_invite(uid)
        url = f'https://t.me/{context.bot.username}?start=coach_{code}'
        await message.reply_text(f'🔗 Ссылка-приглашение для тренера:\n<code>{url}</code>\n\n'
                                 'Отправь её тренеру — по ней он сразу получит кабинет тренера, без заявки. '
                                 'Ссылка одноразовая: для каждого тренера создай новую.',
                                 parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    elif data == 'ad:sub':
        context.user_data['await'] = 'ad_sub'
        await message.reply_text(SUB_HELP, parse_mode=ParseMode.HTML)
    elif data == 'ad:hero':
        await message.reply_text(admin_hero_text(), parse_mode=ParseMode.HTML, reply_markup=admin_hero_kb())
    elif parts[1] in ('hs', 'hu', 'hd') and len(parts) == 3 and parts[2] in APP_PHOTOS:
        key = parts[2]
        if parts[1] == 'hs':
            text, markup = admin_photo_slot(key)
            await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        elif parts[1] == 'hu':
            context.user_data['await'] = f'hero:{key}'
            await message.reply_text(f'Отправь фото «{APP_PHOTOS[key][0]}» — лучше файлом, без сжатия. /cancel — отмена.')
        else:
            delete_app_photo(*_split(key))
            await message.reply_text('🗑 Фото удалено.\n\n' + admin_hero_text(), parse_mode=ParseMode.HTML,
                                     reply_markup=admin_hero_kb())
    elif data == 'ad:pay':
        await message.reply_text(admin_payouts_text(), parse_mode=ParseMode.HTML, reply_markup=admin_payouts_kb())
    elif data == 'ad:payreg':
        created, missing = create_payout_registry()
        for tid, total in missing:
            await notify(context.bot, tid, f'💰 У тебя {money(total)} к выплате, но не заполнены реквизиты. '
                                           'Кабинет → «💰 Начисления и выплаты» → «🧾 Реквизиты».')
        ids = [p['id'] for p in open_payouts()]
        if ids:
            await message.reply_document(registry_csv(ids), filename=f'payouts_{now():%Y-%m-%d}.csv',
                                         caption='Реестр выплат (открывается в Excel). После перевода отметь каждую выплату.')
        note = f'Новых выплат: {len(created)}.'
        if missing:
            note += f' Без реквизитов: {len(missing)} — им отправлено напоминание.'
        await message.reply_text(note + '\n\n' + admin_payouts_text(), parse_mode=ParseMode.HTML,
                                 reply_markup=admin_payouts_kb())
    elif parts[1] == 'paid' and len(parts) == 3 and parts[2].isdigit():
        p = mark_payout_paid(int(parts[2]))
        if not p:
            await message.reply_text('Эта выплата уже отмечена.')
            return
        await notify(context.bot, p['trainer_id'], f'💸 Выплата <b>{money(p["amount"])}</b> отправлена '
                                                   f'({PAYOUT_METHODS.get(p["method"], "")} {mask(p["details"])}). '
                                                   'Не забудь сформировать чек, если ты самозанятый 🧾')
        await message.reply_text(f'✅ Выплата №{p["id"]} отмечена.\n\n' + admin_payouts_text(), parse_mode=ParseMode.HTML,
                                 reply_markup=admin_payouts_kb())
    elif parts[1] in ('tok', 'tno') and len(parts) == 3 and parts[2].isdigit():
        tid = int(parts[2])
        target = get_user(tid)
        if not target:
            return
        if parts[1] == 'tok':
            make_trainer(tid)
            await notify(context.bot, tid, '🎉 Заявка одобрена! Ты в партнёрской программе. '
                                           f'Кабинет — кнопка «{BTN_CABINET}» в меню (или /trainer).',
                         menu_for(get_user(tid)))
            await message.reply_text(f'✅ {display_name(target)} теперь тренер.')
        else:
            set_user_field(tid, 'trainer_status', 'rejected')
            await notify(context.bot, tid, 'К сожалению, заявка в партнёрскую программу отклонена.')
            await message.reply_text(f'Заявка {display_name(target)} отклонена.')
    elif data == 'ad:groups':
        await message.reply_text('Выбери группу мышц (загружено / всего кадров):', reply_markup=admin_groups_kb())
    elif parts[1] == 'g' and len(parts) == 3 and parts[2] in GROUPS:
        await message.reply_text(f'<b>{GROUPS[parts[2]]}</b>: ✅ все фото · ◐ часть · ▫️ нет фото',
                                 parse_mode=ParseMode.HTML, reply_markup=admin_group_kb(parts[2]))
    elif parts[1] == 'e' and len(parts) == 3 and parts[2] in EXERCISES:
        await show_admin_exercise(message, EXERCISES[parts[2]])
    elif parts[1] == 'pr' and len(parts) == 5 and parts[2] in EXERCISES and parts[3] in ('ru', 'en') \
            and parts[4] in ('', 'f'):
        await message.reply_text(admin_prompts_text(EXERCISES[parts[2]], parts[3], parts[4]), parse_mode=ParseMode.HTML)
    elif parts[1] == 'pv' and len(parts) == 4 and parts[2] in EXERCISES and parts[3] in ('', 'f'):
        # Предпросмотр «Техники» глазами мужчины или девушки.
        preview_user = dict(get_user(uid) or {'user_id': uid}, gender='f' if parts[3] == 'f' else 'm')
        await send_technique(message, EXERCISES[parts[2]], preview_user)
    elif parts[1] in ('up', 'del') and len(parts) == 5 and parts[2] in EXERCISES and parts[3].isdigit():
        ex, frame, gender = EXERCISES[parts[2]], int(parts[3]), parts[4]
        if not 1 <= frame <= frame_count(ex.id) or gender not in ('', 'f'):
            return
        if parts[1] == 'up':
            context.user_data['await'] = f'photo:{ex.id}:{frame}:{gender}'
            await message.reply_text(ask_photo_text(ex, frame, gender), parse_mode=ParseMode.HTML)
        else:
            delete_photo(ex.id, frame, gender)
            await message.reply_text(f'🗑 Фото кадра {frame} удалено.')
            await show_admin_exercise(message, ex)


async def save_hero_from_message(message, context, key):
    if key in HERO_GENDERS:  # старый формат ожидания
        key = f'home_{key}'
    if key not in APP_PHOTOS:
        context.user_data.pop('await', None)
        return
    if message.photo:
        tg_file, mime = await message.photo[-1].get_file(), 'image/jpeg'
    elif message.document and (message.document.mime_type or '') in ('image/jpeg', 'image/png', 'image/webp'):
        tg_file, mime = await message.document.get_file(), message.document.mime_type
    else:
        await message.reply_text('Нужна картинка JPG, PNG или WEBP.')
        return
    data = bytes(await tg_file.download_as_bytearray())
    if len(data) > 6 * 1024 * 1024:
        await message.reply_text('Файл больше 6 МБ — сожми его и отправь ещё раз.')
        return
    save_app_photo(*_split(key), data, mime)
    context.user_data.pop('await', None)
    await message.reply_text(f'✅ «{APP_PHOTOS[key][0]}» сохранено — фото уже в приложении.\n\n'
                             + admin_hero_text(), parse_mode=ParseMode.HTML, reply_markup=admin_hero_kb())


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фото от администратора → картинка техники упражнения."""
    uid = update.effective_user.id
    message = update.effective_message
    if not is_admin(uid):
        return
    target = None
    awaiting = context.user_data.get('await') or ''
    if awaiting.startswith('hero:'):
        await save_hero_from_message(message, context, awaiting.split(':', 1)[1])
        return
    # Быстрый способ: фото с подписью «bench 1» или «bench 1 f» (подпись важнее ожидаемого кадра).
    m = re.fullmatch(r'\s*([a-z_]+)[\s_]+(\d)(?:[\s_]+(f|ж|m|м))?\s*', (message.caption or '').lower())
    if m and m.group(1) in EXERCISES and 1 <= int(m.group(2)) <= frame_count(m.group(1)):
        target = (m.group(1), int(m.group(2)), 'f' if m.group(3) in ('f', 'ж') else '')
    elif awaiting.startswith('photo:'):
        _, ex_id, frame, gender = awaiting.split(':')
        target = (ex_id, int(frame), gender)
    if not target:
        await message.reply_text('Чтобы добавить фото к упражнению: «🛠 Админ» → «📸 Фото упражнений», '
                                 'или отправь фото с подписью вида <code>bench 1</code> (мужская версия 👨) '
                                 'или <code>bench 1 f</code> (женская версия 👩).', parse_mode=ParseMode.HTML)
        return
    ex_id, frame, gender = target
    ex = EXERCISES[ex_id]
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or '').startswith('image/'):
        # Файл без сжатия → перезагружаем как фото, чтобы его можно было показывать в альбоме.
        tg_file = await message.document.get_file()
        data = await tg_file.download_as_bytearray()
        sent = await message.reply_photo(bytes(data), caption='Файл преобразован в фото')
        file_id = sent.photo[-1].file_id
    else:
        await message.reply_text('Это не картинка. Отправь фото (png, jpg, webp).')
        return
    save_photo(ex_id, frame, gender, file_id)
    text = f'✅ Сохранено: «{ex.name}», кадр {frame} {GENDER_ICON[gender]}.'
    stored = db_photos(ex_id)
    nxt = next((i for i in range(1, frame_count(ex_id) + 1) if (i, gender) not in stored
                and not photo_source(ex_id, i, gender, stored)), None)
    if nxt:
        context.user_data['await'] = f'photo:{ex_id}:{nxt}:{gender}'
        await message.reply_text(html.escape(text) + '\n\n' + ask_photo_text(ex, nxt, gender), parse_mode=ParseMode.HTML)
    else:
        context.user_data.pop('await', None)
        await message.reply_text(text + f' Все кадры {GENDER_ICON[gender]} этого упражнения загружены 🎉')
        await show_admin_exercise(message, ex)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_panel(update, context)


async def group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await need_profile(update, context):
        return
    if context.user_data.get('wk'):
        await update.effective_message.reply_text('Сначала заверши текущую тренировку.')
        return
    await update.effective_message.reply_text('👥 Какая групповая тренировка?', reply_markup=group_types_kb())


async def finish_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await finish_workout(update.effective_message, context, update.effective_user.id)


async def on_error(update, context):
    if isinstance(context.error, Conflict):
        log.error('Конфликт: этот же бот уже запущен в другом месте (на компьютере или втором сервере). '
                  'Оставь только один запуск.')
        return
    log.error('Ошибка обработки update', exc_info=context.error)


# ======================================================================
# Тренеры: реферальная программа, подопечные, назначенные тренировки, сообщения
# ======================================================================

# (название, от скольких подписчиков, % от подписки, описание)
TRAINER_LEVELS = [
    ('🤝 PARTNER', 0, 20, 'Любой тренер, вступивший в программу'),
    ('🥈 SILVER', 10, 25, 'Тренер с постоянными рекомендациями'),
    ('🥇 GOLD', 30, 30, 'Активный партнёр с собственной аудиторией'),
    ('👑 AMBASSADOR', 100, 40, 'Крупный партнёр, который приводит стабильный поток'),
]
REP_PRESETS = [(5, 5), (6, 8), (8, 10), (10, 12), (12, 15), (15, 20)]
SEC_PRESETS = [(30, 30), (45, 45), (60, 60), (30, 60)]


def sub_price():
    try:
        return float((os.environ.get('SUB_PRICE') or '0').replace(',', '.'))
    except ValueError:
        return 0.0


def trainer_level(subscribers):
    """(номер уровня, уровень) по числу подписчиков."""
    idx = max(i for i, lvl in enumerate(TRAINER_LEVELS) if subscribers >= lvl[1])
    return idx, TRAINER_LEVELS[idx]


def today_iso():
    return now().date().isoformat()


def has_subscription(user):
    return bool(user and user.get('sub_until') and user['sub_until'] >= today_iso())


def is_trainer(user):
    return bool(user and user.get('is_trainer'))


def display_name(user, fallback='Пользователь'):
    return (user or {}).get('name') or fallback


def ensure_user_row(uid, name):
    """Строка пользователя без анкеты — нужна тренерам и пришедшим по ссылке до заполнения анкеты."""
    with connect() as c:
        c.execute('INSERT OR IGNORE INTO users(user_id, name, day_index, created_at) VALUES(?,?,0,?)',
                  (uid, name, now().isoformat(timespec='seconds')))
        c.execute("UPDATE users SET name=? WHERE user_id=? AND (name IS NULL OR name='')", (name, uid))


def referral_stats(tid):
    """(приглашено всего, из них с активной подпиской)."""
    with connect() as c:
        invited = c.execute('SELECT COUNT(*) FROM users WHERE referred_by=?', (tid,)).fetchone()[0]
        subs = c.execute('SELECT COUNT(*) FROM users WHERE referred_by=? AND sub_until>=?',
                         (tid, today_iso())).fetchone()[0]
    return invited, subs


def trainer_clients(tid):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM users WHERE trainer_id=? ORDER BY name', (tid,))]


def create_ref_link(tid, label):
    alphabet = 'abcdefghijkmnpqrstuvwxyz23456789'
    with connect() as c:
        for _ in range(20):
            code = ''.join(secrets.choice(alphabet) for _ in range(8))
            if not c.execute('SELECT 1 FROM ref_links WHERE code=?', (code,)).fetchone():
                c.execute('INSERT INTO ref_links(code, trainer_id, label, created_at) VALUES(?,?,?,?)',
                          (code, tid, label, now().isoformat(timespec='seconds')))
                return code
    raise RuntimeError('Не удалось создать код ссылки')


def get_ref_link(code):
    with connect() as c:
        row = c.execute('SELECT * FROM ref_links WHERE code=?', (code,)).fetchone()
    return dict(row) if row else None


def trainer_links(tid):
    with connect() as c:
        return [dict(r) for r in c.execute(
            '''SELECT l.*, (SELECT COUNT(*) FROM users u WHERE u.ref_code=l.code) AS joined,
                      (SELECT COUNT(*) FROM users u WHERE u.ref_code=l.code AND u.sub_until>=?) AS subs
               FROM ref_links l WHERE l.trainer_id=? ORDER BY l.created_at''', (today_iso(), tid))]


def save_assignment(tid, cid, date_iso, title, note, items):
    with connect() as c:
        cur = c.execute('''INSERT INTO assignments(trainer_id, client_id, date, title, note, items, status, created_at)
                           VALUES(?,?,?,?,?,?, 'pending', ?)''',
                        (tid, cid, date_iso, title, note, json.dumps(items), now().isoformat(timespec='seconds')))
        return cur.lastrowid


def get_assignment(aid):
    with connect() as c:
        row = c.execute('SELECT * FROM assignments WHERE id=?', (aid,)).fetchone()
    if not row:
        return None
    a = dict(row)
    a['items'] = json.loads(a['items'] or '[]')
    return a


def client_assignments(cid, status='pending', until=None):
    q = 'SELECT id FROM assignments WHERE client_id=? AND status=?'
    args = [cid, status]
    if until:
        q += ' AND date<=?'
        args.append(until)
    with connect() as c:
        ids = [r[0] for r in c.execute(q + ' ORDER BY date, id', args)]
    return [get_assignment(i) for i in ids]


def set_assignment_status(aid, status, wid=None):
    with connect() as c:
        c.execute('UPDATE assignments SET status=?, workout_id=COALESCE(?, workout_id) WHERE id=?', (status, wid, aid))


# ---------- Каталог тренеров: профили, заявки, отзывы ----------

SPECIALIZATIONS = {
    'mass': 'Набор массы', 'fat_loss': 'Похудение', 'strength': 'Сила', 'fit': 'Тонус и здоровье',
    'beginners': 'Для новичков', 'women': 'Для женщин', 'mature': '40+ и 60+', 'rehab': 'Спина и реабилитация',
    'home': 'Тренировки дома',
}
TRAINER_FORMATS = {'online': 'Онлайн', 'offline': 'В зале', 'both': 'Онлайн и в зале'}
REVIEW_MIN_WORKOUTS = 3
REVIEW_MIN_DAYS = 14
TRAINER_PROFILE_FIELDS = ('bio', 'specializations', 'experience_years', 'certificates', 'city', 'format',
                          'max_clients', 'listed')


def start_coaching(client_id, trainer_id):
    """Подопечный подключился к тренеру (по ссылке или через принятую заявку)."""
    stamp = now().isoformat(timespec='seconds')
    set_user_field(client_id, 'trainer_id', trainer_id)
    with connect() as c:
        c.execute('UPDATE coaching SET ended_at=? WHERE client_id=? AND ended_at IS NULL', (stamp, client_id))
        c.execute('INSERT INTO coaching(trainer_id, client_id, started_at) VALUES(?,?,?)', (trainer_id, client_id, stamp))
        c.execute("UPDATE coach_requests SET status='cancelled', decided_at=? WHERE client_id=? AND status='pending'",
                  (stamp, client_id))


def end_coaching(client_id):
    set_user_field(client_id, 'trainer_id', None)
    with connect() as c:
        c.execute('UPDATE coaching SET ended_at=? WHERE client_id=? AND ended_at IS NULL',
                  (now().isoformat(timespec='seconds'), client_id))


def get_trainer_profile(tid):
    with connect() as c:
        row = c.execute('SELECT * FROM trainer_profiles WHERE user_id=?', (tid,)).fetchone()
        photo = c.execute('SELECT updated_at FROM trainer_photos WHERE user_id=?', (tid,)).fetchone()
    p = dict(row) if row else {'user_id': tid, 'bio': '', 'specializations': '[]', 'experience_years': None,
                                'certificates': '', 'city': '', 'format': 'both', 'max_clients': None, 'listed': 1}
    p['specializations'] = json.loads(p.get('specializations') or '[]')
    p['photo_version'] = photo['updated_at'] if photo else None
    return p


def save_trainer_profile(tid, data):
    values = {k: data.get(k) for k in TRAINER_PROFILE_FIELDS}
    values['specializations'] = json.dumps([x for x in (data.get('specializations') or []) if x in SPECIALIZATIONS])
    values['listed'] = 1 if data.get('listed', True) else 0
    cols = ', '.join(TRAINER_PROFILE_FIELDS)
    marks = ', '.join('?' for _ in TRAINER_PROFILE_FIELDS)
    updates = ', '.join(f'{k}=excluded.{k}' for k in TRAINER_PROFILE_FIELDS)
    sql = (f'INSERT INTO trainer_profiles(user_id, {cols}, updated_at) VALUES(?, {marks}, ?) '
           f'ON CONFLICT(user_id) DO UPDATE SET {updates}, updated_at=excluded.updated_at')
    with connect() as c:
        c.execute(sql, (tid, *[values[k] for k in TRAINER_PROFILE_FIELDS], now().isoformat(timespec='seconds')))


# ---------- Объёмы тела ----------
MEASURES = {'chest': 'Грудь', 'waist': 'Талия', 'hips': 'Бёдра', 'arm': 'Рука (бицепс)', 'thigh': 'Бедро (нога)'}


def add_measurements(uid, values):
    """values: {поле: см}; пустые поля можно не передавать."""
    clean = {k: round(float(v), 1) for k, v in values.items() if k in MEASURES and v and 20 <= float(v) <= 250}
    if not clean:
        return None
    with connect() as c:
        return c.execute(f'INSERT INTO body_measurements(user_id, {", ".join(clean)}, created_at) '
                         f'VALUES(?, {", ".join("?" * len(clean))}, ?)',
                         (uid, *clean.values(), now().isoformat(timespec='seconds'))).lastrowid


def measurements(uid):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM body_measurements WHERE user_id=? ORDER BY created_at, id', (uid,))]


def delete_measurement(uid, mid):
    with connect() as c:
        return c.execute('DELETE FROM body_measurements WHERE id=? AND user_id=?', (mid, uid)).rowcount


def measurements_summary(uid):
    """По каждому объёму: текущее значение, изменение к предыдущему замеру и к первому."""
    rows = measurements(uid)
    out = {}
    for k in MEASURES:
        vals = [(r['created_at'][:10], r[k]) for r in rows if r.get(k)]
        if vals:
            out[k] = {'value': vals[-1][1], 'date': vals[-1][0],
                      'prev_delta': round(vals[-1][1] - vals[-2][1], 1) if len(vals) > 1 else None,
                      'total_delta': round(vals[-1][1] - vals[0][1], 1) if len(vals) > 1 else None,
                      'history': [{'date': d, 'value': v} for d, v in vals]}
    return out


def parse_measurements(text):
    """«100 80 95 35 55» (грудь талия бёдра рука бедро; «-» — пропустить) → {поле: см} или None."""
    parts = re.split(r'[\s;/]+', (text or '').strip().replace(',', '.'))
    if not 1 <= len(parts) <= 5:
        return None
    values = {}
    for key, p in zip(MEASURES, parts):
        if p in ('-', '—', '0'):
            continue
        try:
            v = float(p)
        except ValueError:
            return None
        if not 20 <= v <= 250:
            return None
        values[key] = v
    return values or None


def measurements_text(uid):
    summary = measurements_summary(uid)
    lines = ['<b>📏 Объёмы тела</b>', '']
    if not summary:
        lines.append('Замеров пока нет.')
    for k, label in MEASURES.items():
        if k in summary:
            m = summary[k]
            delta = f' ({"+" if m["total_delta"] > 0 else ""}{fmt_w(m["total_delta"])} см с начала)' if m['total_delta'] else ''
            lines.append(f'{label}: <b>{fmt_w(m["value"])} см</b>{delta}')
    lines += ['', 'Новый замер — отправь числа в сантиметрах через пробел в порядке:\n'
              '<b>грудь талия бёдра рука бедро</b>\nНапример: <code>100 80 95 35 55</code>. '
              'Что не мерил(а) — поставь «-». Мерить лучше утром, натощак, раз в 2–4 недели.']
    return '\n'.join(lines)


# ---------- Фото для приложения (главная, вход, итог тренировки, тренер, друзья) ----------
# Ключ — «место_пол»: u — для всех/до выбора пола, m — мужская версия, f — женская.
APP_PHOTOS = {
    'home_u': ('👫 Главная и вход — пара', 'экран входа, первый шаг анкеты, главная до выбора пола'),
    'home_m': ('👨 Главная — мужчина', 'главная, карточка «Тренировка дня»'),
    'home_f': ('👩 Главная — женщина', 'главная, карточка «Тренировка дня»'),
    'done_m': ('🏁 Итог тренировки — мужчина', 'экран после завершения тренировки'),
    'done_f': ('🏁 Итог тренировки — женщина', 'экран после завершения тренировки'),
    'coach_u': ('🎓 Занятия с тренером', 'раздел «Тренер» и каталог тренеров'),
    'friends_u': ('🤝 Тренируйся с другом', 'экран «Друзья»'),
}
HERO_GENDERS = {'m': '👨 мужская', 'f': '👩 женская', 'u': '👫 общая'}


def _split(key):
    slot, g = key.rsplit('_', 1)
    return slot, g


def save_app_photo(slot, gender, data, mime):
    with connect() as c:
        c.execute('INSERT OR REPLACE INTO app_photos(slot, gender, data, mime, updated_at) VALUES(?,?,?,?,?)',
                  (slot, gender, data, mime, now().isoformat(timespec='seconds')))


# Фото «из коробки» лежат в assets/photos/<ключ>.jpg; загруженное админом в боте их заменяет.
BUNDLED_PHOTOS = Path(__file__).resolve().parent / 'assets' / 'photos'


def bundled_photo(key):
    path = BUNDLED_PHOTOS / f'{key}.jpg'
    if key not in APP_PHOTOS or not path.is_file():
        return None
    import hashlib
    data = path.read_bytes()
    return {'data': data, 'mime': 'image/jpeg', 'updated_at': 'b' + hashlib.sha1(data).hexdigest()[:10]}


def get_app_photo(slot, gender):
    with connect() as c:
        row = c.execute('SELECT data, mime, updated_at FROM app_photos WHERE slot=? AND gender=?', (slot, gender)).fetchone()
    return dict(row) if row else bundled_photo(f'{slot}_{gender}')


def app_photo_version(slot, gender):
    with connect() as c:
        row = c.execute('SELECT updated_at FROM app_photos WHERE slot=? AND gender=?', (slot, gender)).fetchone()
    if row:
        return row[0]
    b = bundled_photo(f'{slot}_{gender}')
    return b['updated_at'] if b else None


def app_photo_versions():
    """{ключ: версия} всех доступных фото: загруженные админом и встроенные."""
    out = {k: v for k in APP_PHOTOS if (v := app_photo_version(*_split(k)))}
    return out


def delete_app_photo(slot, gender):
    with connect() as c:
        c.execute('DELETE FROM app_photos WHERE slot=? AND gender=?', (slot, gender))


def photo_prompt(key, lang='RU'):
    """Промт из MODEL_PHOTO_PROMPTS.md: раздел с `ключом` в заголовке, абзац **RU:** или **EN:**."""
    text = (Path(__file__).resolve().parent / 'MODEL_PHOTO_PROMPTS.md').read_text(encoding='utf-8')
    section = next((sec for sec in text.split('\n## ') if f'`{key}`' in sec.split('\n', 1)[0]), '')
    if not section and key == 'done_f':
        section = next((sec for sec in text.split('\n## ') if '`done_f`' in sec), '')
    part = section.split(f'**{lang}:**', 1)[-1] if f'**{lang}:**' in section else ''
    return ' '.join(part.split('**EN:**')[0].split()) if part else ''


def hero_prompt(gender):  # совместимость
    return photo_prompt(f'home_{gender}')


def admin_hero_kb():
    have = app_photo_versions()
    rows = [[(f'{"✅" if k in have else "▫️"} {label}', f'ad:hs:{k}')] for k, (label, _) in APP_PHOTOS.items()]
    rows.append([('⬅️ Админка', 'ad:menu')])
    return kb(rows)


def admin_hero_text():
    have = app_photo_versions()
    return ('<b>🖼 Фото для приложения</b>\n\n'
            f'Загружено {sum(k in have for k in APP_PHOTOS)} из {len(APP_PHOTOS)}. Формат — горизонтальный 16:10, 4K, '
            'люди справа, слева тёмное место под текст. Пока фото нет, экран выглядит как обычно.\n\n'
            'Выбери место — покажу промт для генерации и кнопку загрузки.')


def admin_photo_slot(key):
    label, where = APP_PHOTOS[key]
    v = app_photo_version(*_split(key))
    status = ('✅ встроенное фото (можно заменить)' if v and v.startswith('b') else f'✅ загружено {v[:10]}' if v else '— нет')
    text = (f'<b>{label}</b>\nГде: {where}\nСтатус: {status}' +
            f'\n\n<b>Промт:</b>\n{html.escape(photo_prompt(key))}\n\n'
            '<i>Английская версия промта — в файле MODEL_PHOTO_PROMPTS.md.</i>')
    rows = [[('📤 Загрузить', f'ad:hu:{key}')] + ([('🗑 Удалить загруженное', f'ad:hd:{key}')] if v and not v.startswith('b') else []),
            [('⬅️ Все фото', 'ad:hero')]]
    return text, kb(rows)


def save_trainer_photo(tid, data, mime):
    with connect() as c:
        c.execute('INSERT OR REPLACE INTO trainer_photos(user_id, data, mime, updated_at) VALUES(?,?,?,?)',
                  (tid, data, mime, now().isoformat(timespec='seconds')))


def get_trainer_photo(tid):
    with connect() as c:
        row = c.execute('SELECT data, mime FROM trainer_photos WHERE user_id=?', (tid,)).fetchone()
    return (row['data'], row['mime']) if row else (None, None)


def trainer_rating(tid):
    """(средняя оценка, число отзывов)."""
    with connect() as c:
        row = c.execute('SELECT AVG(rating), COUNT(*) FROM reviews WHERE trainer_id=?', (tid,)).fetchone()
    return (round(row[0], 1) if row[0] else None), row[1]


def trainer_reviews(tid, limit=20):
    sql = ('SELECT r.*, u.name FROM reviews r LEFT JOIN users u ON u.user_id=r.client_id '
           'WHERE r.trainer_id=? ORDER BY r.updated_at DESC LIMIT ?')
    with connect() as c:
        return [dict(r) for r in c.execute(sql, (tid, limit))]


def can_review(client_id, tid):
    """Отзыв оставляют только реальные подопечные: 3+ тренировки от тренера или 2+ недели вместе."""
    with connect() as c:
        done = c.execute("SELECT COUNT(*) FROM assignments WHERE client_id=? AND trainer_id=? AND status='done'",
                         (client_id, tid)).fetchone()[0]
        if done >= REVIEW_MIN_WORKOUTS:
            return True
        rows = c.execute('SELECT started_at, ended_at FROM coaching WHERE client_id=? AND trainer_id=?',
                         (client_id, tid)).fetchall()
    for r in rows:
        end = datetime.fromisoformat(r['ended_at']) if r['ended_at'] else now()
        if (end - datetime.fromisoformat(r['started_at'])).days >= REVIEW_MIN_DAYS:
            return True
    return False


def save_review(tid, client_id, rating, text):
    stamp = now().isoformat(timespec='seconds')
    sql = ('INSERT INTO reviews(trainer_id, client_id, rating, text, created_at, updated_at) VALUES(?,?,?,?,?,?) '
           'ON CONFLICT(trainer_id, client_id) DO UPDATE SET rating=excluded.rating, text=excluded.text, '
           'updated_at=excluded.updated_at')
    with connect() as c:
        c.execute(sql, (tid, client_id, rating, text, stamp, stamp))


def create_coach_request(client_id, tid, message):
    with connect() as c:
        row = c.execute("SELECT id FROM coach_requests WHERE client_id=? AND trainer_id=? AND status='pending'",
                        (client_id, tid)).fetchone()
        if row:
            return row[0]
        cur = c.execute('INSERT INTO coach_requests(client_id, trainer_id, message, created_at) VALUES(?,?,?,?)',
                        (client_id, tid, message, now().isoformat(timespec='seconds')))
        return cur.lastrowid


def get_coach_request(rid):
    with connect() as c:
        row = c.execute('SELECT * FROM coach_requests WHERE id=?', (rid,)).fetchone()
    return dict(row) if row else None


def pending_requests(tid=None, client_id=None):
    q, args = "SELECT * FROM coach_requests WHERE status='pending'", []
    if tid is not None:
        q += ' AND trainer_id=?'
        args.append(tid)
    if client_id is not None:
        q += ' AND client_id=?'
        args.append(client_id)
    with connect() as c:
        return [dict(r) for r in c.execute(q + ' ORDER BY id', args)]


def set_request_status(rid, status):
    with connect() as c:
        c.execute('UPDATE coach_requests SET status=?, decided_at=? WHERE id=?',
                  (status, now().isoformat(timespec='seconds'), rid))


def trainer_has_room(tid):
    limit = get_trainer_profile(tid).get('max_clients')
    return not limit or len(trainer_clients(tid)) < limit


def request_text(req):
    client = get_user(req['client_id'])
    lines = [f'📝 <b>Заявка на ведение</b> от <b>{html.escape(display_name(client))}</b>']
    if profile_complete(client):
        lines.append(f'{GENDERS[client["gender"]]}, {AGES[client["age"]]} · {GOALS[client["goal"]]} · '
                     f'{LEVELS[client["level"]].split(":")[0]} · {client["days"]} трен./нед.')
    if req.get('message'):
        lines.append(f'💬 {html.escape(req["message"])}')
    return '\n'.join(lines)


async def decide_coach_request(bot, trainer, rid, accept):
    """Тренер принимает или отклоняет заявку. Возвращает текст результата для тренера."""
    req = get_coach_request(rid)
    if not req or req['trainer_id'] != trainer['user_id'] or req['status'] != 'pending':
        return 'Заявка уже обработана или отменена.'
    client = get_user(req['client_id'])
    if accept:
        if client.get('trainer_id'):
            set_request_status(rid, 'cancelled')
            return 'Этот пользователь уже занимается с другим тренером.'
        if not trainer_has_room(trainer['user_id']):
            return 'Свободных мест нет — увеличь лимит в профиле или освободи место.'
        set_request_status(rid, 'accepted')
        start_coaching(client['user_id'], trainer['user_id'])
        if bot:
            await notify(bot, client['user_id'],
                         f'🎉 Тренер <b>{html.escape(display_name(trainer, ""))}</b> принял твою заявку! '
                         'Он сможет назначать тренировки и писать тебе. Раздел — «🎓 Мой тренер».',
                         menu_for(get_user(client['user_id'])))
        return f'✅ {display_name(client)} теперь твой подопечный.'
    set_request_status(rid, 'rejected')
    if bot:
        await notify(bot, client['user_id'], f'Тренер {html.escape(display_name(trainer, ""))} сейчас не может взять '
                                             'тебя. Выбери другого тренера в каталоге.')
    return f'Заявка {display_name(client)} отклонена.'


def save_message(from_id, to_id, text):
    with connect() as c:
        mid = c.execute('INSERT INTO messages(from_id, to_id, text, created_at) VALUES(?,?,?,?)',
                        (from_id, to_id, text, now().isoformat(timespec='seconds'))).lastrowid
    mark_read(from_id, to_id)  # ответил — значит, прочитал входящие
    return mid


def chat_messages(a, b, after_id=0, limit=300):
    with connect() as c:
        rows = c.execute('''SELECT * FROM (SELECT * FROM messages WHERE ((from_id=? AND to_id=?) OR (from_id=? AND to_id=?))
                            AND id>? ORDER BY id DESC LIMIT ?) ORDER BY id''', (a, b, b, a, after_id, limit)).fetchall()
    return [dict(r) for r in rows]


def mark_read(reader, other):
    with connect() as c:
        c.execute('UPDATE messages SET read_at=? WHERE to_id=? AND from_id=? AND read_at IS NULL',
                  (now().isoformat(timespec='seconds'), reader, other))


def unread_count(reader, other=None):
    q, args = 'SELECT COUNT(*) FROM messages WHERE to_id=? AND read_at IS NULL', [reader]
    if other is not None:
        q += ' AND from_id=?'
        args.append(other)
    with connect() as c:
        return c.execute(q, args).fetchone()[0]


def recent_messages(a, b, limit=3):
    with connect() as c:
        rows = c.execute('''SELECT * FROM messages WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)
                            ORDER BY id DESC LIMIT ?''', (a, b, b, a, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def item_rest(ex, hi):
    if ex.unit == 'sec':
        return 60
    return 180 if hi <= 6 else (120 if hi <= 10 else 75)


def day_from_items(items, title, note=''):
    """WorkoutDay из упражнений, назначенных тренером."""
    planned = []
    for it in items:
        ex = EXERCISES.get(it['ex'])
        if not ex:
            continue
        presc = Prescription(int(it['sets']), int(it['lo']), int(it['hi']), item_rest(ex, int(it['hi'])), ex.unit)
        planned.append(PlannedExercise(ex, 'main' if ex.compound else 'acc', presc))
    return WorkoutDay(title, tuple(planned), note or 'Тренировка от тренера')


def items_from_day(day):
    return [{'ex': p.exercise.id, 'sets': p.presc.sets, 'lo': p.presc.lo, 'hi': p.presc.hi, 'w': None}
            for p in day.exercises]


def item_line(i, it):
    ex = EXERCISES.get(it['ex'])
    name = ex.name if ex else it['ex']
    unit = ' сек' if ex and ex.unit == 'sec' else ''
    reps = f'{it["lo"]}' if it['lo'] == it['hi'] else f'{it["lo"]}–{it["hi"]}'
    weight = f', {fmt_w(it["w"])} кг' if it.get('w') else ''
    return f'{i}. {name} — {it["sets"]}×{reps}{unit}{weight}'


def wk_day(user, wk):
    """План текущей тренировки: назначенная тренером или день программы."""
    if wk.get('items') is not None:
        return day_from_items(wk['items'], wk.get('atitle') or 'Тренировка от тренера', wk.get('anote') or '')
    return plan_day(user, wk['day'], wk.get('mods'), wk.get('place'), wk.get('swaps'))


def date_label(date_iso):
    d = date.fromisoformat(date_iso)
    names = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
    if d == now().date():
        return f'сегодня, {d:%d.%m}'
    if d == now().date() + timedelta(days=1):
        return f'завтра, {d:%d.%m}'
    return f'{names[d.weekday()]}, {d:%d.%m}'


async def notify(bot, uid, text, markup=None):
    """Сообщение другому пользователю; False — если не доставлено (например, бот заблокирован)."""
    try:
        await bot.send_message(uid, text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return True
    except Exception as exc:
        log.warning('Не удалось отправить сообщение %s: %s', uid, exc)
        return False


# ---------- Оплаты, начисления тренерам и выплаты ----------
# Правила:
# • тариф с тренером (COACH) — тренеру, который ведёт подопечного, доля COACH_SHARE % от оплаты;
# • тариф без тренера — пригласившему тренеру реферальные 20–40 % по его уровню на дату оплаты, пока человек платит;
# • начисление 14 дней «ожидает» (возвраты), потом «доступно»; выплата раз в месяц по реестру, от MIN_PAYOUT ₽;
# • выплаты только самозанятым и ИП с заполненными реквизитами;
# • возврат отменяет начисление, а если оно уже выплачено — создаёт удержание из следующей выплаты.

def _env_float(name, default):
    try:
        return float((os.environ.get(name) or str(default)).replace(',', '.'))
    except ValueError:
        return float(default)


def coach_share():
    return _env_float('COACH_SHARE', 60)


def hold_days():
    return int(_env_float('COMMISSION_HOLD_DAYS', 14))


def min_payout():
    return _env_float('MIN_PAYOUT', 1000)


LEGAL_STATUSES = {'npd': 'Самозанятый (НПД)', 'ip': 'ИП'}
PAYOUT_METHODS = {'card': 'Карта', 'sbp': 'СБП (по номеру телефона)', 'account': 'Расчётный счёт'}
COMMISSION_STATUSES = {'pending': 'ожидает', 'available': 'доступно', 'paid': 'выплачено', 'cancelled': 'отменено'}


def money(x):
    x = round(float(x or 0), 2)
    whole = f'{int(abs(x)):,}'.replace(',', ' ')
    frac = f'{abs(x) - int(abs(x)):.2f}'[1:].replace('.', ',')
    return ('−' if x < 0 else '') + whole + ('' if frac == ',00' else frac) + ' ₽'


def record_payment(uid, amount, kind='self', days=None, source='manual', note=''):
    """Оплата подписки: сохраняет её и начисляет тренерам. kind: 'self' — без тренера, 'coach' — с тренером."""
    user = get_user(uid)
    stamp = now()
    with connect() as c:
        pid = c.execute('INSERT INTO payments(user_id, amount, kind, days, paid_at, source, note) VALUES(?,?,?,?,?,?,?)',
                        (uid, amount, kind, days, stamp.isoformat(timespec='seconds'), source, note)).lastrowid
    available_at = (stamp + timedelta(days=hold_days())).isoformat(timespec='seconds')
    rows = []
    if kind == 'coach' and user and user.get('trainer_id'):
        pct = coach_share()
        rows.append((user['trainer_id'], 'coaching', pct))
    elif kind == 'self' and user and user.get('referred_by'):
        pct = trainer_level(referral_stats(user['referred_by'])[1])[1][2]
        rows.append((user['referred_by'], 'referral', pct))
    with connect() as c:
        for tid, ctype, pct in rows:
            c.execute('''INSERT INTO commissions(payment_id, trainer_id, client_id, type, base_amount, percent, amount,
                         status, created_at, available_at) VALUES(?,?,?,?,?,?,?, 'pending', ?, ?)''',
                      (pid, tid, uid, ctype, amount, pct, round(amount * pct / 100, 2),
                       stamp.isoformat(timespec='seconds'), available_at))
    friend_reward_on_payment(uid, pid)
    return pid


def refund_payment(pid):
    """Возврат: отменяет начисления; уже выплаченные — удерживаются из следующей выплаты."""
    stamp = now().isoformat(timespec='seconds')
    with connect() as c:
        pay = c.execute('SELECT * FROM payments WHERE id=?', (pid,)).fetchone()
        if not pay or pay['refunded_at']:
            return False
        c.execute('UPDATE payments SET refunded_at=? WHERE id=?', (stamp, pid))
        c.execute("UPDATE friend_rewards SET status='cancelled' WHERE payment_id=? AND status='pending'", (pid,))
        for com in c.execute('SELECT * FROM commissions WHERE payment_id=? AND amount>0', (pid,)).fetchall():
            if com['status'] in ('pending', 'available'):
                c.execute("UPDATE commissions SET status='cancelled' WHERE id=?", (com['id'],))
            elif com['status'] == 'paid':
                c.execute('''INSERT INTO commissions(payment_id, trainer_id, client_id, type, base_amount, percent, amount,
                             status, created_at, available_at) VALUES(?,?,?, 'refund', ?, ?, ?, 'available', ?, ?)''',
                          (pid, com['trainer_id'], com['client_id'], -com['base_amount'], com['percent'],
                           -com['amount'], stamp, stamp))
    return True


def refresh_commissions():
    """Ожидающие начисления, у которых прошёл срок удержания, становятся доступными."""
    with connect() as c:
        c.execute("UPDATE commissions SET status='available' WHERE status='pending' AND available_at<=?",
                  (now().isoformat(timespec='seconds'),))


def trainer_balance(tid):
    refresh_commissions()
    with connect() as c:
        rows = c.execute('SELECT status, SUM(amount) FROM commissions WHERE trainer_id=? GROUP BY status', (tid,)).fetchall()
    sums = {r[0]: round(r[1] or 0, 2) for r in rows}
    return {k: sums.get(k, 0.0) for k in ('pending', 'available', 'paid')}


def trainer_commissions(tid, limit=30):
    sql = ('SELECT c.*, u.name AS client_name FROM commissions c LEFT JOIN users u ON u.user_id=c.client_id '
           'WHERE c.trainer_id=? ORDER BY c.id DESC LIMIT ?')
    with connect() as c:
        return [dict(r) for r in c.execute(sql, (tid, limit))]


def get_requisites(tid):
    with connect() as c:
        row = c.execute('SELECT * FROM trainer_requisites WHERE user_id=?', (tid,)).fetchone()
    return dict(row) if row else None


def valid_inn(inn, status):
    """ИНН физлица/ИП — 12 цифр с контрольными числами."""
    if not re.fullmatch(r'\d{12}', inn or ''):
        return False
    d = [int(x) for x in inn]
    c1 = sum(w * x for w, x in zip([7, 2, 4, 10, 3, 5, 9, 4, 6, 8], d)) % 11 % 10
    c2 = sum(w * x for w, x in zip([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8], d)) % 11 % 10
    return d[10] == c1 and d[11] == c2


def save_requisites(tid, legal_status, full_name, inn, method, details):
    with connect() as c:
        c.execute('''INSERT OR REPLACE INTO trainer_requisites(user_id, legal_status, full_name, inn, method, details, updated_at)
                     VALUES(?,?,?,?,?,?,?)''', (tid, legal_status, full_name, inn, method, details, now().isoformat(timespec='seconds')))


def requisites_ok(req):
    return bool(req and req.get('legal_status') in LEGAL_STATUSES and req.get('full_name') and
                valid_inn(req.get('inn'), req.get('legal_status')) and req.get('method') in PAYOUT_METHODS and req.get('details'))


def mask(text, keep=4):
    """Скрывает реквизиты: «•••• 9012»."""
    text = str(text or '')
    digits = re.sub(r'\D', '', text)
    if len(digits) >= 8:
        return '•••• ' + digits[-keep:]
    return ('••••' + text[-keep:]) if len(text) > keep else text


def create_payout_registry():
    """Создаёт выплаты всем тренерам с доступной суммой от MIN_PAYOUT ₽ и реквизитами.
    Возвращает (созданные выплаты, тренеры без реквизитов с их суммами)."""
    refresh_commissions()
    created, missing = [], []
    with connect() as c:
        totals = c.execute('''SELECT trainer_id, SUM(amount) AS total FROM commissions
                              WHERE status='available' AND payout_id IS NULL GROUP BY trainer_id HAVING total>0''').fetchall()
    for row in totals:
        tid, total = row['trainer_id'], round(row['total'], 2)
        req = get_requisites(tid)
        if total < min_payout():
            continue
        if not requisites_ok(req):
            missing.append((tid, total))
            continue
        stamp = now().isoformat(timespec='seconds')
        with connect() as c:
            pid = c.execute('''INSERT INTO payouts(trainer_id, amount, status, created_at, legal_status, full_name, inn,
                               method, details) VALUES(?,?, 'created', ?,?,?,?,?,?)''',
                            (tid, total, stamp, req['legal_status'], req['full_name'], req['inn'], req['method'],
                             req['details'])).lastrowid
            c.execute("UPDATE commissions SET payout_id=? WHERE trainer_id=? AND status='available' AND payout_id IS NULL",
                      (pid, tid))
        created.append(pid)
    return created, missing


def open_payouts():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM payouts WHERE status='created' ORDER BY id")]


def trainer_payouts(tid, limit=12):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM payouts WHERE trainer_id=? ORDER BY id DESC LIMIT ?', (tid, limit))]


def mark_payout_paid(pid):
    stamp = now().isoformat(timespec='seconds')
    with connect() as c:
        p = c.execute("SELECT * FROM payouts WHERE id=? AND status='created'", (pid,)).fetchone()
        if not p:
            return None
        c.execute("UPDATE payouts SET status='paid', paid_at=? WHERE id=?", (stamp, pid))
        c.execute("UPDATE commissions SET status='paid' WHERE payout_id=?", (pid,))
    return dict(p)


def registry_csv(payout_ids):
    """Реестр выплат для бухгалтерии/банка: CSV с BOM, открывается в Excel."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(['№ выплаты', 'ID тренера', 'ФИО', 'Статус', 'ИНН', 'Способ', 'Реквизиты', 'Сумма, ₽', 'Начислений'])
    with connect() as c:
        for pid in payout_ids:
            p = c.execute('SELECT * FROM payouts WHERE id=?', (pid,)).fetchone()
            n = c.execute('SELECT COUNT(*) FROM commissions WHERE payout_id=?', (pid,)).fetchone()[0]
            w.writerow([p['id'], p['trainer_id'], p['full_name'], LEGAL_STATUSES.get(p['legal_status'], ''), p['inn'],
                        PAYOUT_METHODS.get(p['method'], ''), p['details'], f'{p["amount"]:.2f}'.replace('.', ','), n])
    return ('﻿' + buf.getvalue()).encode('utf-8')


def commissions_text(trainer):
    tid = trainer['user_id']
    b = trainer_balance(tid)
    req = get_requisites(tid)
    lines = ['<b>💰 Начисления</b>', '',
             f'⏳ Ожидает (удержание {hold_days()} дн.): <b>{money(b["pending"])}</b>',
             f'✅ Доступно к выплате: <b>{money(b["available"])}</b>',
             f'💸 Выплачено всего: <b>{money(b["paid"])}</b>', '',
             f'Выплаты — раз в месяц, от {money(min_payout())}. За ведение подопечных (тариф с тренером) — '
             f'{fmt_w(coach_share())}% оплаты, за приглашённых на тарифы без тренера — процент твоего уровня.', '']
    if requisites_ok(req):
        lines.append(f'Реквизиты: {LEGAL_STATUSES[req["legal_status"]]}, ИНН {mask(req["inn"])}, '
                     f'{PAYOUT_METHODS[req["method"]]} {mask(req["details"])}')
    else:
        lines.append('⚠️ Укажи реквизиты — без них выплата невозможна (начисления сохранятся). '
                     'Выплаты получают только самозанятые и ИП.')
    recent = trainer_commissions(tid, 8)
    if recent:
        lines += ['', '<b>Последние начисления</b>']
        kinds = {'coaching': 'ведение', 'referral': 'реферал', 'refund': 'возврат'}
        for r in recent:
            lines.append(f'• {r["created_at"][:10]} · {html.escape(r["client_name"] or "")} · {kinds.get(r["type"], r["type"])} '
                         f'{fmt_w(r["percent"])}% · <b>{money(r["amount"])}</b> · {COMMISSION_STATUSES.get(r["status"], r["status"])}')
    return '\n'.join(lines)


# ---------- Друзья: приглашения, «Тренируйся с другом», карточка результата ----------
# • У каждого пользователя личная ссылка t.me/<бот>?start=u_<код>.
# • Новичок по ссылке друга сразу получает FRIEND_BONUS_DAYS дней подписки.
# • Пригласивший получает INVITER_BONUS_DAYS дней после первой оплаты друга и удержания (как у тренеров),
#   не больше INVITER_BONUS_CAP_DAYS бонусных дней за 365 дней.
# • Засчитывается первая ссылка: пришёл по ссылке тренера — ссылка друга уже не действует, и наоборот.
# • Пара «Тренируйся с другом»: общая цель тренировок на неделю, прогресс друг друга и серия закрытых недель.

PAIR_GOALS = (2, 3, 4, 5)


def friend_bonus_days():
    return int(_env_float('FRIEND_BONUS_DAYS', 7))


def inviter_bonus_days():
    return int(_env_float('INVITER_BONUS_DAYS', 14))


def inviter_bonus_cap():
    return int(_env_float('INVITER_BONUS_CAP_DAYS', 365))


def user_invite_code(uid):
    user = get_user(uid)
    if user and user.get('invite_code'):
        return user['invite_code']
    alphabet = 'abcdefghijkmnpqrstuvwxyz23456789'
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(7))
        with connect() as c:
            if not c.execute('SELECT 1 FROM users WHERE invite_code=?', (code,)).fetchone():
                c.execute('UPDATE users SET invite_code=? WHERE user_id=?', (code, uid))
                return code


def user_by_invite_code(code):
    if not code or not re.fullmatch(r'[a-z0-9]{4,16}', code):
        return None
    with connect() as c:
        row = c.execute('SELECT * FROM users WHERE invite_code=?', (code,)).fetchone()
    return dict(row) if row else None


def invite_url(bot_username, code, kind='u'):
    return f'https://t.me/{bot_username}?start={kind}_{code}'


def is_new_user(user):
    """Новичок: только что пришёл, не тренировался и ни по чьей ссылке ещё не приходил."""
    if not user or user.get('referred_by') or user.get('invited_by') or user.get('is_trainer'):
        return False
    if finished_workouts(user['user_id'], limit=1):
        return False
    try:
        created = datetime.fromisoformat(user.get('created_at') or '')
    except ValueError:
        return False
    return now() - created <= timedelta(days=2)


def apply_friend_invite(uid, inviter_id):
    """Привязывает новичка к пригласившему другу и дарит дни. Возвращает 'ok', 'self' или 'not_new'."""
    if uid == inviter_id:
        return 'self'
    if not is_new_user(get_user(uid)):
        return 'not_new'
    with connect() as c:
        c.execute('UPDATE users SET invited_by=? WHERE user_id=?', (inviter_id, uid))
    add_subscription(uid, friend_bonus_days())
    return 'ok'


def friend_reward_on_payment(uid, payment_id):
    """Первая оплата приглашённого: награда другу встаёт в очередь (удержание как у начислений тренерам)."""
    user = get_user(uid)
    if not user or not user.get('invited_by'):
        return
    stamp = now()
    with connect() as c:
        c.execute('''INSERT OR IGNORE INTO friend_rewards(inviter_id, friend_id, payment_id, days, status, created_at, available_at)
                     VALUES(?,?,?,?, 'pending', ?, ?)''',
                  (user['invited_by'], uid, payment_id, inviter_bonus_days(), stamp.isoformat(timespec='seconds'),
                   (stamp + timedelta(days=hold_days())).isoformat(timespec='seconds')))


def cancel_friend_reward(payment_id):
    with connect() as c:
        c.execute("UPDATE friend_rewards SET status='cancelled' WHERE payment_id=? AND status='pending'", (payment_id,))


def friend_days_granted(inviter_id, since):
    with connect() as c:
        return c.execute("SELECT COALESCE(SUM(days),0) FROM friend_rewards WHERE inviter_id=? AND status='granted' "
                         'AND granted_at>=?', (inviter_id, since.isoformat(timespec='seconds'))).fetchone()[0]


def process_friend_rewards():
    """Начисляет созревшие награды. Возвращает [(пригласивший, друг, дней)] для уведомлений."""
    stamp = now()
    with connect() as c:
        due = [dict(r) for r in c.execute("SELECT * FROM friend_rewards WHERE status='pending' AND available_at<=? "
                                          'ORDER BY id', (stamp.isoformat(timespec='seconds'),))]
    done = []
    for r in due:
        left = inviter_bonus_cap() - friend_days_granted(r['inviter_id'], stamp - timedelta(days=365))
        days = max(0, min(r['days'], left))
        with connect() as c:
            c.execute('UPDATE friend_rewards SET status=?, days=?, granted_at=? WHERE id=?',
                      ('granted' if days else 'capped', days, stamp.isoformat(timespec='seconds'), r['id']))
        if days:
            add_subscription(r['inviter_id'], days)
            done.append((r['inviter_id'], r['friend_id'], days))
    return done


async def deliver_friend_rewards(bot):
    for inviter, friend, days in process_friend_rewards():
        await notify(bot, inviter, f'🎁 Твой друг <b>{html.escape(display_name(get_user(friend)))}</b> оформил подписку — '
                                   f'тебе <b>+{days} дней</b>! Подписка активна до '
                                   f'{date.fromisoformat(get_user(inviter)["sub_until"]):%d.%m.%Y}.')


def friend_stats(uid):
    with connect() as c:
        invited = c.execute('SELECT COUNT(*) FROM users WHERE invited_by=?', (uid,)).fetchone()[0]
        rows = [dict(r) for r in c.execute(
            '''SELECT f.*, u.name AS friend_name FROM friend_rewards f LEFT JOIN users u ON u.user_id=f.friend_id
               WHERE f.inviter_id=? ORDER BY f.id DESC''', (uid,))]
        friends = [dict(r) for r in c.execute('SELECT user_id, name, created_at FROM users WHERE invited_by=? '
                                              'ORDER BY created_at DESC LIMIT 50', (uid,))]
    return {'invited': invited, 'paid': sum(1 for r in rows if r['status'] in ('pending', 'granted', 'capped')),
            'days': sum(r['days'] for r in rows if r['status'] == 'granted'), 'rewards': rows, 'friends': friends}


# --- Пара «Тренируйся с другом» ---

def active_pair(uid):
    with connect() as c:
        row = c.execute('SELECT * FROM pairs WHERE ended_at IS NULL AND (a_id=? OR b_id=?) ORDER BY id DESC LIMIT 1',
                        (uid, uid)).fetchone()
    return dict(row) if row else None


def create_pair(a, b, goal=3):
    """Возвращает (pair или None, причина)."""
    if a == b:
        return None, 'self'
    if active_pair(a):
        return None, 'inviter_busy'
    if active_pair(b):
        return None, 'busy'
    with connect() as c:
        pid = c.execute('INSERT INTO pairs(a_id, b_id, goal, created_at) VALUES(?,?,?,?)',
                        (a, b, goal, now().isoformat(timespec='seconds'))).lastrowid
    return active_pair(a), 'ok'


def end_pair(uid):
    pair = active_pair(uid)
    if pair:
        with connect() as c:
            c.execute('UPDATE pairs SET ended_at=? WHERE id=?', (now().isoformat(timespec='seconds'), pair['id']))
    return pair


def set_pair_goal(uid, goal):
    pair = active_pair(uid)
    if pair and goal in PAIR_GOALS:
        with connect() as c:
            c.execute('UPDATE pairs SET goal=? WHERE id=?', (goal, pair['id']))
    return active_pair(uid)


def week_monday(d=None):
    d = d or now().date()
    return d - timedelta(days=d.weekday())


def workouts_in_week(uid, monday):
    start = datetime.combine(monday, datetime.min.time())
    with connect() as c:
        return c.execute('SELECT COUNT(*) FROM workouts WHERE user_id=? AND finished_at IS NOT NULL '
                         'AND finished_at>=? AND finished_at<?',
                         (uid, start.isoformat(timespec='seconds'),
                          (start + timedelta(days=7)).isoformat(timespec='seconds'))).fetchone()[0]


def pair_status(pair, uid):
    partner_id = pair['b_id'] if pair['a_id'] == uid else pair['a_id']
    goal = pair['goal']
    monday = week_monday()
    me, partner = workouts_in_week(uid, monday), workouts_in_week(partner_id, monday)
    started = week_monday(datetime.fromisoformat(pair['created_at']).date())
    streak = 1 if me >= goal and partner >= goal else 0
    week = monday - timedelta(days=7)
    while week >= started and workouts_in_week(uid, week) >= goal and workouts_in_week(partner_id, week) >= goal:
        streak += 1
        week -= timedelta(days=7)
    return {'partner_id': partner_id, 'partner': display_name(get_user(partner_id), 'Друг'), 'goal': goal,
            'me': me, 'partner_done': partner, 'streak': streak, 'closed': me >= goal and partner >= goal}


def pair_text(uid):
    pair = active_pair(uid)
    if not pair:
        return ''
    s = pair_status(pair, uid)
    return (f'🤝 <b>Тренируйся с другом:</b> {html.escape(s["partner"])}\n'
            f'Цель недели: {trainings(s["goal"])} каждому\n'
            f'Ты: {s["me"]}/{s["goal"]} {progress_bar(min(1, s["me"] / s["goal"]))}\n'
            f'{html.escape(s["partner"])}: {s["partner_done"]}/{s["goal"]} {progress_bar(min(1, s["partner_done"] / s["goal"]))}\n'
            + (f'🔥 Серия: {s["streak"]} {plural_weeks(s["streak"])} подряд вместе' if s['streak'] else
               'Закройте неделю вместе — начнётся серия 🔥'))


def trainings(n):
    return f'{n} ' + ('тренировки' if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else
                      'тренировка' if n % 10 == 1 and n % 100 != 11 else 'тренировок')


def plural_weeks(n):
    n = abs(n) % 100
    if 11 <= n <= 14:
        return 'недель'
    return {1: 'неделя', 2: 'недели', 3: 'недели', 4: 'недели'}.get(n % 10, 'недель')


async def social_after_workout(bot, uid):
    """После тренировки: сообщить напарнику прогресс; если оба закрыли неделю — поздравить обоих."""
    pair = active_pair(uid)
    if not pair or not bot:
        return
    s = pair_status(pair, uid)
    name = html.escape(display_name(get_user(uid), 'Друг'))
    if s['me'] == s['goal'] and s['partner_done'] >= s['goal']:
        text = (f'🔥 Неделя закрыта вместе! Серия: <b>{s["streak"]} {plural_weeks(s["streak"])}</b>. '
                'Так держать 💪')
        await notify(bot, uid, text)
        await notify(bot, s['partner_id'], text)
        return
    if s['me'] > s['goal']:
        return
    left = s['goal'] - s['partner_done']
    await notify(bot, s['partner_id'],
                 f'🤝 <b>{name}</b> потренировался(лась): {s["me"]}/{s["goal"]} на этой неделе. '
                 + (f'Тебе осталось {left} — не отставай 😉' if left > 0 else 'Ты свою цель уже выполнил(а) 💪'))


# --- Карточка результата ---

FONTS_DIR = Path(__file__).resolve().parent / 'assets' / 'fonts'


def card_data(uid, wid=None):
    """Данные карточки: последняя (или указанная) завершённая тренировка и итоги месяца."""
    user = get_user(uid)
    with connect() as c:
        if wid:
            w = c.execute('SELECT * FROM workouts WHERE id=? AND user_id=? AND finished_at IS NOT NULL', (wid, uid)).fetchone()
        else:
            w = c.execute('SELECT * FROM workouts WHERE user_id=? AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1',
                          (uid,)).fetchone()
    data = {'name': display_name(user, 'Атлет'), 'month': len(finished_workouts(uid, since=now() - timedelta(days=30))),
            'week': workouts_in_week(uid, week_monday()), 'plan': (user or {}).get('days') or 3, 'workout': None}
    pair = active_pair(uid)
    data['streak'] = pair_status(pair, uid)['streak'] if pair else 0
    if not w:
        return data
    w = dict(w)
    sets = workout_sets(w['id'])
    records = []
    for ex_id in dict.fromkeys(s['exercise_id'] for s in sets):
        before = best_e1rm(uid, ex_id, w['id'])
        best = max(e1rm(s['weight'], s['reps']) for s in sets if s['exercise_id'] == ex_id)
        if before and best > before:
            records.append(EXERCISES[ex_id].name if ex_id in EXERCISES else ex_id)
    tonnage = sum(s['weight'] * s['reps'] for s in sets
                  if s['exercise_id'] in EXERCISES and EXERCISES[s['exercise_id']].unit == 'reps')
    minutes = max(1, int((datetime.fromisoformat(w['finished_at']) - datetime.fromisoformat(w['started_at'])).total_seconds() // 60))
    if w.get('kind') == 'group':
        minutes = w.get('group_minutes') or minutes
    data['workout'] = {'id': w['id'], 'title': w.get('title') or 'Тренировка', 'date': w['finished_at'][:10],
                       'minutes': minutes, 'sets': len(sets), 'exercises': len({s['exercise_id'] for s in sets}),
                       'tonnage': round(tonnage), 'records': records[:3], 'group': w.get('kind') == 'group'}
    return data


def render_card(data, url, gift=True):
    """PNG 1080×1350 (формат поста/сторис) в стиле приложения. Ссылка — текстом и QR-кодом."""
    import io
    import qrcode
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1080, 1350
    bg, surface, accent, text, soft, on_accent = '#0E0F0F', '#1A1C1B', '#C8F04A', '#F2F4F1', '#9AA19C', '#0E0F0F'
    img = Image.new('RGB', (W, H), bg)
    d = ImageDraw.Draw(img)

    def font(weight, size):
        return ImageFont.truetype(str(FONTS_DIR / f'Manrope_{weight}.ttf'), size)

    def fit(s, weight, size, width):
        while size > 20 and d.textlength(s, font=font(weight, size)) > width:
            size -= 2
        return font(weight, size)

    pad = 72
    d.ellipse((W - 420, -260, W + 200, 360), fill='#1F2A10')
    d.text((pad, 70), 'FitHelper', font=font('800ExtraBold', 44), fill=accent)
    w = data.get('workout')
    when = f'{date.fromisoformat(w["date"]):%d.%m.%Y}' if w else f'{now():%d.%m.%Y}'
    d.text((W - pad, 82), when, font=font('600SemiBold', 30), fill=soft, anchor='ra')

    y = 190
    d.text((pad, y), data['name'], font=fit(data['name'], '700Bold', 44, W - 2 * pad), fill=soft)
    y += 70
    title = (w['title'] if w else 'Тренируюсь с FitHelper')
    headline = 'Тренировка завершена' if w else 'Мой прогресс'
    d.text((pad, y), headline, font=font('800ExtraBold', 76), fill=text)
    y += 100
    d.text((pad, y), title, font=fit(title, '600SemiBold', 38, W - 2 * pad), fill=soft)
    y += 90

    tiles = []
    if w:
        if w['tonnage']:
            tiles.append((f'{w["tonnage"]:,}'.replace(',', ' '), 'кг тоннаж'))
        tiles.append((str(w['minutes']), 'минут'))
        if w['sets']:
            tiles.append((str(w['sets']), 'подходов'))
    tiles.append((str(data['month']), 'тренировок за 30 дней'))
    tiles = tiles[:4]
    cols = 2
    tw, th, gap = (W - 2 * pad - 24) // cols, 190, 24
    for i, (value, label) in enumerate(tiles):
        x0 = pad + (i % cols) * (tw + gap)
        y0 = y + (i // cols) * (th + gap)
        hero = i == 0
        d.rounded_rectangle((x0, y0, x0 + tw, y0 + th), radius=36, fill=accent if hero else surface)
        d.text((x0 + 32, y0 + 26), value, font=fit(value, '800ExtraBold', 72, tw - 64), fill=on_accent if hero else text)
        d.text((x0 + 32, y0 + 128), label, font=font('700Bold', 28), fill=on_accent if hero else soft)
    y += ((len(tiles) + 1) // cols) * (th + gap) + 10

    extra = []
    if w and w['records']:
        extra.append('Рекорд: ' + ', '.join(w['records']))
    extra.append(f'Неделя: {data["week"]} из {data["plan"]} тренировок')
    if data.get('streak'):
        extra.append(f'Серия с другом: {data["streak"]} {plural_weeks(data["streak"])} подряд')
    for line in extra[:3]:
        d.text((pad, y), line, font=fit(line, '700Bold', 34, W - 2 * pad), fill=text)
        y += 54

    # Низ: приглашение и QR.
    box = (pad, H - 300, W - pad, H - 70)
    d.rounded_rectangle(box, radius=40, fill=surface)
    qr = qrcode.QRCode(border=1, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    q = qr.make_image(fill_color=bg, back_color=accent).convert('RGB').resize((190, 190), Image.NEAREST)
    img.paste(q, (box[2] - 190 - 20, box[1] + 20))
    tx = box[0] + 36
    d.text((tx, box[1] + 34), 'Тренируйся со мной', font=font('800ExtraBold', 44), fill=text)
    sub = 'Наведи камеру на QR-код' if not gift else f'+{friend_bonus_days()} дней подписки в подарок'
    d.text((tx, box[1] + 100), sub, font=font('700Bold', 30), fill=accent)
    short = url.replace('https://', '')
    d.text((tx, box[1] + 150), short, font=fit(short, '600SemiBold', 26, box[2] - 230 - tx), fill=soft)
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def friends_text(uid, bot_username):
    code = user_invite_code(uid)
    st = friend_stats(uid)
    lines = ['<b>🤝 Друзья</b>', '',
             f'Пригласи друга — он сразу получит <b>+{friend_bonus_days()} дней</b> подписки, а ты — '
             f'<b>+{inviter_bonus_days()} дней</b>, когда он оформит подписку.', '',
             f'Твоя ссылка:\n<code>{invite_url(bot_username, code)}</code>', '',
             f'👥 Пришло по ссылке: <b>{st["invited"]}</b> · оформили подписку: <b>{st["paid"]}</b> · '
             f'получено дней: <b>{st["days"]}</b>']
    pt = pair_text(uid)
    lines += ['', pt if pt else '🤝 <b>Тренируйся с другом</b> — общая цель на неделю, видно прогресс друг друга, '
                                'а закрытые вместе недели складываются в серию 🔥']
    return '\n'.join(lines)


def friends_kb(uid):
    rows = [[('📸 Карточка результата', 'fr:card')]]
    if active_pair(uid):
        rows.append([(f'🎯 {g}', f'fr:g:{g}') for g in PAIR_GOALS])
        rows.append([('🚪 Выйти из пары', 'fr:leave')])
    else:
        rows.append([('🤝 Тренироваться с другом', 'fr:pair')])
    return kb(rows)


async def handle_friend_start(update, context, code, pair=False):
    """Пришёл по ссылке друга (u_) или по приглашению в пару (pair_)."""
    uid = update.effective_user.id
    message = update.effective_message
    inviter = user_by_invite_code(code)
    if not inviter:
        return
    ensure_user_row(uid, update.effective_user.first_name or '')
    if inviter['user_id'] == uid:
        await message.reply_text('Это твоя ссылка 🙂 Отправь её другу.')
        return
    name = html.escape(display_name(inviter, 'Друг'))
    if apply_friend_invite(uid, inviter['user_id']) == 'ok':
        await message.reply_text(f'🎁 Тебя пригласил(а) <b>{name}</b> — дарим <b>+{friend_bonus_days()} дней</b> подписки!',
                                 parse_mode=ParseMode.HTML)
        await notify(context.bot, inviter['user_id'],
                     f'🎉 По твоей ссылке пришёл(ла) <b>{html.escape(display_name(get_user(uid)))}</b>. '
                     f'Когда друг оформит подписку, ты получишь +{inviter_bonus_days()} дней.')
    if pair:
        pr, why = create_pair(inviter['user_id'], uid)
        if pr:
            await message.reply_text(f'🤝 Теперь вы с <b>{name}</b> тренируетесь вместе: цель — {trainings(pr["goal"])} '
                                     'в неделю каждому. Я буду сообщать о прогрессе друг друга. '
                                     'Настроить — «🤝 Друзья».', parse_mode=ParseMode.HTML)
            await notify(context.bot, inviter['user_id'],
                         f'🤝 <b>{html.escape(display_name(get_user(uid)))}</b> принял(а) приглашение — '
                         'теперь вы тренируетесь вместе! Цель недели можно поменять в «🤝 Друзья».')
        elif why == 'busy':
            await message.reply_text('У тебя уже есть напарник. Чтобы сменить, выйди из пары в «🤝 Друзья».')
        elif why == 'inviter_busy':
            await message.reply_text(f'У {name} уже есть напарник по тренировкам.', parse_mode=ParseMode.HTML)


async def friends_callback(data, update, context):
    uid = update.effective_user.id
    message = update.callback_query.message
    parts = data.split(':')
    if data == 'fr:home':
        await message.reply_text(friends_text(uid, context.bot.username), parse_mode=ParseMode.HTML,
                                 reply_markup=friends_kb(uid), disable_web_page_preview=True)
    elif parts[1] == 'card':
        wid = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else None
        url = invite_url(context.bot.username, user_invite_code(uid))
        png = render_card(card_data(uid, wid), url)
        await message.reply_photo(png, caption=f'Перешли в сторис или другу 📲\nСсылка с подарком: {url}')
    elif data == 'fr:pair':
        url = invite_url(context.bot.username, user_invite_code(uid), 'pair')
        await message.reply_text('🤝 <b>Тренируйся с другом</b>\n\nОтправь другу эту ссылку. Когда он её откроет, '
                                 'вы станете напарниками: общая цель тренировок на неделю, я сообщаю о прогрессе '
                                 f'друг друга, а закрытые вместе недели складываются в серию 🔥\n\n<code>{url}</code>',
                                 parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    elif parts[1] == 'g' and len(parts) == 3 and parts[2].isdigit():
        pair = set_pair_goal(uid, int(parts[2]))
        if pair:
            s = pair_status(pair, uid)
            await notify(context.bot, s['partner_id'], f'🎯 {html.escape(display_name(get_user(uid)))} изменил(а) '
                                                       f'цель недели: {trainings(s["goal"])} каждому.')
            await message.reply_text(pair_text(uid), parse_mode=ParseMode.HTML, reply_markup=friends_kb(uid))
    elif data == 'fr:leave':
        pair = end_pair(uid)
        if pair:
            partner = pair['b_id'] if pair['a_id'] == uid else pair['a_id']
            await notify(context.bot, partner, f'👋 {html.escape(display_name(get_user(uid)))} вышел(ла) из пары.')
        await message.reply_text('Ты вышел(ла) из пары.', reply_markup=friends_kb(uid))


async def show_friends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user_row(uid, update.effective_user.first_name or '')
    await deliver_friend_rewards(context.bot)
    await update.effective_message.reply_text(friends_text(uid, context.bot.username), parse_mode=ParseMode.HTML,
                                              reply_markup=friends_kb(uid), disable_web_page_preview=True)


# ---------- Кабинет тренера ----------

def cabinet_text(trainer):
    tid = trainer['user_id']
    invited, subs = referral_stats(tid)
    idx, (name, _, percent, desc) = trainer_level(subs)
    clients = trainer_clients(tid)
    lines = ['<b>🎓 Кабинет тренера</b>', '',
             f'Уровень: <b>{name}</b> — <b>{percent}%</b> от подписки', f'<i>{desc}</i>', '',
             f'💳 Подписчиков (активная подписка): <b>{subs}</b>',
             f'🔗 Пришло по твоим ссылкам: <b>{invited}</b>',
             f'👥 Подопечных: <b>{len(clients)}</b>']
    if idx + 1 < len(TRAINER_LEVELS):
        nxt_name, nxt_from, nxt_percent, _ = TRAINER_LEVELS[idx + 1]
        cur_from = TRAINER_LEVELS[idx][1]
        frac = (subs - cur_from) / (nxt_from - cur_from)
        lines += ['', f'До {nxt_name} ({nxt_percent}%): ещё <b>{nxt_from - subs}</b> подписчиков',
                  progress_bar(frac)]
    else:
        lines += ['', '🏆 У тебя максимальный уровень!']
    bal = trainer_balance(tid)
    if any(bal.values()):
        lines += ['', f'💰 Доступно к выплате: <b>{money(bal["available"])}</b> · ожидает: {money(bal["pending"])}']
    pending = sum(len(client_assignments(c['user_id'])) for c in clients)
    if pending:
        lines.append(f'🎯 Назначено и ещё не выполнено: {pending}')
    return '\n'.join(lines)


def cabinet_kb():
    return kb([[('🎯 Назначить тренировку', 'tr:asc')],
               [('🔗 Мои ссылки', 'tr:links'), ('👥 Подопечные', 'tr:clients')],
               [('💰 Начисления и выплаты', 'tr:money')],
               [('🏆 Уровни программы', 'tr:levels')]])


def levels_text(subs):
    idx, _ = trainer_level(subs)
    lines = ['<b>🏆 Уровни партнёрской программы</b>', '',
             'Процент считается от подписок пользователей, которые пришли по твоим ссылкам.', '']
    for i, (name, start_from, percent, desc) in enumerate(TRAINER_LEVELS):
        end = TRAINER_LEVELS[i + 1][1] - 1 if i + 1 < len(TRAINER_LEVELS) else None
        rng = f'{max(start_from, 1)}–{end}' if end else f'{start_from}+'
        mark = '  ← ты здесь' if i == idx else ''
        lines += [f'<b>{name} — {percent}%</b>{mark}', f'{rng} подписчиков · {desc}', '']
    return '\n'.join(lines)


def links_text(trainer, bot_username):
    links = trainer_links(trainer['user_id'])
    lines = ['<b>🔗 Твои реферальные ссылки</b>', '',
             'Отправь ссылку клиентам или опубликуй её. Все, кто придёт по ней, закрепятся за тобой — '
             'с их подписок ты получаешь процент. Подопечными они станут после их согласия.', '']
    if not links:
        lines.append('Ссылок пока нет — создай первую.')
    for link in links:
        url = f'https://t.me/{bot_username}?start=ref_{link["code"]}'
        lines += [f'<b>{html.escape(link["label"] or "Без названия")}</b> — пришло {link["joined"]}, '
                  f'подписок {link["subs"]}', f'<code>{url}</code>', '']
    return '\n'.join(lines)


def client_card_text(client):
    cid = client['user_id']
    t = now()
    week = finished_workouts(cid, since=t - timedelta(days=7))
    month = finished_workouts(cid, since=t - timedelta(days=30))
    groups = sum(1 for w in month if w.get('kind') == 'group')
    sub = f'до {date.fromisoformat(client["sub_until"]):%d.%m.%Y}' if has_subscription(client) else 'нет'
    lines = [f'<b>👤 {html.escape(display_name(client))}</b>  (ID <code>{cid}</code>)', f'💳 Подписка: {sub}']
    if profile_complete(client):
        lines += [f'{GENDERS[client["gender"]]}, {AGES[client["age"]]} · {GOALS[client["goal"]]}',
                  f'{LEVELS[client["level"]]} · {client["days"]} трен./нед. · {PLACE_SHORT[client["place"]]}']
        lines += ['', f'📅 За 7 дней: <b>{len(week)}</b> из {client["days"]}  {progress_bar(len(week) / client["days"])}',
                  f'За 30 дней: <b>{len(month)}</b>' + (f' (групповых: {groups})' if groups else ''),
                  f'🏃 Кардио за 7 дней: {cardio_minutes_since(cid, t - timedelta(days=7))} мин']
    else:
        lines.append('Анкета ещё не заполнена.')
    if month:
        last = month[0]
        lines.append(f'🕐 Последняя: {last["finished_at"][:10]} — {html.escape(last["title"])}')
    prs = personal_records(cid)
    if prs:
        lines += ['', '<b>🏆 Рекорды</b>']
        ranked = sorted(prs.items(), key=lambda kv: -kv[1][0])
        for ex_id, (score, w, r, day) in ranked[:5]:
            ex = EXERCISES.get(ex_id)
            if ex:
                lines.append(f'• {ex.name}: {fmt_set(w, r, ex.unit)} — {day}')
    bw = body_weights(cid)
    if bw:
        diff = bw[-1]['weight'] - bw[0]['weight']
        sign = '+' if diff > 0 else ''
        lines.append(f'⚖️ Вес: {fmt_w(bw[-1]["weight"])} кг ({sign}{fmt_w(diff)} от старта)')
    pending = client_assignments(cid)
    if pending:
        lines += ['', '<b>🎯 Назначено</b>'] + [f'• {date_label(a["date"])} — {html.escape(a["title"])}' for a in pending]
    msgs = recent_messages(client['trainer_id'] or 0, cid)
    if msgs:
        lines += ['', '<b>💬 Переписка</b>']
        for m in msgs:
            who = 'Ты' if m['from_id'] != cid else display_name(client)
            lines.append(f'{html.escape(who)}: {html.escape(m["text"][:120])}')
    return '\n'.join(lines)


def client_card_kb(cid):
    return kb([[('🎯 Назначить тренировку', f'tr:as:{cid}'), ('💬 Написать', f'tr:msg:{cid}')],
               [('✏️ Изменить программу', f'tr:ed:{cid}'), ('📜 История', f'tr:h:{cid}')],
               [('📋 Назначенные', f'tr:al:{cid}'), ('⬅️ Подопечные', 'tr:clients')]])


def builder_text(build, client):
    lines = [f'<b>🛠 Тренировка для {html.escape(display_name(client))}</b>',
             f'Название: {html.escape(build["title"])}', '']
    if build['items']:
        lines += [item_line(i, it) for i, it in enumerate(build['items'], 1)]
    else:
        lines.append('Упражнений пока нет. Добавь их по одному или возьми день из программы подопечного.')
    if build.get('note'):
        lines += ['', f'📝 {html.escape(build["note"])}']
    return '\n'.join(lines)


def builder_kb(build):
    rows = [[('➕ Упражнение', 'tr:ba'), ('📅 День из его программы', 'tr:bp')]]
    if build['items']:
        rows.append([('🗑 Убрать последнее', 'tr:bx'), ('📝 Комментарий', 'tr:bn')])
        rows.append([('✅ Назначить', 'tr:bok')])
    rows.append([('✖️ Отмена', 'tr:bc')])
    return kb(rows)


async def show_builder(message, context):
    build = context.user_data['build']
    client = get_user(build['client'])
    await message.reply_text(builder_text(build, client), parse_mode=ParseMode.HTML, reply_markup=builder_kb(build))


async def trainer_cabinet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    message = update.effective_message
    if not is_trainer(user):
        await trainer_apply_prompt(message, user)
        return
    context.user_data.pop('await', None)
    await message.reply_text(cabinet_text(user), parse_mode=ParseMode.HTML, reply_markup=cabinet_kb())


async def trainer_apply_prompt(message, user):
    if user and user.get('trainer_status') == 'pending':
        await message.reply_text('⏳ Твоя заявка в партнёрскую программу на рассмотрении. Как только её одобрят — '
                                 'здесь появится кабинет тренера.')
        return
    await message.reply_text(
        '<b>🎓 Партнёрская программа для тренеров</b>\n\n'
        '• Создавай реферальные ссылки и получай от <b>20% до 40%</b> от подписок приглашённых.\n'
        '• Назначай подопечным тренировки, следи за их прогрессом и корректируй программу.\n'
        '• Пиши подопечным сообщения прямо в боте.',
        parse_mode=ParseMode.HTML, reply_markup=kb([[('📝 Подать заявку', 'tr:apply')]]))


async def trainer_callback(data, update, context):
    message = update.callback_query.message
    uid = update.effective_user.id
    user = get_user(uid)
    parts = data.split(':')
    if data == 'tr:apply':
        ensure_user_row(uid, update.effective_user.first_name or '')
        user = get_user(uid)
        if is_trainer(user):
            await message.reply_text(cabinet_text(user), parse_mode=ParseMode.HTML, reply_markup=cabinet_kb())
            return
        if not admin_ids():
            await message.reply_text('Приём заявок пока не настроен. Напиши администратору бота.')
            return
        set_user_field(uid, 'trainer_status', 'pending')
        uname = f' @{update.effective_user.username}' if update.effective_user.username else ''
        for admin in admin_ids():
            await notify(context.bot, admin,
                         f'🎓 Заявка в тренеры: <b>{html.escape(display_name(user))}</b>{html.escape(uname)} '
                         f'(ID <code>{uid}</code>)',
                         kb([[('✅ Одобрить', f'ad:tok:{uid}'), ('❌ Отклонить', f'ad:tno:{uid}')]]))
        await message.reply_text('✅ Заявка отправлена. Как только её одобрят, я пришлю уведомление.')
        return
    if not is_trainer(user):
        return
    if parts[1] == 'rq' and len(parts) == 4 and parts[3].isdigit() and parts[2] in ('a', 'r'):
        result = await decide_coach_request(context.bot, user, int(parts[3]), parts[2] == 'a')
        await message.reply_text(result)
        return
    if data == 'tr:home':
        await message.reply_text(cabinet_text(user), parse_mode=ParseMode.HTML, reply_markup=cabinet_kb())
    elif data == 'tr:levels':
        await message.reply_text(levels_text(referral_stats(uid)[1]), parse_mode=ParseMode.HTML,
                                 reply_markup=kb([[('⬅️ Кабинет', 'tr:home')]]))
    elif data == 'tr:links':
        await message.reply_text(links_text(user, context.bot.username), parse_mode=ParseMode.HTML,
                                 reply_markup=kb([[('➕ Создать ссылку', 'tr:newlink')], [('⬅️ Кабинет', 'tr:home')]]),
                                 disable_web_page_preview=True)
    elif data == 'tr:money':
        await message.reply_text(commissions_text(user), parse_mode=ParseMode.HTML,
                                 reply_markup=kb([[('🧾 Реквизиты для выплат', 'tr:req')], [('⬅️ Кабинет', 'tr:home')]]))
    elif data == 'tr:req':
        context.user_data['req'] = {}
        await message.reply_text('🧾 <b>Реквизиты для выплат</b>\n\nВыплаты получают только самозанятые и ИП: '
                                 'с каждой выплаты ты формируешь чек (самозанятый — в приложении «Мой налог»). '
                                 'Какой у тебя статус?', parse_mode=ParseMode.HTML,
                                 reply_markup=kb([[(v, f'tr:rs:{k}')] for k, v in LEGAL_STATUSES.items()]
                                                 + [[('⬅️ Отмена', 'tr:money')]]))
    elif data.startswith('tr:rs:') and data[6:] in LEGAL_STATUSES:
        context.user_data['req'] = {'legal_status': data[6:]}
        context.user_data['await'] = 'req_name'
        await message.reply_text('Напиши ФИО полностью, как в документах.')
    elif data.startswith('tr:rm:') and data[6:] in PAYOUT_METHODS and context.user_data.get('req', {}).get('inn'):
        context.user_data['req']['method'] = data[6:]
        context.user_data['await'] = 'req_details'
        hint = {'card': 'номер карты (16–19 цифр)', 'sbp': 'номер телефона и банк, например «+79991234567 Т-Банк»',
                'account': 'р/с, БИК и название банка'}[data[6:]]
        await message.reply_text(f'Отправь {hint}.')
    elif data == 'tr:newlink':
        context.user_data['await'] = 'link_label'
        await message.reply_text('Как назвать ссылку? Например: «Instagram», «Зал на Ленина», «Сторис». '
                                 'Название видишь только ты — по нему понятно, откуда пришли люди.')
    elif data == 'tr:asc':
        clients = trainer_clients(uid)
        if not clients:
            await message.reply_text('Подопечных пока нет. Отправь клиенту свою реферальную ссылку — '
                                     'после его согласия он появится здесь.',
                                     reply_markup=kb([[('🔗 Мои ссылки', 'tr:links')]]))
            return
        rows = [[(f'{display_name(c)} · {len(client_assignments(c["user_id"]))} назначено', f'tr:as:{c["user_id"]}')]
                for c in clients]
        rows.append([('⬅️ Кабинет', 'tr:home')])
        await message.reply_text('🎯 Кому назначить тренировку?', reply_markup=kb(rows))
    elif data == 'tr:clients':
        clients = trainer_clients(uid)
        if not clients:
            await message.reply_text('Подопечных пока нет. Отправь клиенту свою реферальную ссылку — '
                                     'после его согласия он появится здесь.',
                                     reply_markup=kb([[('🔗 Мои ссылки', 'tr:links')]]))
            return
        rows = []
        for c in clients:
            week = len(finished_workouts(c['user_id'], since=now() - timedelta(days=7)))
            plan = c.get('days') or '—'
            sub = '💳' if has_subscription(c) else '▫️'
            rows.append([(f'{sub} {display_name(c)} · {week}/{plan} за неделю', f'tr:c:{c["user_id"]}')])
        rows.append([('⬅️ Кабинет', 'tr:home')])
        await message.reply_text(f'👥 Подопечные ({len(clients)}). 💳 — с подпиской.', reply_markup=kb(rows))
    else:
        await trainer_client_callback(parts, update, context, user)


def own_client(trainer_id, cid_text):
    if not cid_text.isdigit():
        return None
    client = get_user(int(cid_text))
    return client if client and client.get('trainer_id') == trainer_id else None


async def trainer_client_callback(parts, update, context, trainer):
    """Действия тренера с подопечным и конструктор тренировки."""
    message = update.callback_query.message
    uid = trainer['user_id']
    action = parts[1]
    build = context.user_data.get('build')

    # --- конструктор тренировки ---
    if action in ('ba', 'bp', 'bpd', 'bg', 'be', 'bs', 'br', 'bw', 'bx', 'bn', 'bok', 'bd', 'bc'):
        if not build or not own_client(uid, str(build['client'])):
            await message.reply_text('Конструктор закрыт. Открой подопечного и нажми «🎯 Назначить тренировку».')
            return
        client = get_user(build['client'])
        if action == 'bc':
            context.user_data.pop('build', None)
            context.user_data.pop('await', None)
            await message.reply_text('Отменено.', reply_markup=client_card_kb(client['user_id']))
        elif action == 'ba':
            buttons = [(name, f'tr:bg:{key}') for key, name in GROUPS.items()]
            await message.reply_text('Группа мышц:', reply_markup=kb([buttons[i:i + 2] for i in range(0, len(buttons), 2)]))
        elif action == 'bg' and len(parts) == 3 and parts[2] in GROUPS:
            icons = {GYM: '🏢', HOME: '🏠'}
            rows = [[(f'{e.name} {"".join(icons[p] for p in e.places)}', f'tr:be:{e.id}')]
                    for e in _EXERCISE_LIST if e.group == parts[2]]
            await message.reply_text(f'{GROUPS[parts[2]]} — упражнение (🏢 зал, 🏠 дом):', reply_markup=kb(rows))
        elif action == 'be' and len(parts) == 3 and parts[2] in EXERCISES:
            build['cur'] = {'ex': parts[2]}
            await message.reply_text(f'{EXERCISES[parts[2]].name} — сколько подходов?',
                                     reply_markup=kb([[(str(n), f'tr:bs:{n}') for n in range(1, 7)]]))
        elif action == 'bs' and len(parts) == 3 and parts[2].isdigit() and build.get('cur'):
            build['cur']['sets'] = int(parts[2])
            ex = EXERCISES[build['cur']['ex']]
            presets = SEC_PRESETS if ex.unit == 'sec' else REP_PRESETS
            unit = ' сек' if ex.unit == 'sec' else ''
            buttons = [(f'{lo}{unit}' if lo == hi else f'{lo}–{hi}{unit}', f'tr:br:{lo}:{hi}') for lo, hi in presets]
            await message.reply_text('Сколько ' + ('секунд?' if ex.unit == 'sec' else 'повторов?'),
                                     reply_markup=kb([buttons[:3], buttons[3:]]))
        elif action == 'br' and len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit() and build.get('cur'):
            build['cur']['lo'], build['cur']['hi'] = int(parts[2]), int(parts[3])
            ex = EXERCISES[build['cur']['ex']]
            if ex.unit == 'sec':
                await add_build_item(message, context, None)
                return
            context.user_data['await'] = 'build_weight'
            what = EQUIPMENT[equipment_of(ex)][1]
            await message.reply_text(f'Рабочий вес ({what})? Отправь число в кг или нажми «Без веса» — '
                                     'тогда подопечный подберёт вес сам.',
                                     reply_markup=kb([[('Без веса', 'tr:bw')]]))
        elif action == 'bw':
            context.user_data.pop('await', None)
            await add_build_item(message, context, None)
        elif action == 'bx':
            if build['items']:
                build['items'].pop()
            await show_builder(message, context)
        elif action == 'bn':
            context.user_data['await'] = 'build_note'
            await message.reply_text('Напиши комментарий к тренировке (подопечный увидит его перед началом).')
        elif action == 'bp':
            if not profile_complete(client):
                await message.reply_text('Подопечный ещё не заполнил анкету — программы пока нет.')
                return
            await message.reply_text('Какой день программы взять за основу?', reply_markup=kb(
                [[(f'День {i + 1}: {d.title}', f'tr:bpd:{i}')] for i, d in enumerate(user_program(client))]))
        elif action == 'bpd' and len(parts) == 3 and parts[2].isdigit() and profile_complete(client):
            day = plan_day(client, int(parts[2]))
            build['items'] = items_from_day(day)
            build['title'] = day.title
            await show_builder(message, context)
        elif action == 'bok':
            if not build['items']:
                return
            days = [now().date() + timedelta(days=i) for i in range(7)]
            buttons = [(date_label(d.isoformat()), f'tr:bd:{d.isoformat()}') for d in days]
            await message.reply_text('На какой день назначить?', reply_markup=kb([buttons[:2], buttons[2:5], buttons[5:]]))
        elif action == 'bd' and len(parts) == 3:
            try:
                day_iso = date.fromisoformat(parts[2]).isoformat()
            except ValueError:
                return
            aid = save_assignment(uid, client['user_id'], day_iso, build['title'], build.get('note') or '', build['items'])
            context.user_data.pop('build', None)
            text = (f'🎯 Тренер <b>{html.escape(display_name(trainer))}</b> назначил тренировку на '
                    f'<b>{date_label(day_iso)}</b>: {html.escape(build["title"])}\n\n'
                    + '\n'.join(item_line(i, it) for i, it in enumerate(build['items'], 1)))
            if build.get('note'):
                text += f'\n\n💬 {html.escape(build["note"])}'
            sent = await notify(context.bot, client['user_id'], text, kb([[('▶️ Начать', f'cl:go:{aid}')]]))
            status = 'Подопечный получил уведомление.' if sent else 'Уведомление не доставлено — подопечный увидит её в боте.'
            await message.reply_text(f'✅ Тренировка назначена на {date_label(day_iso)}. {status}',
                                     reply_markup=client_card_kb(client['user_id']))
        return

    # --- подопечный ---
    if len(parts) < 3:
        return
    client = own_client(uid, parts[2])
    if not client:
        await message.reply_text('Этот пользователь больше не твой подопечный.')
        return
    cid = client['user_id']
    if action == 'c':
        await message.reply_text(client_card_text(client), parse_mode=ParseMode.HTML, reply_markup=client_card_kb(cid))
    elif action == 'h':
        await message.reply_text(history_text(cid), parse_mode=ParseMode.HTML,
                                 reply_markup=kb([[('⬅️ К подопечному', f'tr:c:{cid}')]]))
    elif action == 'msg':
        context.user_data['await'] = f'msg_to:{cid}'
        await message.reply_text(f'Напиши сообщение для {display_name(client)} — я перешлю его.')
    elif action == 'as':
        context.user_data['build'] = {'client': cid, 'items': [], 'title': 'Тренировка от тренера', 'note': ''}
        await show_builder(message, context)
    elif action == 'al':
        pending = client_assignments(cid)
        if not pending:
            await message.reply_text('Невыполненных назначенных тренировок нет.',
                                     reply_markup=kb([[('⬅️ К подопечному', f'tr:c:{cid}')]]))
            return
        rows = [[(f'✖️ {date_label(a["date"])} — {a["title"]}', f'tr:ax:{cid}:{a["id"]}')] for a in pending]
        rows.append([('⬅️ К подопечному', f'tr:c:{cid}')])
        await message.reply_text('🎯 Назначенные тренировки (нажми, чтобы отменить):', reply_markup=kb(rows))
    elif action == 'ax' and len(parts) == 4 and parts[3].isdigit():
        a = get_assignment(int(parts[3]))
        if a and a['trainer_id'] == uid and a['status'] == 'pending':
            set_assignment_status(a['id'], 'cancelled')
            await notify(context.bot, cid, f'Тренер отменил тренировку «{html.escape(a["title"])}» '
                                           f'на {date_label(a["date"])}.')
            await message.reply_text('Отменено.', reply_markup=client_card_kb(cid))
    elif action == 'ed':
        if not profile_complete(client):
            await message.reply_text('Подопечный ещё не заполнил анкету.')
            return
        rows = [[(('✅ ' if client['goal'] == k else '') + v, f'tr:eg:{cid}:{k}')] for k, v in GOALS.items()]
        rows += [[(('✅ ' if client['level'] == k else '') + v.split(':')[0], f'tr:el:{cid}:{k}') for k, v in LEVELS.items()]]
        rows += [[(('✅ ' if client['days'] == d else '') + f'{d} дн.', f'tr:ek:{cid}:{d}') for d in DAY_OPTIONS]]
        rows += [[(('✅ ' if client['place'] == k else '') + PLACE_SHORT[k], f'tr:ep:{cid}:{k}') for k in PLACES]]
        rows += [[('🔄 Заменить упражнение', f'tr:sw:{cid}'), ('↩️ Сбросить замены', f'tr:su:{cid}')],
                 [('⬅️ К подопечному', f'tr:c:{cid}')]]
        await message.reply_text(f'✏️ Программа {display_name(client)}: цель, опыт, тренировок в неделю, место.',
                                 reply_markup=kb(rows))
    elif action in ('eg', 'el', 'ek', 'ep') and len(parts) == 4:
        field, options, label = {'eg': ('goal', GOALS, 'цель'), 'el': ('level', LEVELS, 'уровень'),
                                 'ek': ('days', {str(d): f'{d} трен./нед.' for d in DAY_OPTIONS}, 'частота'),
                                 'ep': ('place', PLACES, 'место')}[action]
        if parts[3] not in options:
            return
        value = int(parts[3]) if field == 'days' else parts[3]
        set_user_field(cid, field, value)
        await notify(context.bot, cid, f'✏️ Тренер изменил твою программу: {label} — {html.escape(options[parts[3]])}. '
                                       f'Смотри «{BTN_PROGRAM}».')
        await message.reply_text(f'✅ Сохранено: {label} — {options[parts[3]]}. Подопечный получил уведомление.',
                                 reply_markup=kb([[('✏️ Ещё изменить', f'tr:ed:{cid}'), ('⬅️ К подопечному', f'tr:c:{cid}')]]))
    elif action == 'su':
        with connect() as c:
            c.execute('DELETE FROM user_swaps WHERE user_id=?', (cid,))
        await notify(context.bot, cid, '↩️ Тренер вернул исходные упражнения программы.')
        await message.reply_text('Замены сброшены.', reply_markup=client_card_kb(cid))
    elif action == 'sw':
        await message.reply_text('В каком дне заменить упражнение?', reply_markup=kb(
            [[(f'День {i + 1}: {d.title}', f'tr:sd:{cid}:{i}')] for i, d in enumerate(user_program(client))]))
    elif action == 'sd' and len(parts) == 4 and parts[3].isdigit():
        day = user_program(client)[int(parts[3]) % client['days']]
        await message.reply_text(f'{day.title} — какое упражнение заменить?', reply_markup=kb(
            [[(f'{i + 1}. {p.exercise.name}', f'tr:se:{cid}:{parts[3]}:{i}')] for i, p in enumerate(day.exercises)]))
    elif action == 'se' and len(parts) == 5 and parts[3].isdigit() and parts[4].isdigit():
        di, pos = int(parts[3]) % client['days'], int(parts[4])
        day = user_program(client)[di]
        if pos >= len(day.exercises):
            return
        rows = [[(alternative_label(e), f'tr:sn:{cid}:{di}:{pos}:{e.id}')]
                for e in alternatives(day, pos, client['place'])]
        await message.reply_text(f'Чем заменить «{day.exercises[pos].exercise.name}»?', reply_markup=kb(rows))
    elif action == 'sn' and len(parts) == 6 and parts[3].isdigit() and parts[4].isdigit() and parts[5] in EXERCISES:
        di, pos, new = int(parts[3]) % client['days'], int(parts[4]), EXERCISES[parts[5]]
        base = base_program(client)[di]
        if pos >= len(base.exercises) or client['place'] not in new.places:
            return
        old = user_program(client)[di].exercises[pos].exercise
        set_swap(cid, client['place'], base.exercises[pos].exercise.id, new.id)
        await notify(context.bot, cid, f'🔄 Тренер заменил в твоей программе «{html.escape(old.name)}» '
                                       f'на «{html.escape(new.name)}».')
        await message.reply_text(f'✅ «{old.name}» → «{new.name}». Подопечный получил уведомление.',
                                 reply_markup=kb([[('✏️ Ещё изменить', f'tr:ed:{cid}'), ('⬅️ К подопечному', f'tr:c:{cid}')]]))


async def add_build_item(message, context, weight):
    build = context.user_data['build']
    cur = build.pop('cur', None)
    if cur and all(k in cur for k in ('ex', 'sets', 'lo', 'hi')):
        cur['w'] = weight
        build['items'].append(cur)
    await show_builder(message, context)


# ---------- Подопечный ----------

def my_coach_text(user):
    trainer = get_user(user['trainer_id'])
    lines = [f'<b>🎓 Твой тренер: {html.escape(display_name(trainer, "тренер"))}</b>', '']
    pending = client_assignments(user['user_id'])
    if pending:
        lines.append('<b>🎯 Назначенные тренировки</b>')
        for a in pending:
            lines.append(f'• {date_label(a["date"])} — {html.escape(a["title"])} ({len(a["items"])} упр.)')
        lines.append('')
    else:
        lines += ['Назначенных тренировок пока нет — занимайся по своей программе.', '']
    msgs = recent_messages(user['trainer_id'], user['user_id'], 5)
    if msgs:
        lines.append('<b>💬 Переписка</b>')
        for m in msgs:
            who = 'Ты' if m['from_id'] == user['user_id'] else 'Тренер'
            lines.append(f'{who}: {html.escape(m["text"][:200])}')
    return '\n'.join(lines)


def my_coach_kb(user):
    rows = [[(f'▶️ {date_label(a["date"])}: {a["title"]}', f'cl:go:{a["id"]}')]
            for a in client_assignments(user['user_id'])[:5]]
    rows.append([('💬 Написать тренеру', 'cl:msg')])
    rows.append([('👋 Отключиться от тренера', 'cl:leave')])
    return kb(rows)


async def show_my_coach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or not user.get('trainer_id'):
        await update.effective_message.reply_text('У тебя пока нет тренера.')
        return
    await update.effective_message.reply_text(my_coach_text(user), parse_mode=ParseMode.HTML, reply_markup=my_coach_kb(user))


async def handle_ref_start(update, context, code):
    """Пользователь пришёл по реферальной ссылке тренера."""
    uid = update.effective_user.id
    message = update.effective_message
    link = get_ref_link(code)
    if not link:
        return
    tid = link['trainer_id']
    trainer = get_user(tid)
    if tid == uid:
        await message.reply_text('Это твоя реферальная ссылка 🙂 Отправь её клиентам.')
        return
    ensure_user_row(uid, update.effective_user.first_name or '')
    user = get_user(uid)
    if not user.get('referred_by') and not user.get('invited_by'):
        with connect() as c:
            c.execute('UPDATE users SET referred_by=?, ref_code=? WHERE user_id=?', (tid, code, uid))
        await notify(context.bot, tid, f'🎉 По ссылке «{html.escape(link["label"] or "")}» пришёл новый пользователь: '
                                       f'<b>{html.escape(display_name(user))}</b>.')
    if user.get('trainer_id') == tid:
        return
    if user.get('trainer_id'):
        await message.reply_text('У тебя уже есть тренер. Чтобы сменить, сначала отключись от текущего в «🎓 Мой тренер».')
        return
    await message.reply_text(
        f'🎓 Тебя пригласил тренер <b>{html.escape(display_name(trainer, "тренер"))}</b>.\n\n'
        'Если подключишься, тренер будет видеть твои тренировки, прогресс, рекорды и вес '
        '(данные менструального цикла — нет), сможет назначать тренировки, корректировать программу '
        'и писать тебе сообщения. Отключиться можно в любой момент.',
        parse_mode=ParseMode.HTML,
        reply_markup=kb([[('✅ Подключиться к тренеру', f'cl:join:{code}')], [('Без тренера', 'cl:nojoin')]]))


async def client_callback(data, update, context):
    message = update.callback_query.message
    uid = update.effective_user.id
    user = get_user(uid)
    parts = data.split(':')
    if parts[1] == 'join' and len(parts) == 3:
        link = get_ref_link(parts[2])
        if not link or not user or user.get('trainer_id') or link['trainer_id'] == uid:
            return
        start_coaching(uid, link['trainer_id'])
        trainer = get_user(link['trainer_id'])
        await message.edit_text(f'✅ Ты подключён к тренеру {display_name(trainer, "")}. '
                                'Назначенные тренировки и сообщения появятся в «🎓 Мой тренер».')
        if profile_complete(user):
            await message.reply_text('Меню обновлено 👇', reply_markup=menu_for(get_user(uid)))
        await notify(context.bot, link['trainer_id'],
                     f'👥 Новый подопечный: <b>{html.escape(display_name(user))}</b>. Он в «{BTN_CABINET}» → «Подопечные».',
                     kb([[('👤 Открыть', f'tr:c:{uid}')]]))
    elif parts[1] == 'nojoin':
        await message.edit_text('Хорошо, занимайся самостоятельно. Подключиться к тренеру можно позже по его ссылке.')
    elif parts[1] == 'msg' and user and user.get('trainer_id'):
        context.user_data['await'] = f'msg_to:{user["trainer_id"]}'
        await message.reply_text('Напиши сообщение тренеру — я перешлю его.')
    elif parts[1] == 'leave' and user and user.get('trainer_id'):
        await message.reply_text('Отключиться от тренера? Он перестанет видеть твой прогресс.',
                                 reply_markup=kb([[('Да, отключиться', 'cl:leave2'), ('Отмена', 'cl:stay')]]))
    elif parts[1] == 'leave2' and user and user.get('trainer_id'):
        tid = user['trainer_id']
        end_coaching(uid)
        for a in client_assignments(uid):
            set_assignment_status(a['id'], 'cancelled')
        await notify(context.bot, tid, f'👋 {html.escape(display_name(user))} отключился от тренировок с тобой.')
        await message.reply_text('Готово, ты больше не подключён к тренеру.', reply_markup=menu_for(get_user(uid)))
    elif parts[1] == 'stay':
        await message.edit_text('Остаёмся с тренером 💪')
    elif parts[1] == 'go' and len(parts) == 3 and parts[2].isdigit():
        await start_assigned_workout(message, context, user, int(parts[2]))


async def start_assigned_workout(message, context, user, aid):
    a = get_assignment(aid)
    if not a or a['client_id'] != user['user_id']:
        return
    if a['status'] != 'pending':
        await message.reply_text('Эта тренировка уже выполнена или отменена.')
        return
    if not profile_complete(user):
        await message.reply_text('Сначала заполни короткую анкету — /start.')
        return
    if context.user_data.get('wk'):
        await message.reply_text('Сначала заверши текущую тренировку.')
        return
    wid = start_workout(user['user_id'], -1, f'🎯 {a["title"]}')
    context.user_data['wk'] = {
        'wid': wid, 'day': user['day_index'], 'ex_pos': 0, 'set_no': 1,
        'mods': {'sets': 0, 'rest': 0, 'no_progress': False, 'notes': []},
        'place': place_today(user, context.user_data), 'stage': 'warmup',
        'weights': {it['ex']: float(it['w']) for it in a['items'] if it.get('w')},
        'assigned': aid, 'items': a['items'], 'atitle': a['title'], 'anote': a['note'],
        'started': now().isoformat(timespec='seconds')}
    context.user_data.pop('await', None)
    if a['note']:
        await message.reply_text(f'💬 Комментарий тренера: {a["note"]}')
    await start_cardio_stage(message, context, user, 'warmup')


async def deliver_message(update, context, to_id, text):
    """Сообщение между тренером и подопечным (в обе стороны)."""
    uid = update.effective_user.id
    me, other = get_user(uid), get_user(to_id)
    allowed = other and ((other.get('trainer_id') == uid and is_trainer(me)) or (me and me.get('trainer_id') == to_id))
    message = update.effective_message
    if not allowed:
        await message.reply_text('Не получилось отправить: вы больше не связаны как тренер и подопечный.')
        return
    save_message(uid, to_id, text)
    if other.get('trainer_id') == uid:
        head = f'💬 <b>Сообщение от тренера {html.escape(display_name(me, ""))}</b>'
        markup = kb([[('↩️ Ответить', 'cl:msg')]])
    else:
        head = f'💬 <b>Сообщение от подопечного {html.escape(display_name(me))}</b>'
        markup = kb([[('↩️ Ответить', f'tr:msg:{uid}'), ('👤 Профиль', f'tr:c:{uid}')]])
    sent = await notify(context.bot, to_id, f'{head}\n\n{html.escape(text)}', markup)
    await message.reply_text('✅ Отправлено.' if sent else '⚠️ Сохранил, но доставить не удалось — '
                                                          'возможно, получатель остановил бота.')


# ---------- Админ: тренеры, приглашения, подписки ----------

def create_trainer_invite(admin_id):
    alphabet = 'abcdefghijkmnpqrstuvwxyz23456789'
    with connect() as c:
        for _ in range(20):
            code = ''.join(secrets.choice(alphabet) for _ in range(10))
            if not c.execute('SELECT 1 FROM trainer_invites WHERE code=?', (code,)).fetchone():
                c.execute('INSERT INTO trainer_invites(code, created_by, created_at) VALUES(?,?,?)',
                          (code, admin_id, now().isoformat(timespec='seconds')))
                return code
    raise RuntimeError('Не удалось создать код приглашения')


def use_trainer_invite(code, uid):
    """True — если приглашение действительно и теперь использовано этим пользователем."""
    with connect() as c:
        cur = c.execute('UPDATE trainer_invites SET used_by=?, used_at=? WHERE code=? AND used_by IS NULL',
                        (uid, now().isoformat(timespec='seconds'), code))
        return cur.rowcount == 1


def make_trainer(uid):
    with connect() as c:
        c.execute("UPDATE users SET is_trainer=1, trainer_status='approved' WHERE user_id=?", (uid,))


def admin_trainers_text():
    with connect() as c:
        trainers = [dict(r) for r in c.execute('SELECT * FROM users WHERE is_trainer=1 ORDER BY name')]
        pending = [dict(r) for r in c.execute("SELECT * FROM users WHERE trainer_status='pending' AND is_trainer=0")]
    lines = ['<b>🎓 Тренеры</b>', '']
    if not trainers:
        lines.append('Тренеров пока нет.')
    for t in trainers:
        invited, subs = referral_stats(t['user_id'])
        name, _, percent, _ = trainer_level(subs)[1]
        lines.append(f'• {html.escape(display_name(t))} (ID <code>{t["user_id"]}</code>) — {name} {percent}%, '
                     f'подписчиков {subs}, пришло {invited}, подопечных {len(trainer_clients(t["user_id"]))}')
    if pending:
        lines += ['', f'⏳ Заявок на рассмотрении: {len(pending)}']
    lines += ['', 'Пригласи тренера одноразовой ссылкой — по ней он сразу получит кабинет без заявки.']
    return '\n'.join(lines), pending


def add_subscription(uid, days):
    """Продлевает подписку на days дней (0 или меньше — отменяет). Возвращает новую дату или None."""
    user = get_user(uid)
    if not user:
        return False
    if days <= 0:
        set_user_field(uid, 'sub_until', None)
        return None
    start = max(now().date(), date.fromisoformat(user['sub_until'])) if user.get('sub_until') else now().date()
    until = (start + timedelta(days=days)).isoformat()
    set_user_field(uid, 'sub_until', until)
    return until


async def grant_subscription(message, context, text):
    m = re.fullmatch(r'\s*(\d{4,})\s+(-?\d{1,4})(?:\s+(\d+(?:[.,]\d{1,2})?))?(?:\s+(coach|self|тренер|сам))?\s*',
                     text or '', re.I)
    if not m:
        await message.reply_text(SUB_HELP, parse_mode=ParseMode.HTML)
        return False
    uid, days = int(m.group(1)), int(m.group(2))
    if not get_user(uid):
        await message.reply_text('Пользователь с таким ID не найден (он должен хотя бы раз запустить бота).')
        return False
    paid_note = ''
    if m.group(3) and days > 0:
        amount = float(m.group(3).replace(',', '.'))
        kind = {'тренер': 'coach', 'сам': 'self'}.get((m.group(4) or '').lower(), (m.group(4) or '').lower())
        if not kind:
            kind = 'coach' if get_user(uid).get('trainer_id') else 'self'
        pid = record_payment(uid, amount, kind, days, 'manual', f'admin {message.chat_id}')
        with connect() as c:
            coms = c.execute('SELECT trainer_id, type, amount FROM commissions WHERE payment_id=?', (pid,)).fetchall()
        paid_note = f'\n💳 Оплата №{pid}: {money(amount)} ({"с тренером" if kind == "coach" else "без тренера"}).'
        for com in coms:
            paid_note += (f'\n→ {display_name(get_user(com["trainer_id"]))}: {money(com["amount"])} '
                          f'({"ведение" if com["type"] == "coaching" else "реферал"}), доступно через {hold_days()} дн.')
            await notify(context.bot, com['trainer_id'], f'💰 Начисление <b>{money(com["amount"])}</b> за оплату '
                                                         f'{html.escape(display_name(get_user(uid)))}. '
                                                         f'Станет доступно к выплате через {hold_days()} дн.')
        if not coms:
            paid_note += ('\nНачислений нет: у пользователя нет тренера.' if kind == 'coach'
                          else '\nНачислений нет: пользователь пришёл не по ссылке тренера.')
    result = add_subscription(uid, days)
    if result is False:
        await message.reply_text('Пользователь с таким ID не найден (он должен хотя бы раз запустить бота).')
        return False
    user = get_user(uid)
    if result:
        until = f'{date.fromisoformat(result):%d.%m.%Y}'
        await notify(context.bot, uid, f'💳 Подписка активна до <b>{until}</b>. Спасибо! 💪')
        await message.reply_text(f'✅ {display_name(user)}: подписка до {until}.{paid_note}')
    else:
        await message.reply_text(f'Подписка {display_name(user)} отменена.')
    return True


SUB_HELP = ('💳 Отправь <code>ID ДНЕЙ СУММА</code>, например <code>123456789 30 990</code> — подписка продлится на 30 дней, '
            'оплата 990 ₽ запишется и тренерам начислится их доля. Тариф определяется сам: есть тренер — «с тренером», '
            'нет — «без тренера»; можно указать явно: <code>123456789 30 990 self</code> или <code>coach</code>.\n'
            'Без суммы — подарочная подписка без начислений. 0 дней — отменить подписку.\n'
            'Возврат оплаты: <code>/refund НОМЕР_ОПЛАТЫ</code>.')


def admin_payouts_text():
    refresh_commissions()
    with connect() as c:
        rows = c.execute('''SELECT trainer_id, SUM(CASE WHEN status='available' AND payout_id IS NULL THEN amount ELSE 0 END) av,
                                   SUM(CASE WHEN status='pending' THEN amount ELSE 0 END) pe
                            FROM commissions GROUP BY trainer_id HAVING av<>0 OR pe<>0''').fetchall()
    lines = ['<b>💸 Выплаты тренерам</b>', '',
             f'Начисления «ожидают» {hold_days()} дн. (на случай возврата), потом становятся доступны. '
             f'Раз в месяц сформируй реестр: в него попадут тренеры с суммой от {money(min_payout())} и реквизитами.', '']
    for r in rows:
        req = get_requisites(r['trainer_id'])
        lines.append(f'• {html.escape(display_name(get_user(r["trainer_id"]) or {"user_id": r["trainer_id"]}))}: '
                     f'доступно <b>{money(r["av"])}</b>, ожидает {money(r["pe"])}' + ('' if requisites_ok(req) else ' · ⚠️ нет реквизитов'))
    if not rows:
        lines.append('Начислений к выплате нет.')
    op = open_payouts()
    if op:
        lines += ['', '<b>Сформированы, ждут перевода:</b>']
        for p in op:
            lines.append(f'№{p["id"]} · {html.escape(p["full_name"])} · {LEGAL_STATUSES.get(p["legal_status"], "")} · '
                         f'<b>{money(p["amount"])}</b>')
    return '\n'.join(lines)


def admin_payouts_kb():
    rows = [[(f'✅ №{p["id"]} выплачено · {money(p["amount"])}', f'ad:paid:{p["id"]}')] for p in open_payouts()]
    rows.append([('📄 Сформировать реестр', 'ad:payreg')])
    rows.append([('⬅️ Админка', 'ad:menu')])
    return kb(rows)


async def refund_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args or []
    if len(args) != 1 or not args[0].isdigit():
        await update.effective_message.reply_text('Формат: /refund НОМЕР_ОПЛАТЫ (номер приходит при выдаче подписки).')
        return
    ok = refund_payment(int(args[0]))
    await update.effective_message.reply_text('↩️ Возврат учтён: начисления отменены, уже выплаченные удержатся из '
                                              'следующей выплаты. Подписку при необходимости отмени: /sub ID 0.'
                                              if ok else 'Оплата не найдена или уже возвращена.')


async def sub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await grant_subscription(update.effective_message, context, ' '.join(context.args or []))


async def handle_coach_invite(update, context, code):
    uid = update.effective_user.id
    message = update.effective_message
    ensure_user_row(uid, update.effective_user.first_name or '')
    user = get_user(uid)
    if is_trainer(user):
        await message.reply_text('Ты уже в партнёрской программе 🙂', reply_markup=menu_for(user))
        return True
    if not use_trainer_invite(code, uid):
        await message.reply_text('Ссылка-приглашение недействительна или уже использована. '
                                 'Попроси у администратора новую.')
        return False
    make_trainer(uid)
    user = get_user(uid)
    uname = f' @{update.effective_user.username}' if update.effective_user.username else ''
    for admin in admin_ids():
        await notify(context.bot, admin, f'🎓 По приглашению подключился тренер: <b>{html.escape(display_name(user))}</b>'
                                         f'{html.escape(uname)} (ID <code>{uid}</code>).')
    await message.reply_text('🎉 Добро пожаловать в партнёрскую программу! Кабинет тренера — кнопка '
                             f'«{BTN_CABINET}» в меню.', reply_markup=menu_for(user))
    await message.reply_text(cabinet_text(user), parse_mode=ParseMode.HTML, reply_markup=cabinet_kb())
    return True


def build_app(token):
    init_db()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    persistence = PicklePersistence(filepath=STATE_PATH)
    app = Application.builder().token(token).persistence(persistence).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('today', show_today))
    app.add_handler(CommandHandler('program', show_program))
    app.add_handler(CommandHandler('progress', show_progress))
    app.add_handler(CommandHandler('weight', show_weight))
    app.add_handler(CommandHandler('goals', show_goals))
    app.add_handler(CommandHandler('cycle', show_cycle))
    app.add_handler(CommandHandler('settings', settings))
    app.add_handler(CommandHandler('finish', finish_command))
    app.add_handler(CommandHandler('group', group_command))
    app.add_handler(CommandHandler('trainer', trainer_cabinet))
    app.add_handler(CommandHandler('coach', show_my_coach))
    app.add_handler(CommandHandler('sub', sub_command))
    app.add_handler(CommandHandler('refund', refund_command))
    app.add_handler(CommandHandler('friends', show_friends))
    app.add_handler(CommandHandler('cancel', cancel))
    app.add_handler(CommandHandler('backup', backup_command))
    app.add_handler(CommandHandler('admin', admin_command))
    app.add_handler(CallbackQueryHandler(cs_callback, pattern=r'^cs:'))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo_handler))
    app.add_error_handler(on_error)
    return app


async def handle_app_login(update, context, code):
    """Вход в мобильное приложение: пользователь открыл ссылку t.me/<бот>?start=login_<код>."""
    try:
        import api
    except ImportError:  # pragma: no cover
        from fitness_bot import api
    uid = update.effective_user.id
    ensure_user_row(uid, update.effective_user.first_name or '')
    if api.confirm_login_code(code, uid):
        await update.effective_message.reply_text(
            '✅ Вход в приложение FitHelper подтверждён — вернись в приложение.\n'
            'Тренировки, программа и прогресс общие для бота и приложения.')
    else:
        await update.effective_message.reply_text('Ссылка для входа устарела. Нажми «Войти через Telegram» '
                                                  'в приложении ещё раз.')


async def run_bot_and_api(token):
    """Бот и HTTP API приложения в одном процессе: общая база и аккаунты."""
    import uvicorn
    try:
        import api
    except ImportError:  # pragma: no cover
        from fitness_bot import api
    application = build_app(token)
    port = int(os.environ.get('PORT') or os.environ.get('FITNESS_API_PORT') or 8080)
    server = uvicorn.Server(uvicorn.Config(api.create_app(application.bot), host='0.0.0.0', port=port,
                                           log_level='warning', proxy_headers=True, forwarded_allow_ips='*'))
    async with application:
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        print(f'Фитнес-бот запущен. Версия: {BOT_VERSION}. Данные: {DATA_DIR}. API приложения: порт {port}', flush=True)
        rewards = asyncio.create_task(rewards_loop(application.bot))
        try:
            await server.serve()
        finally:
            rewards.cancel()
            await application.updater.stop()
            await application.stop()


async def rewards_loop(bot):
    """Раз в 30 минут начисляет созревшие награды за друзей."""
    while True:
        try:
            await deliver_friend_rewards(bot)
        except Exception:  # noqa: BLE001 — фоновая задача не должна падать
            log.exception('Ошибка начисления наград за друзей')
        await asyncio.sleep(1800)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    token = (os.environ.get('FITNESS_BOT_TOKEN') or os.environ.get('BOT_TOKEN') or '').strip()
    if not token:
        print('Не задан FITNESS_BOT_TOKEN. Укажи его в переменных окружения или в fitness_bot/.env', flush=True)
        return
    if os.environ.get('FITNESS_API', '1') != '0':
        asyncio.run(run_bot_and_api(token))
        return
    app = build_app(token)
    print(f'Фитнес-бот запущен. Версия: {BOT_VERSION}. Данные: {DATA_DIR}', flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
