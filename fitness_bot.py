"""Фитнес-бот для Telegram: программа тренировок, дневник подходов, цели и прогресс.

Запуск:
    pip install -r fitness_bot/requirements.txt
    FITNESS_BOT_TOKEN=123:ABC python fitness_bot/fitness_bot.py

Токен можно положить в файл .env рядом с ботом (FITNESS_BOT_TOKEN=...).
"""
import asyncio
import html
import logging
import os
import re
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
BOT_VERSION = '2026-11-11 · групповые тренировки'


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
                     'cycle_len', 'period_len', 'place')
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


def menu_for(user):
    last = [BTN_CYCLE, BTN_SETTINGS] if user and user.get('gender') == 'f' else [BTN_SETTINGS]
    rows = [[BTN_TODAY], [BTN_PROGRAM, BTN_PROGRESS], [BTN_WEIGHT, BTN_GOALS], last]
    if user and is_admin(user.get('user_id')):
        rows.append([BTN_ADMIN])
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
    day = plan_day(user, wk['day'], wk.get('mods'), wk.get('place'), wk.get('swaps'))
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
    rows.append([('📖 Техника', f't:{p.exercise.id}'), ('🔄 Заменить', 'sw:l')])
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
    day = plan_day(user, wk['day'], wk.get('mods'), wk.get('place'), wk.get('swaps'))
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
    day = None if group else plan_day(user, wk['day'], wk.get('mods'), wk.get('place'), wk.get('swaps'))
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


def week_progress_line(user):
    week = finished_workouts(user['user_id'], since=now() - timedelta(days=7))
    return f'На этой неделе: {len(week)} из {user["days"]} тренировок {progress_bar(len(week) / user["days"])}'


async def save_past_group(message, uid, group_type, minutes):
    user = get_user(uid)
    log_past_group(uid, group_type, minutes)
    await message.reply_text(
        f'✅ Отметил: <b>{html.escape(GROUP_TYPES[group_type][0])}</b> — {minutes} мин.\n\n{week_progress_line(user)}',
        parse_mode=ParseMode.HTML, reply_markup=menu_for(user))


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
    return plan_day(user, wk['day'], wk.get('mods'), wk.get('place'), wk.get('swaps')).exercises[wk['ex_pos']]


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
    await update.effective_message.reply_text(
        f'<b>⚙️ Настройки</b>\nПол: {GENDERS[user["gender"]]}\nВозраст: {AGES[user["age"]]}\n'
        f'Цель: {GOALS[user["goal"]]}\nОпыт: {LEVELS[user["level"]]}\n'
        f'Где: {PLACES[user["place"]]}\nТренировок в неделю: {user["days"]}\nТаймер отдыха: {timer}',
        parse_mode=ParseMode.HTML,
        reply_markup=kb([[('🔄 Заполнить анкету заново', 's:redo')],
                         [(f'📍 Место по умолчанию: {PLACE_SHORT[user["place"]]}', 's:place')],
                         [(f'Таймер отдыха: {timer}', 's:timer')]]
                        + ([[(f'↩️ Вернуть исходные упражнения ({count_swaps(user["user_id"])})', 's:unswap')]]
                           if count_swaps(user['user_id']) else [])))


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
    await update.effective_message.reply_text(weight_text(update.effective_user.id), parse_mode=ParseMode.HTML)


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
    lines += ['', f'На этой неделе: {len(week)} из {user["days"]} тренировок {progress_bar(len(week) / user["days"])}',
              f'Следующая — день {(wk["day"] + 1) % user["days"] + 1}. Не забудь про сон и белок 🍗']
    await message.reply_text('\n'.join(lines), parse_mode=ParseMode.HTML, reply_markup=menu_for(user))


async def log_set(update: Update, context: ContextTypes.DEFAULT_TYPE, weight, reps):
    uid = update.effective_user.id
    wk = context.user_data['wk']
    user = get_user(uid)
    day = plan_day(user, wk['day'], wk.get('mods'), wk.get('place'), wk.get('swaps'))
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
    day = plan_day(user, wk['day'], wk.get('mods'), wk.get('place'), wk.get('swaps'))
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
            ex = plan_day(user, wk['day'], wk.get('mods'), wk.get('place'), wk.get('swaps')).exercises[wk['ex_pos']].exercise
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
              BTN_ADMIN: admin_panel}
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
            p = plan_day(user, wk['day'], wk.get('mods'), wk.get('place'), wk.get('swaps')).exercises[wk['ex_pos']]
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
    return kb([[('📸 Фото упражнений', 'ad:groups')], [('💾 Резервная копия базы', 'ad:backup')]])


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


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фото от администратора → картинка техники упражнения."""
    uid = update.effective_user.id
    message = update.effective_message
    if not is_admin(uid):
        return
    target = None
    awaiting = context.user_data.get('await') or ''
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
    app.add_handler(CommandHandler('cancel', cancel))
    app.add_handler(CommandHandler('backup', backup_command))
    app.add_handler(CommandHandler('admin', admin_command))
    app.add_handler(CallbackQueryHandler(cs_callback, pattern=r'^cs:'))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo_handler))
    app.add_error_handler(on_error)
    return app


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    token = (os.environ.get('FITNESS_BOT_TOKEN') or os.environ.get('BOT_TOKEN') or '').strip()
    if not token:
        print('Не задан FITNESS_BOT_TOKEN. Укажи его в переменных окружения или в fitness_bot/.env', flush=True)
        return
    app = build_app(token)
    print(f'Фитнес-бот запущен. Версия: {BOT_VERSION}. Данные: {DATA_DIR}', flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
