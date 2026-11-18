import os
import sys
import tempfile
import unittest
from datetime import timedelta
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


class PayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(api.create_app())

    def h(self, uid, name):
        fb.ensure_user_row(uid, name)
        return {'Authorization': f'Bearer {api.create_session(uid)}'}

    def shift(self, days):
        with fb.connect() as c:
            c.execute('UPDATE commissions SET available_at=? WHERE status=\'pending\'',
                      ((fb.now() - timedelta(days=days)).isoformat(timespec='seconds'),))

    def test_inn_checksum(self):
        self.assertTrue(fb.valid_inn('500100732259', 'npd'))
        self.assertFalse(fb.valid_inn('500100732258', 'npd'))
        self.assertFalse(fb.valid_inn('7707083893', 'ip'))  # 10 цифр — юрлицо

    def test_referral_coaching_hold_refund_registry(self):
        th = self.h(7001, 'Тренер Иван')
        fb.make_trainer(7001)
        fb.ensure_user_row(7002, 'Реферал')

        with fb.connect() as c:
            c.execute('UPDATE users SET referred_by=7001 WHERE user_id=7002')
            c.execute('UPDATE users SET trainer_id=7001 WHERE user_id=7003')
        fb.ensure_user_row(7003, 'Подопечный')
        with fb.connect() as c:
            c.execute('UPDATE users SET trainer_id=7001 WHERE user_id=7003')
        p1 = fb.record_payment(7002, 1000, 'self', 30)
        fb.record_payment(7003, 3000, 'coach', 30)
        fb.record_payment(7004, 500, 'self', 30)  # пришёл сам — начислений нет
        b = fb.trainer_balance(7001)
        self.assertEqual(b['pending'], 200 + 1800)  # PARTNER 20% + ведение 60%
        self.assertEqual(b['available'], 0)
        self.shift(1)
        self.assertEqual(fb.trainer_balance(7001)['available'], 2000)
        # Возврат до выплаты — начисление отменяется.
        self.assertTrue(fb.refund_payment(p1))
        self.assertFalse(fb.refund_payment(p1))
        self.assertEqual(fb.trainer_balance(7001)['available'], 1800)
        # Без реквизитов — в реестр не попадает.
        created, missing = fb.create_payout_registry()
        self.assertEqual((created, missing), ([], [(7001, 1800)]))
        bad = {'legal_status': 'fl', 'full_name': 'Иванов Иван', 'inn': '500100732259', 'method': 'card', 'details': '2200123412341234'}
        self.assertEqual(self.client.put('/api/trainer/requisites', json=bad, headers=th).status_code, 422)
        ok = {**bad, 'legal_status': 'npd'}
        r = self.client.put('/api/trainer/requisites', json=ok, headers=th).json()
        self.assertTrue(r['ok'])
        self.assertEqual(r['details_masked'][-4:], '1234')
        created, missing = fb.create_payout_registry()
        self.assertEqual(len(created), 1)
        csv = fb.registry_csv(created).decode('utf-8-sig')
        self.assertIn('Иванов Иван', csv)
        self.assertIn('1800,00', csv)
        self.assertEqual(fb.create_payout_registry(), ([], []))  # повторно не дублируется
        fb.mark_payout_paid(created[0])
        self.assertIsNone(fb.mark_payout_paid(created[0]))
        e = self.client.get('/api/trainer/earnings', headers=th).json()
        self.assertEqual(e['balance'], {'pending': 0, 'available': 0, 'paid': 1800})
        self.assertEqual(e['payouts'][0]['status'], 'paid')
        # Возврат после выплаты — удержание из следующей.
        coach_pay = [x for x in e['commissions'] if x['type'] == 'coaching'][0]
        with fb.connect() as c:
            pid = c.execute('SELECT payment_id FROM commissions WHERE id=?', (coach_pay['id'],)).fetchone()[0]
        fb.refund_payment(pid)
        self.assertEqual(fb.trainer_balance(7001)['available'], -1800)
        self.assertEqual(self.client.get('/api/trainer', headers=th).json()['balance']['available'], -1800)


class FriendsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(api.create_app())

    def h(self, uid, name):
        fb.ensure_user_row(uid, name)
        return {'Authorization': f'Bearer {api.create_session(uid)}'}

    def test_invite_bonus_hold_cap(self):
        ah = self.h(8001, 'Аня')
        code = fb.user_invite_code(8001)
        self.assertEqual(fb.user_invite_code(8001), code)
        self.assertEqual(fb.user_by_invite_code(code)['user_id'], 8001)
        fb.ensure_user_row(8002, 'Боря')
        self.assertEqual(fb.apply_friend_invite(8001, 8001), 'self')
        self.assertEqual(fb.apply_friend_invite(8002, 8001), 'ok')
        self.assertEqual(fb.get_user(8002)['sub_until'], (fb.now().date() + timedelta(days=7)).isoformat())
        self.assertEqual(fb.apply_friend_invite(8002, 8001), 'not_new')  # второй раз не срабатывает
        # Ссылка тренера после ссылки друга не перебивает.
        fb.ensure_user_row(8009, 'Старичок')
        with fb.connect() as c:
            c.execute("UPDATE users SET created_at='2020-01-01T00:00:00' WHERE user_id=8009")
        self.assertEqual(fb.apply_friend_invite(8009, 8001), 'not_new')
        # Оплата друга → награда после удержания, повторная оплата награду не дублирует.
        p1 = fb.record_payment(8002, 990, 'self', 30)
        fb.record_payment(8002, 990, 'self', 30)
        self.assertEqual(fb.process_friend_rewards(), [])
        with fb.connect() as c:
            c.execute("UPDATE friend_rewards SET available_at='2020-01-01' WHERE friend_id=8002")
        self.assertEqual(fb.process_friend_rewards(), [(8001, 8002, 14)])
        self.assertEqual(fb.get_user(8001)['sub_until'], (fb.now().date() + timedelta(days=14)).isoformat())
        self.assertFalse(fb.refund_payment(999999))
        self.assertTrue(fb.refund_payment(p1))  # возврат после начисления награды уже не отменяет
        r = self.client.get('/api/friends', headers=ah).json()
        self.assertEqual(r['stats'], {'invited': 1, 'paid': 1, 'days': 14})
        self.assertIn('?start=u_' + code, r['invite_url'])
        self.assertEqual(r['friends'][0]['status'], 'granted')
        # Лимит бонусных дней.
        os.environ['INVITER_BONUS_CAP_DAYS'] = '20'
        try:
            for fid in (8003, 8004):
                fb.ensure_user_row(fid, f'Друг {fid}')
                fb.apply_friend_invite(fid, 8001)
                fb.record_payment(fid, 990, 'self', 30)
            with fb.connect() as c:
                c.execute("UPDATE friend_rewards SET available_at='2020-01-01'")
            self.assertEqual(fb.process_friend_rewards(), [(8001, 8003, 6)])
        finally:
            del os.environ['INVITER_BONUS_CAP_DAYS']

    def test_refund_cancels_pending_reward(self):
        fb.ensure_user_row(8101, 'А')
        fb.ensure_user_row(8102, 'Б')
        fb.apply_friend_invite(8102, 8101)
        pid = fb.record_payment(8102, 500, 'self', 30)
        fb.refund_payment(pid)
        with fb.connect() as c:
            c.execute("UPDATE friend_rewards SET available_at='2020-01-01'")
        self.assertEqual(fb.process_friend_rewards(), [])

    def test_pair_and_card(self):
        ah = self.h(8201, 'Катя')
        fb.ensure_user_row(8202, 'Дима')
        self.assertEqual(self.client.get('/api/friends', headers=ah).json()['pair'], None)
        pair, why = fb.create_pair(8201, 8202, goal=2)
        self.assertEqual(why, 'ok')
        self.assertEqual(fb.create_pair(8202, 8203)[1], 'inviter_busy')
        for uid in (8201, 8202):
            for _ in range(2):
                fb.log_past_group(uid, next(iter(fb.GROUP_TYPES)), 45)
        st = fb.pair_status(pair, 8201)
        self.assertEqual((st['me'], st['partner_done'], st['streak'], st['closed']), (2, 2, 1, True))
        r = self.client.post('/api/friends/pair/goal', json={'goal': 4}, headers=ah).json()
        self.assertEqual(r['pair']['goal'], 4)
        self.assertEqual(r['pair']['streak'], 0)
        self.assertEqual(self.client.post('/api/friends/pair/goal', json={'goal': 9}, headers=ah).status_code, 422)
        png = self.client.get(r['card_url'])
        self.assertEqual(png.headers['content-type'], 'image/png')
        self.assertTrue(png.content.startswith(b'\x89PNG'))
        self.assertEqual(self.client.get('/api/card/zzzzzzz.png').status_code, 404)
        self.assertIsNone(self.client.delete('/api/friends/pair', headers=ah).json()['pair'])


