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
