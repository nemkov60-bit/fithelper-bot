import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('FITNESS_DB', os.path.join(tempfile.mkdtemp(), 'test.db'))

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import fitness_bot as fb  # noqa: E402

PROFILE = {'gender': 'm', 'age': '30', 'goal': 'mass', 'level': 'mid', 'days': 3, 'place': 'gym'}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(api.create_app())

    def login(self, uid):
        fb.ensure_user_row(uid, 'Тест')
        return {'Authorization': f'Bearer {api.create_session(uid)}'}

    def test_login_via_bot_code(self):
        r = self.client.post('/api/auth/start').json()
        self.assertIn('?start=login_', r['url'])
        self.assertEqual(self.client.post('/api/auth/poll', json={'code': r['code']}).json()['status'], 'pending')
        fb.ensure_user_row(4001, 'Иван')
        self.assertTrue(api.confirm_login_code(r['code'], 4001))
        ok = self.client.post('/api/auth/poll', json={'code': r['code']}).json()
        self.assertEqual(ok['status'], 'ok')
        self.assertFalse(ok['me']['profile_complete'])
        me = self.client.get('/api/me', headers={'Authorization': 'Bearer ' + ok['token']}).json()
        self.assertEqual(me['id'], 4001)
        # Код одноразовый.
        self.assertEqual(self.client.post('/api/auth/poll', json={'code': r['code']}).json()['status'], 'pending')
        self.assertEqual(self.client.get('/api/me').status_code, 401)

    def test_workout_flow(self):
        h = self.login(4002)
        self.assertEqual(self.client.get('/api/today', headers=h).status_code, 409)  # анкета не заполнена
        me = self.client.put('/api/me/profile', json=PROFILE, headers=h).json()
        self.assertTrue(me['profile_complete'])
        today = self.client.get('/api/today', headers=h).json()
        self.assertEqual(today['day_index'], 0)
        self.assertEqual(len(today['plan']['exercises']), 6)
        home = self.client.get('/api/today?place=home', headers=h).json()
        self.assertTrue(all('home' in e['places'] for e in home['plan']['exercises']))
        w = self.client.post('/api/workouts', json={'place': 'gym'}, headers=h).json()
        ex = w['plan']['exercises'][0]
        for n in (1, 2):
            self.assertEqual(self.client.post(f'/api/workouts/{w["id"]}/sets', headers=h,
                                              json={'exercise_id': ex['id'], 'set_no': n, 'weight': 60, 'reps': 8}).status_code, 200)
        self.client.post(f'/api/workouts/{w["id"]}/cardio', json={'phase': 'warmup', 'kind': 'bike', 'minutes': 8}, headers=h)
        fin = self.client.post(f'/api/workouts/{w["id"]}/finish', json={}, headers=h).json()
        self.assertEqual(fin['sets'], 2)
        self.assertEqual(fin['tonnage'], 960)
        self.assertEqual(self.client.get('/api/today', headers=h).json()['day_index'], 1)
        prog = self.client.get('/api/progress', headers=h).json()
        self.assertEqual(prog['total'], 1)
        self.assertEqual(prog['cardio_week'], 8)
        self.assertEqual(prog['records'][0]['weight'], 60)
        hist = self.client.get('/api/history', headers=h).json()['workouts']
        self.assertEqual(hist[0]['exercises'][0]['sets'], ['60 кг × 8', '60 кг × 8'])
        # Следующий раз — прошлые подходы и совет.
        nxt = self.client.post('/api/workouts', json={'day': 0}, headers=h).json()
        first = nxt['plan']['exercises'][0]
        self.assertEqual(first['prev'], [[60.0, 8], [60.0, 8]])
        self.assertEqual(first['weight'], 60.0)
        self.assertTrue(self.client.post(f'/api/workouts/{nxt["id"]}/finish', json={}, headers=h).json()['cancelled'])

    def test_exercise_cardio_swaps_weight(self):
        h = self.login(4003)
        self.client.put('/api/me/profile', json={**PROFILE, 'gender': 'f'}, headers=h)
        ex = self.client.get('/api/exercises/bench', headers=h).json()
        self.assertEqual(ex['equipment']['key'], 'barbell')
        self.assertTrue(ex['technique']['steps'])
        self.assertEqual(len(ex['photos']), 3)
        self.assertIsNone(ex['photos'][0]['url'])
        fb.save_photo('bench', 1, 'f', 'FILEID')
        try:
            self.assertIn('g=f', self.client.get('/api/exercises/bench', headers=h).json()['photos'][0]['url'])
        finally:
            fb.delete_photo('bench', 1, 'f')
        c = self.client.get('/api/cardio?phase=cooldown&place=gym&groups=chest,back', headers=h).json()
        self.assertEqual(len(c['stretches']), 2)
        self.assertNotIn('rope', [o['id'] for o in c['options']])
        alts = self.client.get('/api/alternatives?day=0&pos=0&place=gym', headers=h).json()
        new = alts['alternatives'][0]['id']
        self.client.post('/api/swaps', json={'day': 0, 'pos': 0, 'place': 'gym', 'exercise_id': new}, headers=h)
        prog = self.client.get('/api/program', headers=h).json()
        self.assertTrue(prog['days'][0]['exercises'][0]['swapped'])
        self.client.post('/api/body-weight', json={'weight': 64.5}, headers=h)
        self.assertEqual(self.client.get('/api/progress', headers=h).json()['body_weight'][-1]['weight'], 64.5)

    def test_coach(self):
        h = self.login(4004)
        self.client.put('/api/me/profile', json=PROFILE, headers=h)
        self.assertIsNone(self.client.get('/api/coach', headers=h).json()['trainer'])
        fb.ensure_user_row(4005, 'Тренер')
        fb.make_trainer(4005)
        fb.set_user_field(4004, 'trainer_id', 4005)
        aid = fb.save_assignment(4005, 4004, fb.today_iso(), 'Ноги', 'Аккуратно', [
            {'ex': 'squat', 'sets': 3, 'lo': 8, 'hi': 10, 'w': 50}])
        coach = self.client.get('/api/coach', headers=h).json()
        self.assertEqual(coach['trainer']['name'], 'Тренер')
        self.assertEqual(coach['assignments'][0]['items'][0]['weight'], 50)
        self.assertEqual(self.client.get('/api/today', headers=h).json()['assignments'][0]['id'], aid)
        w = self.client.post('/api/workouts', json={'assignment_id': aid}, headers=h).json()
        self.assertEqual(w['plan']['exercises'][0]['sets'], 3)
        self.client.post(f'/api/workouts/{w["id"]}/sets', json={'exercise_id': 'squat', 'set_no': 1, 'weight': 50, 'reps': 9}, headers=h)
        self.client.post(f'/api/workouts/{w["id"]}/finish', json={'assignment_id': aid}, headers=h)
        self.assertEqual(fb.get_assignment(aid)['status'], 'done')
        self.assertEqual(fb.get_user(4004)['day_index'], 0)  # назначенная не сдвигает программу
        self.client.post('/api/coach/messages', json={'text': 'Привет!'}, headers=h)
        self.assertTrue(self.client.get('/api/coach', headers=h).json()['messages'][-1]['mine'])

    def test_web_fallback(self):
        r = self.client.get('/progress')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get('/api/nope').status_code, 404)


