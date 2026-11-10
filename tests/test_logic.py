import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['FITNESS_DB'] = os.path.join(tempfile.mkdtemp(), 'test.db')

import fitness_bot as fb  # noqa: E402


class ProgramTests(unittest.TestCase):
    def test_all_combinations_build(self):
        for goal in fb.GOALS:
            for level in fb.LEVELS:
                for days in fb.DAY_OPTIONS:
                    for place, gender, age in [(pl, g, a) for pl in fb.PLACES for g in fb.GENDERS for a in fb.AGES]:
                        program = fb.build_program(goal, level, days, place, gender, age)
                        self.assertEqual(len(program), max(2, days))
                        for day in program:
                            ids = [p.exercise.id for p in day.exercises]
                            self.assertEqual(len(ids), len(set(ids)), (goal, level, days, place, day.title))
                            for p in day.exercises:
                                self.assertIn(place, p.exercise.places)
                                if fb.age_group(age) in ('teen', 'senior') and p.exercise.unit == 'reps':
                                    self.assertGreaterEqual(p.presc.lo, 8)
                                self.assertGreaterEqual(p.presc.sets, 2)
                                self.assertLess(p.presc.lo, p.presc.hi)

    def test_variants_differ(self):
        a, b = fb.build_program('mass', 'mid', 4, fb.GYM)[0::2]
        self.assertNotEqual([p.exercise.id for p in a.exercises], [p.exercise.id for p in b.exercises])
        self.assertTrue(a.title.endswith('A') and b.title.endswith('B'))

    def test_goal_affects_prescription(self):
        strength = fb.build_program('strength', 'mid', 3, fb.GYM)[0].exercises[0].presc
        fat = fb.build_program('fat_loss', 'mid', 3, fb.GYM)[0].exercises[0].presc
        self.assertLess(strength.hi, fat.lo + 1)
        self.assertGreater(strength.rest, fat.rest)

    def test_novice_three_days_is_full_body(self):
        program = fb.build_program('fit', 'novice', 3, fb.HOME)
        self.assertTrue(all(d.title.startswith('Всё тело') for d in program))


class ParsingTests(unittest.TestCase):
    def test_parse_set(self):
        self.assertEqual(fb.parse_set('80 8'), (80.0, 8))
        self.assertEqual(fb.parse_set('62,5x10'), (62.5, 10))
        self.assertEqual(fb.parse_set('62.5 × 10'), (62.5, 10))
        self.assertEqual(fb.parse_set('100кг 5 раз'), (100.0, 5))
        self.assertEqual(fb.parse_set('12'), (0.0, 12))
        self.assertIsNone(fb.parse_set('привет'))
        self.assertIsNone(fb.parse_set('1 2 3'))
        self.assertIsNone(fb.parse_set('60 0'))
        self.assertIsNone(fb.parse_set('60 7.5'))

    def test_parse_weight(self):
        self.assertEqual(fb.parse_weight('78,4'), 78.4)
        self.assertEqual(fb.parse_weight('80 кг'), 80.0)
        self.assertIsNone(fb.parse_weight('5'))


class AdviceTests(unittest.TestCase):
    def setUp(self):
        self.ex = fb.EXERCISES['squat']
        self.presc = fb.Prescription(3, 6, 10, 120)

    def test_increase_when_top_of_range(self):
        self.assertIn('добавь 5 кг', fb.advice(self.ex, self.presc, [(80, 10)] * 3))
        bench = fb.EXERCISES['bench']
        self.assertIn('2.5 кг', fb.advice(bench, self.presc, [(60, 10)] * 3))

    def test_hold_when_below(self):
        self.assertIn('Оставь 80 кг', fb.advice(self.ex, self.presc, [(80, 8), (80, 5)]))

    def test_keep_weight_in_range(self):
        self.assertIn('Тот же вес 80 кг', fb.advice(self.ex, self.presc, [(80, 9)] * 3))

    def test_first_time(self):
        self.assertIn('Первый раз', fb.advice(self.ex, self.presc, []))

    def test_e1rm(self):
        self.assertAlmostEqual(fb.e1rm(100, 10), 133.33, places=1)
        self.assertEqual(fb.e1rm(100, 1), 100)
        self.assertEqual(fb.e1rm(0, 15), 15)


