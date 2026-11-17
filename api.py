"""HTTP API для мобильного приложения FitHelper.

Работает в одном процессе с ботом (общая база и аккаунты), см. fitness_bot.main().
Все маршруты — под /api, веб-версия приложения (папка web/) отдаётся с корня.

Локальный запуск без бота (для разработки):  python api.py
"""
import base64
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import fitness_bot as fb

WEB_DIR = Path(os.environ.get('FITNESS_WEB_DIR', fb.ROOT / 'web'))
LOGIN_TTL_MIN = 10
SESSION_TTL_DAYS = 180

_photo_cache = {}


# ======================================================================
# Авторизация: вход через Telegram-бота
# ======================================================================

def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_login_code():
    code = secrets.token_urlsafe(18).replace('-', 'x').replace('_', 'y')
    with fb.connect() as c:
        c.execute('DELETE FROM login_codes WHERE created_at<?',
                  ((fb.now() - timedelta(minutes=LOGIN_TTL_MIN)).isoformat(timespec='seconds'),))
        c.execute('INSERT INTO login_codes(code, created_at) VALUES(?,?)', (code, fb.now().isoformat(timespec='seconds')))
    return code


def confirm_login_code(code, uid):
    """Вызывается ботом, когда пользователь открыл ссылку входа. True — код принят."""
    with fb.connect() as c:
        cur = c.execute('UPDATE login_codes SET user_id=? WHERE code=? AND user_id IS NULL AND created_at>=?',
                        (uid, code, (fb.now() - timedelta(minutes=LOGIN_TTL_MIN)).isoformat(timespec='seconds')))
        return cur.rowcount == 1


def exchange_login_code(code):
    """Код подтверждён в боте → выдаём токен сессии (один раз)."""
    with fb.connect() as c:
        row = c.execute('SELECT user_id FROM login_codes WHERE code=?', (code,)).fetchone()
        if not row or not row['user_id']:
            return None, None
        c.execute('DELETE FROM login_codes WHERE code=?', (code,))
        token = secrets.token_urlsafe(32)
        c.execute('INSERT INTO api_sessions(token_hash, user_id, created_at, last_seen) VALUES(?,?,?,?)',
                  (_hash(token), row['user_id'], fb.now().isoformat(timespec='seconds'), fb.now().isoformat(timespec='seconds')))
    return token, row['user_id']


def create_session(uid):
    """Сессия без входа через бота — для тестов и разработки."""
    token = secrets.token_urlsafe(32)
    with fb.connect() as c:
        c.execute('INSERT INTO api_sessions(token_hash, user_id, created_at, last_seen) VALUES(?,?,?,?)',
                  (_hash(token), uid, fb.now().isoformat(timespec='seconds'), fb.now().isoformat(timespec='seconds')))
    return token


def current_user(authorization: str = Header(default='')):
    token = authorization.removeprefix('Bearer ').strip()
    if not token:
        raise HTTPException(401, 'Нужен вход')
    with fb.connect() as c:
        row = c.execute('SELECT * FROM api_sessions WHERE token_hash=?', (_hash(token),)).fetchone()
        if not row or row['created_at'] < (fb.now() - timedelta(days=SESSION_TTL_DAYS)).isoformat(timespec='seconds'):
            raise HTTPException(401, 'Сессия истекла, войди снова')
        c.execute('UPDATE api_sessions SET last_seen=? WHERE token_hash=?', (fb.now().isoformat(timespec='seconds'), row['token_hash']))
    user = fb.get_user(row['user_id'])
    if not user:
        raise HTTPException(401, 'Пользователь не найден')
    return user


def profile_user(user=Depends(current_user)):
    if not fb.profile_complete(user):
        raise HTTPException(409, 'Сначала заполни анкету')
    return user


# ======================================================================
# Сериализация
# ======================================================================

def ex_json(ex, user=None):
    eq = fb.equipment_of(ex)
    name, hint, steps = fb.EQUIPMENT[eq]
    return {
        'id': ex.id, 'name': ex.name, 'group': ex.group, 'group_name': fb.GROUPS[ex.group],
        'places': list(ex.places), 'compound': ex.compound, 'bodyweight': ex.bodyweight, 'unit': ex.unit,
        'tip': ex.tip, 'equipment': {'key': eq, 'name': name, 'hint': hint, 'steps': list(steps)},
        'start_weight': fb.start_weight(ex, user) if user else '',
        'frames': fb.frame_count(ex.id),
    }


def default_weight(user, ex, prev):
    if prev:
        return max(w for w, _ in prev)
    if fb.equipment_of(ex) == 'bodyweight':
        return 0.0
    hint = fb.re.search(r'\d+(?:\.\d+)?', fb.start_weight(ex, user))
    return float(hint.group(0)) if hint else 0.0


def planned_json(user, p, no_progress=False):
    prev = fb.previous_sets(user['user_id'], p.exercise.id)
    return {
        **ex_json(p.exercise, user), 'role': p.role,
        'sets': p.presc.sets, 'lo': p.presc.lo, 'hi': p.presc.hi, 'rest': p.presc.rest,
        'plan_text': p.presc.text(), 'rep_options': fb.rep_options(p.presc),
        'prev': [[w, r] for w, r in prev],
        'advice': fb.advice(p.exercise, p.presc, prev, user.get('gender') or 'm', no_progress,
                            fb.start_weight(p.exercise, user)),
        'weight': default_weight(user, p.exercise, prev),
    }


def day_json(user, day, no_progress=False):
    return {'title': day.title, 'groups': day.groups, 'note': day.note,
            'exercises': [planned_json(user, p, no_progress) for p in day.exercises]}


def assignment_json(a):
    items = []
    for it in a['items']:
        ex = fb.EXERCISES.get(it['ex'])
        if ex:
            items.append({'id': ex.id, 'name': ex.name, 'sets': it['sets'], 'lo': it['lo'], 'hi': it['hi'],
                          'weight': it.get('w'), 'unit': ex.unit})
    return {'id': a['id'], 'date': a['date'], 'date_label': fb.date_label(a['date']), 'title': a['title'],
            'note': a['note'] or '', 'items': items, 'status': a['status']}


def week_strip(uid):
    today = fb.now().date()
    monday = today - timedelta(days=today.weekday())
    done = {w['finished_at'][:10] for w in fb.finished_workouts(uid, since=datetime.combine(monday, datetime.min.time()))}
    return [{'label': lbl, 'date': (monday + timedelta(days=i)).isoformat(),
             'done': (monday + timedelta(days=i)).isoformat() in done, 'today': monday + timedelta(days=i) == today}
            for i, lbl in enumerate(['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'])]


def streak_days(uid):
    """Сколько дней подряд (по сегодня или вчера) были тренировки."""
    days = {w['finished_at'][:10] for w in fb.finished_workouts(uid, since=fb.now() - timedelta(days=400))}
    d = fb.now().date()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


def me_json(user):
    trainer = fb.get_user(user['trainer_id']) if user.get('trainer_id') else None
    return {
        'id': user['user_id'], 'name': user.get('name') or '', 'profile_complete': fb.profile_complete(user),
        'profile': {k: user.get(k) for k in ('gender', 'age', 'goal', 'level', 'days', 'place', 'cycle_tracking',
                                             'cycle_len', 'period_len', 'period_start', 'target_weight', 'rest_timer')},
        'theme': user.get('theme'),
        'subscription_until': user.get('sub_until') if fb.has_subscription(user) else None,
        'is_trainer': fb.is_trainer(user), 'is_admin': fb.is_admin(user['user_id']),
        'trainer': {'id': trainer['user_id'], 'name': fb.display_name(trainer, 'Тренер')} if trainer else None,
        'version': fb.BOT_VERSION,
    }