if __name__ == '__main__':
    unittest.main()


class TrainerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(api.create_app())

    def test_trainer_cabinet(self):
        fb.ensure_user_row(5001, 'Тренер Иван')
        h = {'Authorization': f'Bearer {api.create_session(5001)}'}
        self.assertEqual(self.client.get('/api/trainer', headers=h).status_code, 403)
        fb.make_trainer(5001)
        home = self.client.get('/api/trainer', headers=h).json()
        self.assertEqual(home['level']['name'], 'PARTNER')
        self.assertEqual(home['level']['percent'], 20)
        self.assertEqual(home['next']['left'], 10)
        link = self.client.post('/api/trainer/links', json={'label': 'Instagram'}, headers=h).json()
        self.assertIn('?start=ref_', link['url'])
        # подопечный
        fb.ensure_user_row(5002, 'Аня')
        fb.save_user(5002, 'Аня', {'gender': 'f', 'age': '30', 'goal': 'fit', 'level': 'novice', 'days': 3, 'place': 'gym'})
        fb.set_user_field(5002, 'trainer_id', 5001)
        self.assertEqual(self.client.get('/api/trainer/clients/9999', headers=h).status_code, 404)
        card = self.client.get('/api/trainer/clients/5002', headers=h).json()
        self.assertEqual(card['labels']['place'], '🏢 в зале')
        self.assertEqual(len(card['program_days']), 3)
        day = self.client.get('/api/trainer/clients/5002/program-day/0', headers=h).json()
        self.assertTrue(day['items'])
        r = self.client.post('/api/trainer/clients/5002/assignments', headers=h, json={
            'date': fb.today_iso(), 'title': day['title'], 'note': 'Без отказа', 'items': day['items']})
        aid = r.json()['id']
        self.assertEqual(self.client.get('/api/trainer', headers=h).json()['clients'][0]['pending'], 1)
        self.client.post('/api/trainer/clients/5002/messages', json={'text': 'Привет!'}, headers=h)
        self.assertEqual(self.client.get('/api/trainer/clients/5002', headers=h).json()['messages'][-1]['text'], 'Привет!')
        p = self.client.patch('/api/trainer/clients/5002/program', json={'days': 4, 'place': 'home'}, headers=h).json()
        self.assertEqual(len(p['changes']), 2)
        self.assertEqual(fb.get_user(5002)['days'], 4)
        self.client.delete(f'/api/trainer/assignments/{aid}', headers=h)
        self.assertEqual(fb.get_assignment(aid)['status'], 'cancelled')
        cat = self.client.get('/api/trainer/catalog', headers=h).json()
        self.assertGreater(len(cat['exercises']), 80)


class MarketplaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(api.create_app())

    def h(self, uid, name):
        fb.ensure_user_row(uid, name)
        return {'Authorization': f'Bearer {api.create_session(uid)}'}

    def test_catalog_request_review(self):
        import base64
        th = self.h(6001, 'Мария Тренер')
        fb.make_trainer(6001)
        # Без заполненного профиля тренера нет в каталоге.
        ch = self.h(6002, 'Клиент Олег')
        self.client.put('/api/me/profile', json=PROFILE, headers=ch)
        self.assertEqual(self.client.get('/api/trainers', headers=ch).json()['trainers'], [])
        prof = {'bio': 'Тренер по силовым, 8 лет стажа', 'specializations': ['strength', 'mass', 'bad'],
                'experience_years': 8, 'certificates': 'FPA', 'city': 'Москва', 'format': 'both', 'max_clients': 1}
        r = self.client.put('/api/trainer/profile', json=prof, headers=th).json()
        self.assertEqual(r['specializations'], ['strength', 'mass'])
        png = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 50).decode()
        self.assertIn('/photo?v=', self.client.post('/api/trainer/photo', json={'data': png, 'mime': 'image/png'}, headers=th).json()['photo_url'])
        cat = self.client.get('/api/trainers?spec=strength', headers=ch).json()
        self.assertEqual(cat['trainers'][0]['name'], 'Мария Тренер')
        self.assertEqual(self.client.get('/api/trainers?spec=women', headers=ch).json()['trainers'], [])
        self.assertEqual(self.client.get('/api/trainers/6001/photo').status_code, 200)
        # Заявка и принятие.
        rid = self.client.post('/api/trainers/6001/requests', json={'message': 'Хочу силу'}, headers=ch).json()['id']
        self.assertEqual(self.client.get('/api/trainer', headers=th).json()['requests'][0]['message'], 'Хочу силу')
        self.assertEqual(self.client.get('/api/coach', headers=ch).json()['pending'][0]['trainer_id'], 6001)
        res = self.client.post(f'/api/trainer/requests/{rid}/accept', headers=th).json()['result']
        self.assertIn('подопечный', res)
        self.assertEqual(fb.get_user(6002)['trainer_id'], 6001)
        # Лимит мест — 1: следующий клиент не может подать заявку.
        ch2 = self.h(6003, 'Клиент Ира')
        self.client.put('/api/me/profile', json=PROFILE, headers=ch2)
        self.assertEqual(self.client.post('/api/trainers/6001/requests', json={}, headers=ch2).status_code, 409)
        # Отзыв — только после 2 недель или 3 тренировок.
        self.assertEqual(self.client.post('/api/trainers/6001/review', json={'rating': 5}, headers=ch).status_code, 403)
        with fb.connect() as c:
            c.execute("UPDATE coaching SET started_at='2026-01-01T00:00:00' WHERE client_id=6002")
        self.assertTrue(self.client.get('/api/coach', headers=ch).json()['can_review'])
        r = self.client.post('/api/trainers/6001/review', json={'rating': 4, 'text': 'Отличный тренер'}, headers=ch).json()
        self.assertEqual((r['rating'], r['reviews']), (4.0, 1))
        detail = self.client.get('/api/trainers/6001', headers=ch2).json()
        self.assertEqual(detail['reviews_list'][0]['text'], 'Отличный тренер')
        self.assertFalse(detail['has_room'])
        # Отключение освобождает место.
        self.client.post('/api/coach/leave', headers=ch)
        self.assertIsNone(fb.get_user(6002)['trainer_id'])
        self.assertTrue(self.client.get('/api/trainers/6001', headers=ch2).json()['has_room'])