class DbTests(unittest.TestCase):
    def test_history_and_records(self):
        fb.init_db()
        uid = 42
        fb.save_user(uid, 'Тест', {'gender': 'm', 'age': '30', 'goal': 'mass', 'level': 'mid', 'days': 3,
                                   'place': fb.GYM})
        w1 = fb.start_workout(uid, 0, 'День 1')
        fb.add_set(w1, uid, 'bench', 1, 60, 10)
        fb.add_set(w1, uid, 'bench', 2, 60, 8)
        fb.finish_workout_db(w1)
        w2 = fb.start_workout(uid, 0, 'День 1')
        fb.add_set(w2, uid, 'bench', 1, 70, 6)
        self.assertEqual(fb.previous_sets(uid, 'bench', w2), [(60, 10), (60, 8)])
        self.assertAlmostEqual(fb.best_e1rm(uid, 'bench', w2), 80.0)
        fb.finish_workout_db(w2)
        self.assertEqual(fb.personal_records(uid)['bench'][1], 70)
        self.assertEqual(fb.best_weight(uid, 'bench'), 70)
        fb.set_exercise_goal(uid, 'bench', 100)
        self.assertIn('70 / 100 кг', fb.goals_text(uid))
        fb.add_body_weight(uid, 80)
        fb.add_body_weight(uid, 78)
        fb.set_user_field(uid, 'target_weight', 75)
        self.assertIn('40%', fb.goals_text(uid))


class ProfileTests(unittest.TestCase):
    def ids(self, program):
        return {p.exercise.id for d in program for p in d.exercises}

    def test_senior_program_is_gentle(self):
        program = fb.build_program('strength', 'mid', 4, fb.GYM, 'm', '60')
        self.assertFalse(self.ids(program) & {'deadlift', 'squat', 'ohp', 'row_bb'})
        self.assertTrue(all(p.presc.sets <= 3 for d in program for p in d.exercises))

    def test_novice_gets_machines_and_start_weights(self):
        program = fb.build_program('mass', 'novice', 3, fb.GYM, 'm', '30')
        self.assertNotIn('pullup', self.ids(program))
        user = {'gender': 'f', 'age': '30'}
        self.assertIn('10–20', fb.start_weight(fb.EXERCISES['bench'], user))
        self.assertIn('20 кг', fb.start_weight(fb.EXERCISES['bench'], {'gender': 'm', 'age': '30'}))

    def test_female_glute_focus(self):
        def glutes(g):
            program = fb.build_program('fit', 'mid', 4, fb.GYM, g, '30')
            return sum(p.exercise.group == 'glutes' for d in program for p in d.exercises)
        self.assertGreater(glutes('f'), glutes('m'))

    def test_female_novice_home_knee_pushups(self):
        ids = self.ids(fb.build_program('fit', 'novice', 2, fb.HOME, 'f', '30'))
        self.assertIn('pushup_knee', ids)
        self.assertNotIn('pushup_knee', self.ids(fb.build_program('fit', 'novice', 2, fb.HOME, 'm', '30')))

    def test_female_weight_step(self):
        self.assertEqual(fb.weight_step(fb.EXERCISES['bench'], 'f'), 1.25)
        self.assertEqual(fb.weight_step(fb.EXERCISES['squat'], 'm'), 5)