# ======================================================================
# Модели запросов
# ======================================================================

class LoginPoll(BaseModel):
    code: str


class ProfileIn(BaseModel):
    gender: str
    age: str
    goal: str
    level: str
    days: int
    place: str
    cycle_tracking: bool = False
    period_start: str | None = None
    cycle_len: int | None = None
    period_len: int | None = None


class SettingsIn(BaseModel):
    place: str | None = None
    rest_timer: bool | None = None
    target_weight: float | None = None
    theme: str | None = None


THEMES = ('classic', 'men', 'women', 'premium', 'steel', 'light')


class StartIn(BaseModel):
    day: int | None = None
    place: str | None = None
    standard: bool = False
    assignment_id: int | None = None


class SetIn(BaseModel):
    exercise_id: str
    set_no: int = Field(ge=1, le=20)
    weight: float = Field(ge=0, le=1000)
    reps: int = Field(ge=1, le=600)


class CardioIn(BaseModel):
    phase: str
    kind: str
    minutes: int = Field(ge=1, le=180)


class FinishIn(BaseModel):
    assignment_id: int | None = None


class WeightIn(BaseModel):
    weight: float = Field(ge=20, le=400)


class SwapIn(BaseModel):
    day: int
    pos: int
    place: str
    exercise_id: str


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class GroupLogIn(BaseModel):
    type: str
    minutes: int = Field(ge=5, le=300)


class LinkIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)


class ItemIn(BaseModel):
    ex: str
    sets: int = Field(ge=1, le=10)
    lo: int = Field(ge=1, le=600)
    hi: int = Field(ge=1, le=600)
    w: float | None = Field(default=None, ge=0, le=1000)


class AssignmentIn(BaseModel):
    date: str
    title: str = Field(min_length=1, max_length=80)
    note: str = Field(default='', max_length=500)
    items: list[ItemIn] = Field(min_length=1, max_length=20)


class TrainerProfileIn(BaseModel):
    bio: str = Field(default='', max_length=1500)
    specializations: list[str] = Field(default_factory=list, max_length=9)
    experience_years: int | None = Field(default=None, ge=0, le=60)
    certificates: str = Field(default='', max_length=1000)
    city: str = Field(default='', max_length=60)
    format: str = 'both'
    max_clients: int | None = Field(default=None, ge=1, le=500)
    listed: bool = True


class PhotoIn(BaseModel):
    data: str = Field(max_length=4_000_000)
    mime: str = 'image/jpeg'


class RequestIn(BaseModel):
    message: str = Field(default='', max_length=500)


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = Field(default='', max_length=1000)


class MeasurementsIn(BaseModel):
    chest: float | None = None
    waist: float | None = None
    hips: float | None = None
    arm: float | None = None
    thigh: float | None = None


class GoalIn(BaseModel):
    goal: int


class RequisitesIn(BaseModel):
    legal_status: str
    full_name: str = Field(max_length=120)
    inn: str = Field(max_length=20)
    method: str
    details: str = Field(max_length=200)


class ProgramPatch(BaseModel):
    goal: str | None = None
    level: str | None = None
    days: int | None = None
    place: str | None = None


# ======================================================================
# Приложение
# ======================================================================