class ThemeTests(unittest.TestCase):
    def test_theme_setting(self):
        client = TestClient(api.create_app())
        fb.ensure_user_row(9301, 'Лена')
        h = {'Authorization': f'Bearer {api.create_session(9301)}'}
        client.put('/api/me/profile', json={**PROFILE, 'gender': 'f'}, headers=h)
        self.assertIsNone(client.get('/api/me', headers=h).json()['theme'])
        self.assertEqual(client.patch('/api/me/settings', json={'theme': 'classic'}, headers=h).json()['theme'], 'classic')
        self.assertEqual(client.patch('/api/me/settings', json={'theme': 'women'}, headers=h).status_code, 422)


class BodyChatHeroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(api.create_app())

    def h(self, uid, name, gender='m'):
        fb.ensure_user_row(uid, name)
        hd = {'Authorization': f'Bearer {api.create_session(uid)}'}
        self.client.put('/api/me/profile', json={**PROFILE, 'gender': gender}, headers=hd)
        return hd

    def test_measurements(self):
        h = self.h(9401, 'Иван')
        self.assertEqual(fb.parse_measurements('100 80 - 35,5'), {'chest': 100, 'waist': 80, 'arm': 35.5})
        self.assertIsNone(fb.parse_measurements('100 abc'))
        self.assertIsNone(fb.parse_measurements('5'))
        self.assertEqual(self.client.post('/api/measurements', json={}, headers=h).status_code, 422)
        self.assertEqual(self.client.post('/api/measurements', json={'waist': 500}, headers=h).status_code, 422)
        self.client.post('/api/measurements', json={'chest': 100, 'waist': 84}, headers=h)
        r = self.client.post('/api/measurements', json={'waist': 81.5}, headers=h).json()['measurements']
        self.assertEqual(r['waist']['value'], 81.5)
        self.assertEqual(r['waist']['total_delta'], -2.5)
        self.assertIsNone(r['chest']['total_delta'])
        self.assertIn('waist', self.client.get('/api/progress', headers=h).json()['measurements'])

    def test_bundled_photos(self):
        # Встроенные фото из assets/photos отдаются, пока админ не загрузил свои.
        h = self.h(9404, 'Лена', 'f')
        photos = self.client.get('/api/meta').json()['photos']
        self.assertTrue({'home_u', 'home_m', 'home_f'} <= set(photos))
        url = self.client.get('/api/today', headers=h).json()['hero_url']
        self.assertTrue(url.startswith('/api/photos/home_f.jpg?v=b'))
        r = self.client.get(url)
        self.assertEqual(r.headers['content-type'], 'image/jpeg')
        self.assertTrue(r.content.startswith(b'\xff\xd8'))
        fb.save_app_photo('home', 'f', b'\xff\xd8own', 'image/jpeg')
        self.assertEqual(self.client.get('/api/hero/f.jpg').content, b'\xff\xd8own')
        fb.delete_app_photo('home', 'f')
        self.assertNotEqual(self.client.get('/api/hero/f.jpg').content, b'\xff\xd8own')

    def test_hero_photo(self):
        saved = fb.BUNDLED_PHOTOS
        fb.BUNDLED_PHOTOS = Path(tempfile.mkdtemp())
        try:
            self._hero_photo()
        finally:
            fb.BUNDLED_PHOTOS = saved

    def _hero_photo(self):
        h = self.h(9402, 'Оля', 'f')
        self.assertIsNone(self.client.get('/api/today', headers=h).json()['hero_url'])
        fb.save_app_photo('home', 'f', b'\xff\xd8jpegdata', 'image/jpeg')
        url = self.client.get('/api/today', headers=h).json()['hero_url']
        self.assertTrue(url.startswith('/api/photos/home_f.jpg?v='))
        self.assertEqual(self.client.get('/api/hero/f.jpg').content, b'\xff\xd8jpegdata')
        self.assertEqual(self.client.get(url).content, b'\xff\xd8jpegdata')
        self.assertEqual(self.client.get('/api/hero/m.jpg').status_code, 404)
        self.assertIn('RU', fb.hero_prompt('m') + 'RU')
        self.assertIn('мужчина', fb.hero_prompt('m'))
        self.assertIn('женщина', fb.hero_prompt('f'))
        for key in fb.APP_PHOTOS:
            self.assertGreater(len(fb.photo_prompt(key)), 300, key)
            self.assertIn('16:10', fb.photo_prompt(key, 'EN'), key)
        # Пара — до выбора пола; на неё же откатывается главная, если своей версии нет.
        fb.save_app_photo('home', 'u', b'pair', 'image/jpeg')
        photos = self.client.get('/api/meta').json()['photos']
        self.assertEqual(set(photos), {'home_f', 'home_u'})
        self.assertEqual(self.client.get(photos['home_u']).content, b'pair')
        self.assertEqual(self.client.get('/api/photos/evil_x.jpg').status_code, 404)
        fb.delete_app_photo('home', 'f')
        hm = self.h(9403, 'Миша', 'm')
        self.assertTrue(self.client.get('/api/today', headers=hm).json()['hero_url'].startswith('/api/photos/home_u.jpg'))
        fb.delete_app_photo('home', 'u')

    def test_chat(self):
        th = self.h(9411, 'Тренер Лёша')
        fb.make_trainer(9411)
        ch = self.h(9412, 'Клиент Петя')
        sh = self.h(9413, 'Чужой')
        with fb.connect() as c:
            c.execute('UPDATE users SET trainer_id=9411 WHERE user_id=9412')
        self.assertEqual(self.client.get('/api/chat/9411', headers=sh).status_code, 404)
        m = self.client.post('/api/chat/9411', json={'text': 'Привет!'}, headers=ch).json()['message']
        self.assertTrue(m['mine'])
        self.assertFalse(m['read'])
        self.assertEqual(fb.unread_count(9411, 9412), 1)
        r = self.client.get('/api/chat/9412', headers=th).json()
        self.assertEqual((r['peer']['role'], r['messages'][0]['text'], r['messages'][0]['mine']), ('client', 'Привет!', False))
        self.assertEqual(fb.unread_count(9411), 0)
        self.client.post('/api/chat/9412', json={'text': 'Здорово'}, headers=th)
        r = self.client.get(f'/api/chat/9411?after={m["id"]}', headers=ch).json()
        self.assertEqual([x['text'] for x in r['messages']], ['Здорово'])
        self.assertTrue(self.client.get('/api/chat/9411', headers=ch).json()['messages'][0]['read'])
        self.assertEqual(r['peer']['role'], 'trainer')