class CycleTests(unittest.TestCase):
    def user(self, start, length=28, period=5):
        return {'gender': 'f', 'cycle_tracking': 1, 'period_start': start.isoformat(),
                'cycle_len': length, 'period_len': period}

    def test_phases(self):
        start = fb.date(2026, 11, 1)
        u = self.user(start)
        phase = lambda offset: fb.cycle_info(u, start + fb.timedelta(days=offset))['phase']
        self.assertEqual(phase(0), 'menstrual')
        self.assertEqual(phase(4), 'menstrual')
        self.assertEqual(phase(6), 'follicular')
        self.assertEqual(phase(13), 'ovulation')
        self.assertEqual(phase(18), 'luteal')
        self.assertEqual(phase(25), 'pms')
        self.assertEqual(phase(28), 'menstrual')  # следующий цикл по прогнозу
        info = fb.cycle_info(u, start + fb.timedelta(days=10))
        self.assertEqual(info['day'], 11)
        self.assertEqual(info['next_start'], fb.date(2026, 11, 29))

    def test_no_tracking(self):
        self.assertIsNone(fb.cycle_info({'gender': 'm'}))
        self.assertIsNone(fb.cycle_info({'gender': 'f', 'cycle_tracking': 0, 'period_start': '2026-11-01'}))

    def test_menstrual_mods_reduce_load(self):
        fb.init_db()
        today = fb.now().date()
        u = {'user_id': 900, 'level': 'mid', 'days': 3, **self.user(today)}
        mods = fb.today_mods(u, finished_count=10)
        self.assertEqual(mods['sets'], -1)
        self.assertTrue(mods['no_progress'])
        std = fb.today_mods(u, finished_count=10, standard=True)
        self.assertEqual(std['sets'], 0)
        day = fb.build_program('mass', 'mid', 3, fb.GYM, 'f', '30')[0]
        light = fb.apply_mods(day, mods)
        self.assertEqual(light.exercises[0].presc.sets, day.exercises[0].presc.sets - 1)
        self.assertIn('без прибавки', fb.advice(fb.EXERCISES['bench'], light.exercises[0].presc, [(40, 10)], 'f', True))

    def test_novice_adaptation(self):
        u = {'user_id': 901, 'level': 'novice', 'days': 3, 'gender': 'm'}
        self.assertEqual(fb.today_mods(u, finished_count=0)['sets'], -1)
        self.assertEqual(fb.today_mods(u, finished_count=6)['sets'], 0)

    def test_parse_date(self):
        today = fb.date(2026, 11, 8)
        self.assertEqual(fb.parse_date('03.11', today), fb.date(2026, 11, 3))
        self.assertEqual(fb.parse_date('25.10.2026', today), fb.date(2026, 10, 25))
        self.assertIsNone(fb.parse_date('20.11', today))  # прошлый год — старше 90 дней
        self.assertIsNone(fb.parse_date('01.01.2020', today))
        self.assertIsNone(fb.parse_date('abc', today))

    def test_cycle_length_learned(self):
        fb.init_db()
        uid = 77
        fb.save_user(uid, 'Аня', {'gender': 'f', 'age': '30', 'goal': 'fit', 'level': 'novice', 'days': 2,
                                  'place': fb.GYM, 'cycle_tracking': 1, 'period_start': '2026-09-01'})
        fb.log_period_start(uid, '2026-10-01')
        fb.log_period_start(uid, '2026-10-31')
        user = fb.get_user(uid)
        self.assertEqual(user['cycle_len'], 30)
        self.assertEqual(user['period_start'], '2026-10-31')


if __name__ == '__main__':
    unittest.main()


class ImagePromptTests(unittest.TestCase):
    def test_every_exercise_has_two_frames(self):
        import exercise_images as ei
        for ex in fb._EXERCISE_LIST:
            self.assertIn(ex.id, ei.EXERCISE_FRAMES, ex.id)
            prompts = ei.prompts_for(ex.id)
            self.assertGreaterEqual(len(prompts), 2, ex.id)
            for caption, prompt in prompts:
                self.assertTrue(caption and len(caption) <= 1024)
                self.assertIn('no text', prompt)
        self.assertFalse(set(ei.EXERCISE_FRAMES) - set(fb.EXERCISES))

    def test_markdown_is_up_to_date(self):
        import exercise_images as ei
        md = Path(__file__).resolve().parents[1] / 'IMAGE_PROMPTS.md'
        self.assertEqual(md.read_text(encoding='utf-8'), ei.build_markdown(fb._EXERCISE_LIST),
                         'Перегенерируй: python fitness_bot/exercise_images.py')

    def test_photo_lookup(self):
        old = fb.IMAGES_DIR
        fb.IMAGES_DIR = Path(tempfile.mkdtemp())
        try:
            (fb.IMAGES_DIR / 'bench_1.png').write_bytes(b'x')
            (fb.IMAGES_DIR / 'bench_2.jpg').write_bytes(b'x')
            (fb.IMAGES_DIR / 'bench_2_f.jpg').write_bytes(b'x')
            self.assertEqual([p.name for p, _ in fb.exercise_photos('bench', 'm')], ['bench_1.png', 'bench_2.jpg'])
            self.assertEqual([p.name for p, _ in fb.exercise_photos('bench', 'f')], ['bench_1.png', 'bench_2_f.jpg'])
            self.assertEqual(fb.exercise_photos('squat'), [])
        finally:
            fb.IMAGES_DIR = old