def create_app(bot=None):
    """bot — экземпляр telegram.Bot (для фото из Telegram и сообщений тренеру); None — без бота."""
    fb.init_db()
    app = FastAPI(title='FitHelper API', docs_url='/api/docs', openapi_url='/api/openapi.json')
    app.state.bot = bot
    app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

    # ---------- вход ----------
    @app.post('/api/auth/start')
    def auth_start():
        code = create_login_code()
        username = getattr(bot, 'username', None) or os.environ.get('FITNESS_BOT_USERNAME', 'FitHelperTop_bot')
        return {'code': code, 'url': f'https://t.me/{username}?start=login_{code}', 'expires_in': LOGIN_TTL_MIN * 60}

    @app.post('/api/auth/poll')
    def auth_poll(body: LoginPoll):
        token, uid = exchange_login_code(body.code)
        if not token:
            return {'status': 'pending'}
        return {'status': 'ok', 'token': token, 'me': me_json(fb.get_user(uid))}

    @app.post('/api/auth/logout')
    def auth_logout(authorization: str = Header(default='')):
        token = authorization.removeprefix('Bearer ').strip()
        with fb.connect() as c:
            c.execute('DELETE FROM api_sessions WHERE token_hash=?', (_hash(token),))
        return {'ok': True}

    # ---------- справочники и профиль ----------
    @app.get('/api/meta')
    def meta():
        return {'genders': fb.GENDERS, 'ages': fb.AGES, 'goals': fb.GOALS, 'levels': fb.LEVELS, 'places': fb.PLACES,
                'day_options': list(fb.DAY_OPTIONS), 'groups': fb.GROUPS,
                'group_types': {k: v[0] for k, v in fb.GROUP_TYPES.items()}}

    @app.get('/api/me')
    def me(user=Depends(current_user)):
        return me_json(user)

    @app.put('/api/me/profile')
    def put_profile(body: ProfileIn, user=Depends(current_user)):
        if (body.gender not in fb.GENDERS or body.age not in fb.AGES or body.goal not in fb.GOALS
                or body.level not in fb.LEVELS or body.days not in fb.DAY_OPTIONS or body.place not in fb.PLACES):
            raise HTTPException(422, 'Неверные значения анкеты')
        profile = body.model_dump()
        profile['cycle_tracking'] = 1 if (body.cycle_tracking and body.gender == 'f') else 0
        fb.save_user(user['user_id'], user.get('name') or '', profile)
        return me_json(fb.get_user(user['user_id']))

    @app.patch('/api/me/settings')
    def patch_settings(body: SettingsIn, user=Depends(profile_user)):
        if body.place is not None:
            if body.place not in fb.PLACES:
                raise HTTPException(422, 'Неверное место')
            fb.set_user_field(user['user_id'], 'place', body.place)
        if body.rest_timer is not None:
            fb.set_user_field(user['user_id'], 'rest_timer', 1 if body.rest_timer else 0)
        if body.target_weight is not None:
            fb.set_user_field(user['user_id'], 'target_weight', body.target_weight or None)
        if body.theme is not None:
            if body.theme not in THEMES:
                raise HTTPException(422, 'Неизвестная тема')
            fb.set_user_field(user['user_id'], 'theme', body.theme)
        return me_json(fb.get_user(user['user_id']))

    @app.post('/api/me/cycle/period-started')
    def period_started(user=Depends(profile_user)):
        fb.log_period_start(user['user_id'], fb.now().date())
        return {'cycle': cycle_json(fb.get_user(user['user_id']))}

    def cycle_json(user):
        info = fb.cycle_info(user)
        if not info:
            return None
        emoji, name, _, _, _, tip = fb.PHASES[info['phase']]
        return {'day': info['day'], 'length': info['length'], 'phase': info['phase'], 'phase_name': name,
                'tip': tip, 'next_start': info['next_start'].isoformat(), 'days_left': info['days_left']}

    # ---------- тренировка на сегодня ----------
    @app.get('/api/today')
    def today(day: int | None = None, place: str | None = None, user=Depends(profile_user)):
        place = place if place in fb.PLACES else user['place']
        day_index = (user['day_index'] if day is None else day) % user['days']
        mods = fb.today_mods(user)
        plan = fb.plan_day(user, day_index, mods, place)
        week = fb.finished_workouts(user['user_id'], since=fb.now() - timedelta(days=7))
        due = [assignment_json(a) for a in fb.client_assignments(user['user_id'], until=fb.today_iso())] \
            if user.get('trainer_id') else []
        info = fb.cycle_info(user)
        return {
            'day_index': day_index, 'days': user['days'], 'place': place, 'default_place': user['place'],
            'plan': day_json(user, plan, mods['no_progress']),
            'notes': mods['notes'], 'light_day': bool(info and fb.PHASES[info['phase']][2]),
            'cycle': cycle_json(user),
            'program_days': [d.title for d in fb.user_program(user, place)],
            'week': {'done': len(week), 'plan': user['days'], 'strip': week_strip(user['user_id'])},
            'streak': streak_days(user['user_id']), 'assignments': due, 'hero_url': hero_url(user),
        }

    @app.get('/api/program')
    def program(place: str | None = None, user=Depends(profile_user)):
        place = place if place in fb.PLACES else user['place']
        base = fb.base_program(user, place)
        days = []
        for i, d in enumerate(fb.user_program(user, place)):
            days.append({'index': i, 'title': d.title, 'groups': d.groups, 'exercises': [
                {**ex_json(p.exercise, user), 'role': p.role, 'plan_text': p.presc.text(),
                 'swapped': p.exercise.id != base[i].exercises[pos].exercise.id}
                for pos, p in enumerate(d.exercises)]})
        return {'place': place, 'next_day': user['day_index'] % user['days'], 'days': days}

    # ---------- проведение тренировки ----------
    def own_workout(uid, wid, open_only=True):
        with fb.connect() as c:
            row = c.execute('SELECT * FROM workouts WHERE id=? AND user_id=?', (wid, uid)).fetchone()
        if not row or (open_only and row['finished_at']):
            raise HTTPException(404, 'Тренировка не найдена')
        return dict(row)

    @app.post('/api/workouts')
    def start(body: StartIn, user=Depends(profile_user)):
        uid = user['user_id']
        place = body.place if body.place in fb.PLACES else user['place']
        if body.assignment_id:
            a = fb.get_assignment(body.assignment_id)
            if not a or a['client_id'] != uid or a['status'] != 'pending':
                raise HTTPException(404, 'Назначенная тренировка не найдена')
            plan = fb.day_from_items(a['items'], a['title'], a['note'] or '')
            wid = fb.start_workout(uid, -1, f'🎯 {a["title"]}')
            return {'id': wid, 'assignment_id': a['id'], 'place': place, 'plan': day_json(user, plan),
                    'notes': [f'💬 Комментарий тренера: {a["note"]}'] if a['note'] else []}
        day_index = (user['day_index'] if body.day is None else body.day) % user['days']
        mods = fb.today_mods(user, standard=body.standard)
        plan = fb.plan_day(user, day_index, mods, place)
        title = plan.title + ('' if place == user['place'] else (' (дома)' if place == fb.HOME else ' (в зале)'))
        wid = fb.start_workout(uid, day_index, title)
        return {'id': wid, 'assignment_id': None, 'day_index': day_index, 'place': place,
                'plan': day_json(user, plan, mods['no_progress']), 'notes': mods['notes']}

    @app.post('/api/workouts/{wid}/sets')
    def add_set(wid: int, body: SetIn, user=Depends(profile_user)):
        own_workout(user['user_id'], wid)
        if body.exercise_id not in fb.EXERCISES:
            raise HTTPException(422, 'Неизвестное упражнение')
        fb.add_set(wid, user['user_id'], body.exercise_id, body.set_no, body.weight, body.reps)
        return {'ok': True}

    @app.delete('/api/workouts/{wid}/sets/last')
    def undo_set(wid: int, user=Depends(profile_user)):
        own_workout(user['user_id'], wid)
        with fb.connect() as c:
            c.execute('DELETE FROM sets WHERE id=(SELECT MAX(id) FROM sets WHERE workout_id=?)', (wid,))
        return {'ok': True}

    @app.post('/api/workouts/{wid}/cardio')
    def add_cardio(wid: int, body: CardioIn, user=Depends(profile_user)):
        own_workout(user['user_id'], wid)
        if body.phase not in ('warmup', 'cooldown') or body.kind not in fb.CARDIO:
            raise HTTPException(422, 'Неверное кардио')
        fb.add_cardio(wid, user['user_id'], body.phase, body.kind, body.minutes)
        return {'ok': True}

    @app.post('/api/workouts/{wid}/finish')
    async def finish(wid: int, body: FinishIn, request: Request, user=Depends(profile_user)):
        uid = user['user_id']
        w = own_workout(uid, wid)
        sets = fb.workout_sets(wid)
        cardio = fb.workout_cardio(wid)
        if not sets and not cardio:
            fb.delete_workout(wid)
            return {'cancelled': True}
        records = []
        for ex_id in dict.fromkeys(s['exercise_id'] for s in sets):
            before = fb.best_e1rm(uid, ex_id, wid)
            best = max(fb.e1rm(s['weight'], s['reps']) for s in sets if s['exercise_id'] == ex_id)
            if before and best > before:
                records.append(fb.EXERCISES[ex_id].name if ex_id in fb.EXERCISES else ex_id)
        fb.finish_workout_db(wid)
        if w['day_index'] is not None and w['day_index'] >= 0:
            fb.set_user_field(uid, 'day_index', (w['day_index'] + 1) % user['days'])
        started = datetime.fromisoformat(w['started_at'])
        minutes = max(1, int((fb.now() - started).total_seconds() // 60))
        tonnage = sum(s['weight'] * s['reps'] for s in sets
                      if s['exercise_id'] in fb.EXERCISES and fb.EXERCISES[s['exercise_id']].unit == 'reps')
        if body.assignment_id:
            a = fb.get_assignment(body.assignment_id)
            if a and a['client_id'] == uid and a['status'] == 'pending':
                fb.set_assignment_status(a['id'], 'done', wid)
                bot = request.app.state.bot
                if bot:
                    await fb.notify(bot, a['trainer_id'],
                                    f'✅ <b>{fb.html.escape(fb.display_name(user))}</b> выполнил(а) тренировку '
                                    f'«{fb.html.escape(a["title"])}» в приложении за {minutes} мин, подходов: {len(sets)}.')
        await fb.social_after_workout(request.app.state.bot, uid)
        week = fb.finished_workouts(uid, since=fb.now() - timedelta(days=7))
        return {'cancelled': False, 'workout_id': wid, 'minutes': minutes, 'sets': len(sets),
                'exercises': len({s['exercise_id'] for s in sets}), 'tonnage': round(tonnage),
                'records': records, 'cardio': [fb.cardio_line(r) for r in cardio],
                'week': {'done': len(week), 'plan': user['days']}}

    @app.delete('/api/workouts/{wid}')
    def cancel(wid: int, user=Depends(profile_user)):
        own_workout(user['user_id'], wid)
        fb.delete_workout(wid)
        return {'ok': True}

    # ---------- кардио ----------
    @app.get('/api/cardio')
    def cardio(phase: str = 'warmup', place: str | None = None, groups: str = '', user=Depends(profile_user)):
        phase = phase if phase in ('warmup', 'cooldown') else 'warmup'
        place = place if place in fb.PLACES else user['place']
        ag = fb.age_group(user.get('age'))
        kinds = fb.cardio_options(place, ag)
        if phase == 'cooldown':
            kinds = [k for k in kinds if not fb.CARDIO[k][2]] or kinds
        lo, hi, default = fb.cardio_minutes(phase, user['goal'], ag)
        p_lo, p_hi = fb.pulse_range(phase, user['goal'], user.get('age'))
        wanted = [g for g in groups.split(',') if g in fb.STRETCHES]
        return {'phase': phase, 'minutes': {'lo': lo, 'hi': hi, 'default': default}, 'pulse': {'lo': p_lo, 'hi': p_hi},
                'options': [{'id': k, 'name': fb.CARDIO[k][0], 'how': fb.CARDIO[k][3]} for k in kinds],
                'joint_warmup': fb.JOINT_WARMUP if phase == 'warmup' else [],
                'stretches': [fb.STRETCHES[g] for g in dict.fromkeys(wanted)] if phase == 'cooldown' else []}

    # ---------- упражнения ----------
    @app.get('/api/exercises/{ex_id}')
    def exercise(ex_id: str, user=Depends(profile_user)):
        ex = fb.EXERCISES.get(ex_id)
        if not ex:
            raise HTTPException(404, 'Упражнение не найдено')
        secondary, setup, steps, breath, mistakes = fb.TECHNIQUE[ex.id]
        g = 'f' if user.get('gender') == 'f' else ''
        stored = fb.db_photos(ex.id)
        frames = []
        for i, (caption, _) in enumerate(fb.EXERCISE_FRAMES.get(ex.id, (None, []))[1], 1):
            has = any(fb.photo_source(ex.id, i, x, stored) for x in (g, 'f' if g == '' else ''))
            frames.append({'n': i, 'caption': caption,
                           'url': f'/api/exercises/{ex.id}/photos/{i}?g={"f" if g else "m"}' if has else None})
        return {**ex_json(ex, user), 'technique': {'secondary': secondary, 'setup': setup, 'steps': steps,
                                                   'breath': breath, 'mistakes': mistakes}, 'photos': frames}

    @app.get('/api/exercises/{ex_id}/photos/{frame}')
    async def photo(ex_id: str, frame: int, request: Request, g: str = 'm'):
        if ex_id not in fb.EXERCISES:
            raise HTTPException(404)
        mine = 'f' if g == 'f' else ''
        stored = fb.db_photos(ex_id)
        src = fb.photo_source(ex_id, frame, mine, stored) or fb.photo_source(ex_id, frame, 'f' if mine == '' else '', stored)
        if not src:
            raise HTTPException(404)
        if isinstance(src, Path):
            return FileResponse(src, headers={'Cache-Control': 'public, max-age=86400'})
        if src not in _photo_cache:
            bot = request.app.state.bot
            if not bot:
                raise HTTPException(404)
            tg_file = await bot.get_file(src)
            _photo_cache[src] = bytes(await tg_file.download_as_bytearray())
            if len(_photo_cache) > 300:
                _photo_cache.pop(next(iter(_photo_cache)))
        return Response(_photo_cache[src], media_type='image/jpeg', headers={'Cache-Control': 'public, max-age=86400'})

    @app.get('/api/alternatives')
    def alternatives(day: int, pos: int, place: str | None = None, user=Depends(profile_user)):
        place = place if place in fb.PLACES else user['place']
        plan = fb.plan_day(user, day % user['days'], place=place)
        if not 0 <= pos < len(plan.exercises):
            raise HTTPException(404)
        role = plan.exercises[pos].role
        out = []
        for ex in fb.alternatives(plan, pos, place):
            presc = fb.prescription(ex, role, user['goal'], user['level'], user.get('age') or '30')
            out.append(planned_json(user, fb.PlannedExercise(ex, role, presc)))
        return {'current': plan.exercises[pos].exercise.id, 'alternatives': out}

    @app.post('/api/swaps')
    def swap(body: SwapIn, user=Depends(profile_user)):
        if body.place not in fb.PLACES or body.exercise_id not in fb.EXERCISES:
            raise HTTPException(422)
        base = fb.base_program(user, body.place)[body.day % user['days']]
        if not 0 <= body.pos < len(base.exercises) or body.place not in fb.EXERCISES[body.exercise_id].places:
            raise HTTPException(422)
        fb.set_swap(user['user_id'], body.place, base.exercises[body.pos].exercise.id, body.exercise_id)
        return {'ok': True}

    @app.delete('/api/swaps')
    def reset_swaps(user=Depends(profile_user)):
        fb.clear_swaps(user['user_id'])
        return {'ok': True}

    # ---------- прогресс ----------
    @app.get('/api/progress')
    def progress(user=Depends(profile_user)):
        uid = user['user_id']
        t = fb.now()
        total = fb.finished_workouts(uid)
        month = fb.finished_workouts(uid, since=t - timedelta(days=30))
        week = fb.finished_workouts(uid, since=t - timedelta(days=7))
        month_sets = [s for w in month for s in fb.workout_sets(w['id'])]
        tonnage = sum(s['weight'] * s['reps'] for s in month_sets
                      if s['exercise_id'] in fb.EXERCISES and fb.EXERCISES[s['exercise_id']].unit == 'reps')
        prs = sorted(fb.personal_records(uid).items(), key=lambda kv: -kv[1][0])
        groups = [w for w in month if w.get('kind') == 'group']
        return {
            'total': len(total), 'month': len(month), 'week': len(week), 'plan': user['days'],
            'streak': streak_days(uid), 'tonnage_month': round(tonnage),
            'cardio_week': fb.cardio_minutes_since(uid, t - timedelta(days=7)),
            'groups_month': {'count': len(groups), 'minutes': sum(w.get('group_minutes') or 0 for w in groups)},
            'records': [{'id': ex_id, 'name': fb.EXERCISES[ex_id].name, 'weight': w, 'reps': r, 'date': d,
                         'text': fb.fmt_set(w, r, fb.EXERCISES[ex_id].unit),
                         'e1rm': round(score, 1) if w and r > 1 else None}
                        for ex_id, (score, w, r, d) in prs if ex_id in fb.EXERCISES][:12],
            'body_weight': [{'date': b['created_at'][:10], 'weight': b['weight']} for b in fb.body_weights(uid)],
            'target_weight': user.get('target_weight'),
            'week_strip': week_strip(uid),
            'measurements': fb.measurements_summary(uid),
            'measure_labels': fb.MEASURES,
        }

    @app.post('/api/measurements')
    def add_measurements(body: MeasurementsIn, user=Depends(profile_user)):
        values = {k: v for k, v in body.model_dump().items() if v}
        if any(not 20 <= v <= 250 for v in values.values()):
            raise HTTPException(422, 'Объёмы — от 20 до 250 см')
        if not fb.add_measurements(user['user_id'], values):
            raise HTTPException(422, 'Укажи хотя бы один объём')
        return {'measurements': fb.measurements_summary(user['user_id'])}

    @app.get('/api/hero/{gender}.jpg')
    def hero_photo(gender: str):
        photo = fb.get_app_photo('home', gender)
        if not photo:
            raise HTTPException(404)
        return Response(photo['data'], media_type=photo['mime'], headers={'Cache-Control': 'public, max-age=86400'})

    def hero_url(user):
        g = 'f' if user.get('gender') == 'f' else 'm'
        v = fb.app_photo_version('home', g)
        return f'/api/hero/{g}.jpg?v={v.replace(":", "")}' if v else None

    @app.post('/api/body-weight')
    def body_weight(body: WeightIn, user=Depends(profile_user)):
        fb.add_body_weight(user['user_id'], body.weight)
        return {'ok': True}

    @app.get('/api/history')
    def history(limit: int = 20, user=Depends(profile_user)):
        out = []
        for w in fb.finished_workouts(user['user_id'], limit=min(max(limit, 1), 100)):
            by_ex = {}
            for s in fb.workout_sets(w['id']):
                by_ex.setdefault(s['exercise_id'], []).append(s)
            out.append({
                'id': w['id'], 'title': w['title'], 'date': w['finished_at'][:10], 'kind': w.get('kind') or 'strength',
                'minutes': w.get('group_minutes') or max(1, int((datetime.fromisoformat(w['finished_at']) -
                                                                  datetime.fromisoformat(w['started_at'])).total_seconds() // 60)),
                'exercises': [{'name': fb.EXERCISES[e].name if e in fb.EXERCISES else e,
                               'sets': [fb.fmt_set(s['weight'], s['reps'], fb.EXERCISES[e].unit if e in fb.EXERCISES else 'reps')
                                        for s in ss]} for e, ss in by_ex.items()],
                'cardio': [fb.cardio_line(r) for r in fb.workout_cardio(w['id'])],
            })
        return {'workouts': out}

    # ---------- групповые ----------
    @app.post('/api/groups/log')
    async def group_log(body: GroupLogIn, request: Request, user=Depends(profile_user)):
        if body.type not in fb.GROUP_TYPES:
            raise HTTPException(422)
        fb.log_past_group(user['user_id'], body.type, body.minutes)
        await fb.social_after_workout(request.app.state.bot, user['user_id'])
        return {'ok': True}

    # ---------- друзья ----------
    def friends_json(user):
        uid = user['user_id']
        code = fb.user_invite_code(uid)
        st = fb.friend_stats(uid)
        pair = fb.active_pair(uid)
        ps = fb.pair_status(pair, uid) if pair else None
        last = fb.card_data(uid)['workout']
        return {
            'invite_url': fb.invite_url(bot_username(), code), 'pair_url': fb.invite_url(bot_username(), code, 'pair'),
            'friend_days': fb.friend_bonus_days(), 'inviter_days': fb.inviter_bonus_days(),
            'stats': {'invited': st['invited'], 'paid': st['paid'], 'days': st['days']},
            'friends': [{'name': f['name'] or 'Друг', 'date': (f['created_at'] or '')[:10],
                         'status': next((r['status'] for r in st['rewards'] if r['friend_id'] == f['user_id']), 'joined')}
                        for f in st['friends']],
            'pair': {'partner': ps['partner'], 'goal': ps['goal'], 'me': ps['me'], 'partner_done': ps['partner_done'],
                     'streak': ps['streak'], 'closed': ps['closed']} if ps else None,
            'goals': list(fb.PAIR_GOALS),
            'card_url': f'/api/card/{code}.png?v={last["id"] if last else 0}',
            'has_workout': bool(last),
        }

    @app.get('/api/friends')
    def friends(user=Depends(current_user)):
        return friends_json(user)

    @app.post('/api/friends/pair/goal')
    async def pair_goal(body: GoalIn, request: Request, user=Depends(current_user)):
        if body.goal not in fb.PAIR_GOALS:
            raise HTTPException(422, 'Цель — от 2 до 5 тренировок')
        pair = fb.set_pair_goal(user['user_id'], body.goal)
        if not pair:
            raise HTTPException(404, 'Напарника пока нет')
        bot = request.app.state.bot
        if bot:
            s = fb.pair_status(pair, user['user_id'])
            await fb.notify(bot, s['partner_id'], f'🎯 {fb.html.escape(fb.display_name(user))} изменил(а) цель недели: '
                                                  f'{fb.trainings(s["goal"])} каждому.')
        return friends_json(user)

    @app.delete('/api/friends/pair')
    async def pair_leave(request: Request, user=Depends(current_user)):
        pair = fb.end_pair(user['user_id'])
        bot = request.app.state.bot
        if pair and bot:
            partner = pair['b_id'] if pair['a_id'] == user['user_id'] else pair['a_id']
            await fb.notify(bot, partner, f'👋 {fb.html.escape(fb.display_name(user))} вышел(ла) из пары.')
        return friends_json(user)

    @app.get('/api/card/{code}.png')
    def result_card(code: str, gift: int = 1):
        # Код приглашения и так публичный (он в ссылке на карточке), поэтому картинку можно отдавать без входа.
        owner = fb.user_by_invite_code(code)
        if not owner:
            raise HTTPException(404)
        png = fb.render_card(fb.card_data(owner['user_id']), fb.invite_url(bot_username(), code), gift=bool(gift))
        return Response(png, media_type='image/png', headers={'Cache-Control': 'private, max-age=60'})

    # ---------- тренер ----------
    @app.get('/api/coach')
    def coach(user=Depends(profile_user)):
        if not user.get('trainer_id'):
            reqs = fb.pending_requests(client_id=user['user_id'])
            return {'trainer': None, 'assignments': [], 'done': [], 'messages': [],
                    'pending': [{'id': r['id'], 'trainer_id': r['trainer_id'],
                                 'trainer_name': fb.display_name(fb.get_user(r['trainer_id']), 'Тренер')} for r in reqs]}
        uid, tid = user['user_id'], user['trainer_id']
        trainer = fb.get_user(tid)
        done = [assignment_json(a) for a in fb.client_assignments(uid, status='done')][-10:]
        my_review = next((r for r in fb.trainer_reviews(tid, 1000) if r['client_id'] == uid), None)
        return {'trainer': {'id': tid, 'name': fb.display_name(trainer, 'Тренер'), 'rating': fb.trainer_rating(tid)[0],
                            'photo_url': trainer_card(trainer)['photo_url']},
                'can_review': fb.can_review(uid, tid),
                'my_review': {'rating': my_review['rating'], 'text': my_review['text'] or ''} if my_review else None,
                'pending': [],
                'assignments': [assignment_json(a) for a in fb.client_assignments(uid)],
                'done': list(reversed(done)),
                'messages': [{'mine': m['from_id'] == uid, 'text': m['text'], 'at': m['created_at']}
                             for m in fb.recent_messages(tid, uid, 30)],
                'unread': fb.unread_count(uid, tid)}

    # ---------- чат тренер ↔ подопечный ----------
    def chat_peer(user, peer_id):
        """Собеседник: мой тренер или мой подопечный. Возвращает (peer, роль собеседника)."""
        peer = fb.get_user(peer_id)
        if peer and user.get('trainer_id') == peer_id:
            return peer, 'trainer'
        if peer and fb.is_trainer(user) and peer.get('trainer_id') == user['user_id']:
            return peer, 'client'
        raise HTTPException(404, 'Чат недоступен')

    def message_json(m, uid):
        return {'id': m['id'], 'mine': m['from_id'] == uid, 'text': m['text'], 'at': m['created_at'],
                'read': bool(m.get('read_at'))}

    @app.get('/api/chat/{peer_id}')
    def chat(peer_id: int, after: int = 0, user=Depends(current_user)):
        uid = user['user_id']
        peer, role = chat_peer(user, peer_id)
        fb.mark_read(uid, peer_id)
        photo = trainer_card(peer)['photo_url'] if role == 'trainer' else None
        return {'peer': {'id': peer_id, 'name': fb.display_name(peer, 'Тренер' if role == 'trainer' else 'Подопечный'),
                         'role': role, 'photo_url': photo},
                'messages': [message_json(m, uid) for m in fb.chat_messages(uid, peer_id, after)]}

    @app.post('/api/chat/{peer_id}')
    async def chat_send(peer_id: int, body: MessageIn, request: Request, user=Depends(current_user)):
        uid = user['user_id']
        peer, role = chat_peer(user, peer_id)
        text = body.text.strip()
        if not text:
            raise HTTPException(422, 'Пустое сообщение')
        mid = fb.save_message(uid, peer_id, text)
        bot = request.app.state.bot
        if bot:
            if role == 'trainer':
                await fb.notify(bot, peer_id, f'💬 <b>Сообщение от подопечного {fb.html.escape(fb.display_name(user))}</b>\n\n'
                                              f'{fb.html.escape(text)}',
                                fb.kb([[('↩️ Ответить', f'tr:msg:{uid}'), ('👤 Профиль', f'tr:c:{uid}')]]))
            else:
                await fb.notify(bot, peer_id, f'💬 <b>Сообщение от тренера {fb.html.escape(fb.display_name(user, ""))}</b>\n\n'
                                              f'{fb.html.escape(text)}', fb.kb([[('↩️ Ответить', 'cl:msg')]]))
        return {'message': message_json(fb.chat_messages(uid, peer_id, mid - 1, 1)[0], uid)}

    @app.post('/api/coach/messages')
    async def coach_message(body: MessageIn, request: Request, user=Depends(profile_user)):
        if not user.get('trainer_id'):
            raise HTTPException(404, 'Тренер не подключён')
        fb.save_message(user['user_id'], user['trainer_id'], body.text.strip())
        bot = request.app.state.bot
        if bot:
            await fb.notify(bot, user['trainer_id'],
                            f'💬 <b>Сообщение от подопечного {fb.html.escape(fb.display_name(user))}</b> (из приложения)\n\n'
                            f'{fb.html.escape(body.text.strip())}',
                            fb.kb([[('↩️ Ответить', f'tr:msg:{user["user_id"]}'), ('👤 Профиль', f'tr:c:{user["user_id"]}')]]))
        return {'ok': True}

    # ---------- каталог тренеров ----------
    def trainer_card(t):
        tid = t['user_id']
        prof = fb.get_trainer_profile(tid)
        rating, count = fb.trainer_rating(tid)
        return {
            'id': tid, 'name': fb.display_name(t, 'Тренер'), 'rating': rating, 'reviews': count,
            'clients': len(fb.trainer_clients(tid)), 'has_room': fb.trainer_has_room(tid),
            'specializations': [{'key': k, 'label': fb.SPECIALIZATIONS[k]} for k in prof['specializations']],
            'experience_years': prof.get('experience_years'), 'city': prof.get('city') or '',
            'format': prof.get('format') or 'both', 'format_label': fb.TRAINER_FORMATS.get(prof.get('format') or 'both', ''),
            'bio': prof.get('bio') or '', 'certificates': prof.get('certificates') or '',
            'photo_url': f'/api/trainers/{tid}/photo?v={prof["photo_version"]}' if prof['photo_version'] else None,
        }

    def listed_trainers():
        with fb.connect() as c:
            rows = c.execute('''SELECT u.* FROM users u JOIN trainer_profiles p ON p.user_id=u.user_id
                                WHERE u.is_trainer=1 AND p.listed=1 AND COALESCE(p.bio, '')<>'' ''').fetchall()
        return [dict(r) for r in rows]

    @app.get('/api/trainers')
    def trainers(spec: str = '', format: str = '', city: str = '', user=Depends(current_user)):
        cards = [trainer_card(t) for t in listed_trainers() if t['user_id'] != user['user_id']]
        if spec:
            cards = [c for c in cards if any(x['key'] == spec for x in c['specializations'])]
        if format in ('online', 'offline'):
            cards = [c for c in cards if c['format'] in (format, 'both')]
        if city.strip():
            cards = [c for c in cards if city.strip().lower() in c['city'].lower() or c['format'] != 'offline']

        def score(c):  # байесовское среднее: мало отзывов — ближе к 4.0
            return ((c['rating'] or 0) * c['reviews'] + 4.0 * 3) / (c['reviews'] + 3)
        cards.sort(key=lambda c: (c['has_room'], score(c), c['reviews']), reverse=True)
        return {'trainers': cards, 'specializations': fb.SPECIALIZATIONS, 'formats': fb.TRAINER_FORMATS,
                'my_requests': [r['trainer_id'] for r in fb.pending_requests(client_id=user['user_id'])]}

    @app.get('/api/trainers/{tid}')
    def trainer_detail(tid: int, user=Depends(current_user)):
        t = fb.get_user(tid)
        if not fb.is_trainer(t):
            raise HTTPException(404, 'Тренер не найден')
        uid = user['user_id']
        mine = next((r for r in fb.pending_requests(client_id=uid) if r['trainer_id'] == tid), None)
        my_review = next((r for r in fb.trainer_reviews(tid, 1000) if r['client_id'] == uid), None)
        return {**trainer_card(t),
                'reviews_list': [{'name': (r['name'] or 'Пользователь').split(' ')[0], 'rating': r['rating'], 'text': r['text'] or '',
                                  'date': r['updated_at'][:10]} for r in fb.trainer_reviews(tid)],
                'is_my_trainer': user.get('trainer_id') == tid, 'has_trainer': bool(user.get('trainer_id')),
                'my_request': {'id': mine['id'], 'status': mine['status']} if mine else None,
                'can_review': fb.can_review(uid, tid),
                'my_review': {'rating': my_review['rating'], 'text': my_review['text'] or ''} if my_review else None}

    @app.get('/api/trainers/{tid}/photo')
    def trainer_photo(tid: int):
        data, mime = fb.get_trainer_photo(tid)
        if not data:
            raise HTTPException(404)
        return Response(data, media_type=mime or 'image/jpeg', headers={'Cache-Control': 'public, max-age=604800'})

    @app.post('/api/trainers/{tid}/requests')
    async def request_trainer(tid: int, body: RequestIn, user=Depends(profile_user)):
        t = fb.get_user(tid)
        if not fb.is_trainer(t) or tid == user['user_id']:
            raise HTTPException(404, 'Тренер не найден')
        if user.get('trainer_id'):
            raise HTTPException(409, 'У тебя уже есть тренер. Сначала отключись от него в разделе «Тренер».')
        if not fb.trainer_has_room(tid):
            raise HTTPException(409, 'У тренера сейчас нет свободных мест')
        rid = fb.create_coach_request(user['user_id'], tid, body.message.strip())
        if bot:
            await fb.notify(bot, tid, fb.request_text(fb.get_coach_request(rid)),
                            fb.kb([[('✅ Принять', f'tr:rq:a:{rid}'), ('❌ Отклонить', f'tr:rq:r:{rid}')]]))
        return {'id': rid, 'status': 'pending'}

    @app.delete('/api/requests/{rid}')
    def cancel_request(rid: int, user=Depends(current_user)):
        r = fb.get_coach_request(rid)
        if not r or r['client_id'] != user['user_id'] or r['status'] != 'pending':
            raise HTTPException(404, 'Заявка не найдена')
        fb.set_request_status(rid, 'cancelled')
        return {'ok': True}

    @app.post('/api/trainers/{tid}/review')
    def review_trainer(tid: int, body: ReviewIn, user=Depends(profile_user)):
        if not fb.is_trainer(fb.get_user(tid)):
            raise HTTPException(404, 'Тренер не найден')
        if not fb.can_review(user['user_id'], tid):
            raise HTTPException(403, f'Оценить тренера можно после {fb.REVIEW_MIN_WORKOUTS} тренировок от него '
                                     f'или {fb.REVIEW_MIN_DAYS} дней занятий вместе')
        fb.save_review(tid, user['user_id'], body.rating, body.text.strip())
        rating, count = fb.trainer_rating(tid)
        return {'rating': rating, 'reviews': count}

    @app.post('/api/coach/leave')
    async def leave_coach(user=Depends(current_user)):
        tid = user.get('trainer_id')
        if not tid:
            return {'ok': True}
        fb.end_coaching(user['user_id'])
        for a in fb.client_assignments(user['user_id']):
            fb.set_assignment_status(a['id'], 'cancelled')
        if bot:
            await fb.notify(bot, tid, f'👋 {fb.html.escape(fb.display_name(user))} отключился от тренировок с тобой.')
        return {'ok': True}

    # ---------- кабинет тренера ----------
    def trainer_user(user=Depends(current_user)):
        if not fb.is_trainer(user):
            raise HTTPException(403, 'Кабинет доступен только тренерам')
        return user

    def own_client(trainer, cid):
        client = fb.get_user(cid)
        if not client or client.get('trainer_id') != trainer['user_id']:
            raise HTTPException(404, 'Это не твой подопечный')
        return client

    def bot_username():
        return getattr(bot, 'username', None) or os.environ.get('FITNESS_BOT_USERNAME', 'FitHelperTop_bot')

    @app.get('/api/trainer')
    def trainer_home(trainer=Depends(trainer_user)):
        tid = trainer['user_id']
        invited, subs = fb.referral_stats(tid)
        idx, (name, _, percent, desc) = fb.trainer_level(subs)
        nxt = fb.TRAINER_LEVELS[idx + 1] if idx + 1 < len(fb.TRAINER_LEVELS) else None
        cur_from = fb.TRAINER_LEVELS[idx][1]
        clients = []
        for c in fb.trainer_clients(tid):
            week = len(fb.finished_workouts(c['user_id'], since=fb.now() - timedelta(days=7)))
            clients.append({'id': c['user_id'], 'name': fb.display_name(c), 'week': week, 'plan': c.get('days') or 0,
                            'goal': fb.GOALS.get(c.get('goal'), ''), 'subscription': fb.has_subscription(c),
                            'pending': len(fb.client_assignments(c['user_id'])),
                            'unread': fb.unread_count(tid, c['user_id'])})
        price = fb.sub_price()
        return {
            'level': {'name': name.split(' ', 1)[-1], 'percent': percent, 'description': desc},
            'next': {'name': nxt[0].split(' ', 1)[-1], 'percent': nxt[2], 'left': nxt[1] - subs,
                     'progress': (subs - cur_from) / (nxt[1] - cur_from)} if nxt else None,
            'subscribers': subs, 'invited': invited,
            'income': round(subs * price * percent / 100) if price else None,
            'balance': fb.trainer_balance(tid),
            'requisites_ok': fb.requisites_ok(fb.get_requisites(tid)),
            'levels': [{'name': lv[0].split(' ', 1)[-1], 'from': lv[1], 'percent': lv[2], 'description': lv[3]}
                       for lv in fb.TRAINER_LEVELS],
            'links': [{'code': l['code'], 'label': l['label'], 'joined': l['joined'], 'subs': l['subs'],
                       'url': f'https://t.me/{bot_username()}?start=ref_{l["code"]}'} for l in fb.trainer_links(tid)],
            'clients': clients,
            'rating': dict(zip(('value', 'count'), fb.trainer_rating(tid))),
            'profile_listed': bool(fb.get_trainer_profile(tid).get('bio')) and bool(fb.get_trainer_profile(tid).get('listed')),
            'requests': [{'id': r['id'], 'name': fb.display_name(fb.get_user(r['client_id'])), 'message': r['message'] or '',
                          'goal': fb.GOALS.get(fb.get_user(r['client_id']).get('goal'), ''), 'date': r['created_at'][:10]}
                         for r in fb.pending_requests(tid=tid)],
        }

    @app.get('/api/trainer/earnings')
    def trainer_earnings(trainer=Depends(trainer_user)):
        tid = trainer['user_id']
        req = fb.get_requisites(tid)
        return {
            'balance': fb.trainer_balance(tid),
            'rules': {'coach_share': fb.coach_share(), 'hold_days': fb.hold_days(), 'min_payout': fb.min_payout(),
                      'level_percent': fb.trainer_level(fb.referral_stats(tid)[1])[1][2]},
            'commissions': [{'id': r['id'], 'date': r['created_at'][:10], 'client': r['client_name'] or '',
                             'type': r['type'], 'percent': r['percent'], 'base': r['base_amount'], 'amount': r['amount'],
                             'status': r['status'], 'available_at': (r['available_at'] or '')[:10]}
                            for r in fb.trainer_commissions(tid, 50)],
            'payouts': [{'id': p['id'], 'amount': p['amount'], 'status': p['status'], 'created': p['created_at'][:10],
                         'paid': (p['paid_at'] or '')[:10]} for p in fb.trainer_payouts(tid)],
            'requisites': requisites_out(req),
            'legal_statuses': fb.LEGAL_STATUSES, 'methods': fb.PAYOUT_METHODS,
        }

    def requisites_out(req):
        if not req:
            return None
        return {'legal_status': req['legal_status'], 'full_name': req['full_name'], 'inn': req['inn'],
                'method': req['method'], 'details_masked': fb.mask(req['details']), 'ok': fb.requisites_ok(req)}

    @app.put('/api/trainer/requisites')
    def put_requisites(body: RequisitesIn, trainer=Depends(trainer_user)):
        inn = re.sub(r'\D', '', body.inn)
        if body.legal_status not in fb.LEGAL_STATUSES:
            raise HTTPException(422, 'Выплаты доступны только самозанятым и ИП')
        if len(body.full_name.split()) < 2:
            raise HTTPException(422, 'Укажи ФИО полностью')
        if not fb.valid_inn(inn, body.legal_status):
            raise HTTPException(422, 'ИНН не прошёл проверку — нужно 12 цифр')
        if body.method not in fb.PAYOUT_METHODS or len(body.details.strip()) < 5:
            raise HTTPException(422, 'Укажи способ и реквизиты для перевода')
        fb.save_requisites(trainer['user_id'], body.legal_status, body.full_name.strip(), inn, body.method,
                           body.details.strip())
        return requisites_out(fb.get_requisites(trainer['user_id']))

    @app.get('/api/trainer/profile')
    def trainer_profile(trainer=Depends(trainer_user)):
        prof = fb.get_trainer_profile(trainer['user_id'])
        return {**{k: prof.get(k) for k in fb.TRAINER_PROFILE_FIELDS}, 'listed': bool(prof.get('listed')),
                'photo_url': trainer_card(trainer)['photo_url'], 'specializations_all': fb.SPECIALIZATIONS,
                'formats': fb.TRAINER_FORMATS}

    @app.put('/api/trainer/profile')
    def put_trainer_profile(body: TrainerProfileIn, trainer=Depends(trainer_user)):
        if body.format not in fb.TRAINER_FORMATS:
            raise HTTPException(422, 'Неверный формат')
        fb.save_trainer_profile(trainer['user_id'], body.model_dump())
        return trainer_profile(trainer)

    @app.post('/api/trainer/photo')
    def put_trainer_photo(body: PhotoIn, trainer=Depends(trainer_user)):
        if body.mime not in ('image/jpeg', 'image/png', 'image/webp'):
            raise HTTPException(422, 'Нужна картинка JPG, PNG или WEBP')
        raw = body.data.split(',', 1)[-1]
        try:
            data = base64.b64decode(raw, validate=True)
        except ValueError:
            raise HTTPException(422, 'Не удалось прочитать картинку')
        if len(data) > 2_500_000:
            raise HTTPException(413, 'Фото больше 2,5 МБ')
        fb.save_trainer_photo(trainer['user_id'], data, body.mime)
        return {'photo_url': trainer_card(trainer)['photo_url']}

    @app.post('/api/trainer/requests/{rid}/{action}')
    async def decide_request(rid: int, action: str, trainer=Depends(trainer_user)):
        if action not in ('accept', 'reject'):
            raise HTTPException(404)
        return {'result': await fb.decide_coach_request(bot, trainer, rid, action == 'accept')}

    @app.post('/api/trainer/links')
    def trainer_new_link(body: LinkIn, trainer=Depends(trainer_user)):
        code = fb.create_ref_link(trainer['user_id'], body.label.strip())
        return {'code': code, 'url': f'https://t.me/{bot_username()}?start=ref_{code}'}

    @app.get('/api/trainer/catalog')
    def trainer_catalog(trainer=Depends(trainer_user)):
        return {'groups': fb.GROUPS, 'exercises': [
            {'id': e.id, 'name': e.name, 'group': e.group, 'places': list(e.places), 'unit': e.unit,
             'bodyweight': e.bodyweight, 'equipment': fb.EQUIPMENT[fb.equipment_of(e)][0]} for e in fb._EXERCISE_LIST]}

    @app.get('/api/trainer/clients/{cid}')
    def trainer_client(cid: int, trainer=Depends(trainer_user)):
        c = own_client(trainer, cid)
        t = fb.now()
        week = fb.finished_workouts(cid, since=t - timedelta(days=7))
        month = fb.finished_workouts(cid, since=t - timedelta(days=30))
        prs = sorted(fb.personal_records(cid).items(), key=lambda kv: -kv[1][0])[:6]
        complete = fb.profile_complete(c)
        return {
            'id': cid, 'name': fb.display_name(c), 'subscription_until': c.get('sub_until') if fb.has_subscription(c) else None,
            'profile': {k: c.get(k) for k in ('gender', 'age', 'goal', 'level', 'days', 'place')} if complete else None,
            'labels': {'gender': fb.GENDERS.get(c.get('gender'), ''), 'age': fb.AGES.get(c.get('age'), ''),
                       'goal': fb.GOALS.get(c.get('goal'), ''), 'level': fb.LEVELS.get(c.get('level'), ''),
                       'place': fb.PLACE_SHORT.get(c.get('place'), '')} if complete else None,
            'week': len(week), 'month': len(month), 'groups_month': sum(1 for w in month if w.get('kind') == 'group'),
            'cardio_week': fb.cardio_minutes_since(cid, t - timedelta(days=7)),
            'last': {'title': month[0]['title'], 'date': month[0]['finished_at'][:10]} if month else None,
            'records': [{'name': fb.EXERCISES[e].name, 'text': fb.fmt_set(w, r, fb.EXERCISES[e].unit), 'date': d}
                        for e, (_, w, r, d) in prs if e in fb.EXERCISES],
            'body_weight': [{'date': b['created_at'][:10], 'weight': b['weight']} for b in fb.body_weights(cid)][-30:],
            'measurements': fb.measurements_summary(cid), 'measure_labels': fb.MEASURES,
            'assignments': [assignment_json(a) for a in fb.client_assignments(cid)],
            'messages': [{'mine': m['from_id'] == trainer['user_id'], 'text': m['text'], 'at': m['created_at']}
                         for m in fb.recent_messages(trainer['user_id'], cid, 30)],
            'program_days': [d.title for d in fb.user_program(c)] if complete else [],
        }

    @app.get('/api/trainer/clients/{cid}/history')
    def trainer_client_history(cid: int, trainer=Depends(trainer_user)):
        own_client(trainer, cid)
        return history(limit=20, user=fb.get_user(cid))

    @app.get('/api/trainer/clients/{cid}/program-day/{day}')
    def trainer_program_day(cid: int, day: int, trainer=Depends(trainer_user)):
        c = own_client(trainer, cid)
        if not fb.profile_complete(c):
            raise HTTPException(409, 'Подопечный ещё не заполнил анкету')
        plan = fb.plan_day(c, day % c['days'])
        return {'title': plan.title, 'items': fb.items_from_day(plan)}

    @app.post('/api/trainer/clients/{cid}/messages')
    async def trainer_message(cid: int, body: MessageIn, trainer=Depends(trainer_user)):
        own_client(trainer, cid)
        text = body.text.strip()
        fb.save_message(trainer['user_id'], cid, text)
        if bot:
            await fb.notify(bot, cid, f'💬 <b>Сообщение от тренера {fb.html.escape(fb.display_name(trainer, ""))}</b>\n\n'
                                      f'{fb.html.escape(text)}', fb.kb([[('↩️ Ответить', 'cl:msg')]]))
        return {'ok': True}

    @app.post('/api/trainer/clients/{cid}/assignments')
    async def trainer_assign(cid: int, body: AssignmentIn, trainer=Depends(trainer_user)):
        own_client(trainer, cid)
        try:
            day_iso = datetime.fromisoformat(body.date).date().isoformat()
        except ValueError:
            raise HTTPException(422, 'Неверная дата')
        items = []
        for it in body.items:
            if it.ex not in fb.EXERCISES:
                raise HTTPException(422, f'Неизвестное упражнение {it.ex}')
            items.append({'ex': it.ex, 'sets': it.sets, 'lo': min(it.lo, it.hi), 'hi': max(it.lo, it.hi), 'w': it.w or None})
        aid = fb.save_assignment(trainer['user_id'], cid, day_iso, body.title.strip(), body.note.strip(), items)
        if bot:
            text = (f'🎯 Тренер <b>{fb.html.escape(fb.display_name(trainer, ""))}</b> назначил тренировку на '
                    f'<b>{fb.date_label(day_iso)}</b>: {fb.html.escape(body.title.strip())}\n\n'
                    + '\n'.join(fb.item_line(i, it) for i, it in enumerate(items, 1))
                    + (f'\n\n💬 {fb.html.escape(body.note.strip())}' if body.note.strip() else ''))
            await fb.notify(bot, cid, text, fb.kb([[('▶️ Начать', f'cl:go:{aid}')]]))
        return {'id': aid}

    @app.delete('/api/trainer/assignments/{aid}')
    async def trainer_cancel_assignment(aid: int, trainer=Depends(trainer_user)):
        a = fb.get_assignment(aid)
        if not a or a['trainer_id'] != trainer['user_id'] or a['status'] != 'pending':
            raise HTTPException(404, 'Назначение не найдено')
        fb.set_assignment_status(aid, 'cancelled')
        if bot:
            await fb.notify(bot, a['client_id'], f'Тренер отменил тренировку «{fb.html.escape(a["title"])}» '
                                                 f'на {fb.date_label(a["date"])}.')
        return {'ok': True}

    @app.patch('/api/trainer/clients/{cid}/program')
    async def trainer_program(cid: int, body: ProgramPatch, trainer=Depends(trainer_user)):
        c = own_client(trainer, cid)
        if not fb.profile_complete(c):
            raise HTTPException(409, 'Подопечный ещё не заполнил анкету')
        changes = []
        for field, options, label in (('goal', fb.GOALS, 'цель'), ('level', fb.LEVELS, 'уровень'),
                                      ('days', {d: f'{d} трен./нед.' for d in fb.DAY_OPTIONS}, 'частота'),
                                      ('place', fb.PLACES, 'место')):
            value = getattr(body, field)
            if value is None or value == c.get(field):
                continue
            if value not in options:
                raise HTTPException(422, f'Неверное значение: {label}')
            fb.set_user_field(cid, field, value)
            changes.append(f'{label} — {options[value]}')
        if changes and bot:
            await fb.notify(bot, cid, '✏️ Тренер изменил твою программу: ' + '; '.join(fb.html.escape(x) for x in changes))
        return {'ok': True, 'changes': changes}

    # ---------- веб-версия приложения ----------
    @app.get('/api/health')
    def health():
        return {'ok': True, 'version': fb.BOT_VERSION}

    @app.get('/{path:path}', include_in_schema=False)
    def web(path: str):
        if path.startswith('api/'):
            raise HTTPException(404)
        root = WEB_DIR.resolve()
        target = (root / path).resolve()
        if path and target.is_file() and root in target.parents:
            return FileResponse(target)
        index = root / 'index.html'
        if index.is_file():
            return FileResponse(index, headers={'Cache-Control': 'no-cache'})
        return Response('FitHelper API работает. Веб-версия приложения ещё не собрана.', media_type='text/plain; charset=utf-8')

    return app


if __name__ == '__main__':  # pragma: no cover
    import uvicorn
    uvicorn.run(create_app(), host='0.0.0.0', port=int(os.environ.get('PORT', '8080')))