class CabinetButtonsTests(unittest.TestCase):
    def test_cabinet_kb_and_profile_text(self):
        fb.ensure_user_row(9701, 'Тренер Кнопка')
        fb.make_trainer(9701)
        fb.ensure_user_row(9702, 'Клиент Кнопка')
        texts = lambda: [b.text for row in fb.cabinet_kb(fb.get_user(9701)).inline_keyboard for b in row]
        self.assertNotIn('📥 Заявки (1)', texts())
        fb.create_coach_request(9702, 9701, '')
        self.assertIn('📥 Заявки (1)', texts())
        self.assertIn('📇 Профиль в каталоге', texts())
        self.assertIn('Тебя пока нет в каталоге', fb.catalog_profile_text(fb.get_user(9701)))


class AppleAndDeleteTests(unittest.TestCase):
    def test_apple_login_and_delete(self):
        client = TestClient(api.create_app())
        saved = api.verify_apple_token
        api.verify_apple_token = lambda token: {'sub': 'apple-001', 'email': 'x@privaterelay.appleid.com'} if token == 'good' else (_ for _ in ()).throw(api.HTTPException(401, 'bad'))
        try:
            self.assertEqual(client.post('/api/auth/apple', json={'identity_token': 'bad'}).status_code, 401)
            r = client.post('/api/auth/apple', json={'identity_token': 'good', 'given_name': 'Ева'}).json()
            uid = r['me']['id']
            self.assertLess(uid, 0)
            self.assertEqual(r['me']['name'], 'Ева')
            # повторный вход — тот же аккаунт
            self.assertEqual(client.post('/api/auth/apple', json={'identity_token': 'good'}).json()['me']['id'], uid)
        finally:
            api.verify_apple_token = saved
        h = {'Authorization': f'Bearer {r["token"]}'}
        client.put('/api/me/profile', json=PROFILE, headers=h)
        client.post('/api/body-weight', json={'weight': 70}, headers=h)
        client.post('/api/measurements', json={'waist': 80}, headers=h)
        self.assertEqual(client.delete('/api/me', headers=h).json(), {'ok': True})
        self.assertIsNone(fb.get_user(uid))
        self.assertEqual(fb.body_weights(uid), [])
        self.assertEqual(fb.measurements(uid), [])
        self.assertEqual(client.get('/api/me', headers=h).status_code, 401)
        self.assertIn('Политика конфиденциальности', client.get('/privacy').text)