class TechniqueTests(unittest.TestCase):
    def test_every_exercise_has_technique(self):
        from exercise_technique import TECHNIQUE
        self.assertEqual(set(TECHNIQUE), set(fb.EXERCISES))
        for ex in fb._EXERCISE_LIST:
            secondary, setup, steps, breath, mistakes = TECHNIQUE[ex.id]
            self.assertTrue(setup and breath and len(steps) >= 2 and mistakes, ex.id)
            text = fb.technique_text(ex, {'level': 'novice', 'gender': 'f', 'age': '30'})
            self.assertLess(len(text), 4096, ex.id)
            self.assertIn('Выполнение', text)

    def test_admin_screens_fit_telegram_limits(self):
        for ex in fb._EXERCISE_LIST:
            self.assertLess(len(fb.admin_exercise_text(ex)), 4096, ex.id)
            for row in fb.admin_exercise_kb(ex).inline_keyboard:
                for b in row:
                    self.assertLessEqual(len(b.callback_data.encode()), 64)

    def test_admin_ids(self):
        old = os.environ.get('ADMIN_ID')
        try:
            os.environ['ADMIN_ID'] = '123, 456'
            self.assertTrue(fb.is_admin(456))
            self.assertFalse(fb.is_admin(789))
            os.environ['ADMIN_ID'] = ''
            self.assertFalse(fb.is_admin(123))
        finally:
            if old is None:
                os.environ.pop('ADMIN_ID', None)
            else:
                os.environ['ADMIN_ID'] = old

    def test_photos_by_gender(self):
        fb.init_db()
        fb.save_photo('crunch', 1, '', 'MALE_1')
        fb.save_photo('crunch', 1, 'f', 'FEMALE_1')
        fb.save_photo('crunch', 2, 'f', 'FEMALE_2')
        # Мужчинам — мужские фото, девушкам — женские; если версии своего пола нет — показываем другую.
        self.assertEqual([s for s, _ in fb.exercise_photos('crunch', 'm')], ['MALE_1', 'FEMALE_2'])
        self.assertEqual([s for s, _ in fb.exercise_photos('crunch', 'f')], ['FEMALE_1', 'FEMALE_2'])
        self.assertEqual(fb.photo_coverage('crunch', ''), (1, 2))
        self.assertEqual(fb.photo_coverage('crunch', 'f'), (2, 2))
        self.assertEqual(fb.coverage_label('crunch'), '👨 1/2 · 👩 2/2')
        fb.delete_photo('crunch', 1, '')
        self.assertEqual(fb.photo_coverage('crunch', ''), (0, 2))


class RussianPromptTests(unittest.TestCase):
    def test_every_frame_has_russian_prompt(self):
        import exercise_images as ei
        import exercise_images_ru as ru
        self.assertEqual(set(ru.FRAMES_RU), set(ei.EXERCISE_FRAMES))
        for ex_id, (_, frames) in ei.EXERCISE_FRAMES.items():
            self.assertEqual(len(ru.FRAMES_RU[ex_id]), len(frames), ex_id)
            for i in range(len(frames)):
                prompt = ru.build_prompt_ru(ex_id, i)
                self.assertIn('без текста', prompt)
                self.assertIn(ru.FEMALE_PERSON_RU[1:], ru.build_prompt_ru(ex_id, i, female=True))
                self.assertIn('4K', prompt)
                self.assertNotIn('иллюстрац', prompt)
                self.assertIn(ei.FEMALE_PERSON, ei.build_prompt(ex_id, i, female=True))
                self.assertIn('Photorealistic', ei.build_prompt(ex_id, i))

    def test_russian_markdown_is_up_to_date(self):
        import exercise_images_ru as ru
        md = Path(__file__).resolve().parents[1] / 'IMAGE_PROMPTS_RU.md'
        self.assertEqual(md.read_text(encoding='utf-8'), ru.build_markdown_ru(fb._EXERCISE_LIST),
                         'Перегенерируй: python exercise_images_ru.py')

    def test_admin_prompt_messages_fit(self):
        for ex in fb._EXERCISE_LIST:
            for lang in ('ru', 'en'):
                for gender in ('', 'f'):
                    self.assertLess(len(fb.admin_prompts_text(ex, lang, gender)), 4096, ex.id)
            for i in range(1, fb.frame_count(ex.id) + 1):
                for gender in ('', 'f'):
                    self.assertLess(len(fb.ask_photo_text(ex, i, gender)), 4000)
