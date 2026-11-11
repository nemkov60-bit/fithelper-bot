"""Промты для генерации реалистичных фото техники упражнений (фитнес-модели, 4K).

Для каждого упражнения — минимум два кадра: исходное и конечное положение
(для сложных базовых упражнений — третий кадр с ключевой деталью или типичной ошибкой).
Каждый кадр — в двух версиях: с мужчиной (👨) и с женщиной (👩). В «📖 Технике» мужчины видят
мужские фото, девушки — женские.

Здесь — английские промты (Midjourney, DALL·E, Flux, Stable Diffusion понимают их точнее всего).
Русские промты — в exercise_images_ru.py. Русская подпись кадра — то, что бот покажет под фото.

Фото загружаются через бота («🛠 Админ» → «🖼 Фото упражнений») или кладутся в images/
как <id>_<кадр>.jpg (мужская версия) и <id>_<кадр>_f.jpg (женская).

Сгенерировать Markdown-файл со всеми промтами:  python exercise_images.py
"""

# Единый стиль — чтобы все фото выглядели как одна фотосессия.
STYLE = ('Photorealistic professional fitness photography, 4K, ultra detailed, shot on a full-frame camera '
         'with a 50mm lens, soft natural studio lighting, sharp focus, realistic skin texture and anatomy, '
         'correct exercise technique and accurate joint angles, full body in frame, the same model throughout '
         'the series, no text, no labels, no watermark, no logos, 4:3 aspect ratio')

PERSON = ('male fitness model in his late 20s with an athletic, naturally muscular build, short hair, '
          'wearing a plain black t-shirt, grey shorts and white sneakers')
FEMALE_PERSON = ('female fitness model in her late 20s with a toned athletic build, hair tied in a ponytail, '
                 'wearing a black sports top, grey leggings and white sneakers')

GYM = 'in a bright modern gym, softly blurred background with bokeh'
HOME = 'in a bright modern living room with a yoga mat on the floor, softly blurred background'

# id: (место, [(подпись для бота, описание кадра), ...])
EXERCISE_FRAMES = {
    # ---------------- Грудь ----------------
    'bench': (GYM, [
        ('Исходное положение: штанга на прямых руках над плечами, лопатки сведены',
         'lying on a flat bench, feet flat on the floor, barbell held with straight arms directly above the shoulders, '
         'grip slightly wider than shoulders, shoulder blades squeezed together, slight arch in lower back, side view'),
        ('Нижняя точка: гриф касается низа груди, локти под 45° к корпусу',
         'lying on a flat bench, barbell lowered to touch the lower chest, elbows bent at about 45 degrees from the torso, '
         'forearms vertical, feet planted, buttocks on the bench, side view'),
        ('Хват и положение кистей: запястья прямые, гриф на основании ладони',
         'close-up view from above of hands gripping a barbell while lying on a bench, wrists straight and stacked over '
         'forearms, bar resting on the heel of the palm, thumbs wrapped around the bar'),
    ]),
    'incline_db': (GYM, [
        ('Исходное положение: гантели над грудью на прямых руках, скамья под 30°',
         'lying on a bench inclined at 30 degrees, two dumbbells held with straight arms above the upper chest, '
         'palms facing forward, feet flat on the floor, three-quarter side view'),
        ('Нижняя точка: гантели у верха груди, локти под 45°',
         'lying on a bench inclined at 30 degrees, dumbbells lowered to the sides of the upper chest, elbows bent and '
         'below bench level at about 45 degrees from torso, chest open, three-quarter side view'),
    ]),
    'db_fly': (GYM, [
        ('Исходное положение: гантели над грудью, локти слегка согнуты',
         'lying on a flat bench, two dumbbells held above the chest with palms facing each other, elbows slightly bent, '
         'front three-quarter view'),
        ('Нижняя точка: руки разведены в стороны дугой, лёгкое растяжение груди',
         'lying on a flat bench, arms opened wide to the sides in an arc with elbows softly bent, dumbbells at chest '
         'level, chest stretched, front three-quarter view'),
    ]),
    'cable_cross': (GYM, [
        ('Исходное положение: шаг вперёд, руки разведены, корпус чуть наклонён',
         'standing in the middle of a cable crossover machine, one foot forward, torso leaning slightly forward, '
         'arms spread wide holding high cable handles, elbows slightly bent, front view'),
        ('Конечное положение: руки сведены перед грудью',
         'standing in a cable crossover machine, one foot forward, hands brought together in front of the lower chest, '
         'elbows slightly bent, chest squeezed, front view'),
    ]),
    'pushup': (HOME, [
        ('Исходное положение: упор лёжа, тело — прямая линия от головы до пяток',
         'high plank push-up position on a yoga mat, hands under shoulders, arms straight, body in a straight line from '
         'head to heels, core tight, side view'),
        ('Нижняя точка: грудь почти касается пола, локти под 45°',
         'push-up bottom position on a yoga mat, chest a few centimeters above the floor, elbows bent at 45 degrees to '
         'the torso, body perfectly straight, side view'),
        ('Ошибка: провисший таз — так делать не нужно',
         'incorrect push-up form shown on a yoga mat: hips sagging toward the floor and lower back arched, side view, '
         'subtle red tint on the sagging area'),
    ]),
    'pushup_knee': (HOME, [
        ('Исходное положение: упор с колен, корпус от коленей до головы прямой',
         'knee push-up start position on a yoga mat, knees on the mat, hands under shoulders, arms straight, '
         'straight line from knees to head, side view'),
        ('Нижняя точка: грудь у пола, таз не поднимается',
         'knee push-up bottom position on a yoga mat, chest close to the floor, elbows bent at 45 degrees, '
         'hips in line with torso, side view'),
    ]),
    'pushup_decline': (HOME, [
        ('Исходное положение: ноги на стуле, руки на полу под плечами',
         'decline push-up start position, feet resting on a chair seat, hands on a yoga mat under the shoulders, '
         'arms straight, body straight, side view'),
        ('Нижняя точка: грудь опущена к полу, корпус не прогибается',
         'decline push-up bottom position, feet on a chair, chest lowered close to the floor, elbows bent, '
         'body straight without sagging, side view'),
    ]),
    'pushup_wide': (HOME, [
        ('Исходное положение: руки шире плеч, тело прямое',
         'wide-grip push-up start position on a yoga mat, hands placed much wider than shoulders, arms straight, '
         'body straight, front three-quarter view'),
        ('Нижняя точка: медленно опуститься, грудь у пола',
         'wide-grip push-up bottom position, chest close to the floor between the hands, elbows pointing out to the '
         'sides, body straight, front three-quarter view'),
    ]),

    # ---------------- Спина ----------------
    'pullup': (GYM, [
        ('Исходное положение: вис на прямых руках, хват чуть шире плеч',
         'dead hang from a pull-up bar, overhand grip slightly wider than shoulders, arms fully straight, '
         'legs together slightly in front, shoulders engaged, side view'),
        ('Верхняя точка: грудь к перекладине, подбородок выше грифа',
         'top of a pull-up, chin above the bar, chest pulled toward the bar, elbows pointing down and back, '
         'no swinging, side view'),
    ]),
    'lat_pulldown': (GYM, [
        ('Исходное положение: руки вверху на рукояти, бёдра зафиксированы валиками',
         'seated at a lat pulldown machine, thighs under the pads, arms extended overhead holding a wide bar, '
         'torso upright with slight lean back, side view'),
        ('Конечное положение: гриф у верха груди, лопатки сведены',
         'seated at a lat pulldown machine, bar pulled down to the upper chest, elbows down and back, '
         'shoulder blades squeezed, chest up, side view'),
    ]),
    'row_bb': (GYM, [
        ('Исходное положение: наклон ~45°, спина прямая, штанга на прямых руках',
         'bent-over barbell row start, hips hinged back, torso at about 45 degrees, neutral straight back, knees '
         'slightly bent, barbell hanging at arm length below the knees, side view'),
        ('Конечное положение: штанга подтянута к поясу',
         'bent-over barbell row top position, barbell pulled to the lower ribs and belly, elbows behind the torso, '
         'back flat, torso angle unchanged, side view'),
        ('Ошибка: круглая спина — так делать не нужно',
         'incorrect bent-over row: rounded upper and lower back, head dropped, side view, subtle red tint on the '
         'rounded spine'),
    ]),
    'row_db': (GYM, [
        ('Исходное положение: колено и рука на скамье, гантель на прямой руке',
         'one-arm dumbbell row start, one knee and the same-side hand on a flat bench, back flat and parallel to the '
         'floor, other arm hanging straight down holding a dumbbell, side view'),
        ('Конечное положение: гантель у пояса, локоть вдоль корпуса',
         'one-arm dumbbell row top, dumbbell pulled to the hip, elbow close to the body and pointing up and back, '
         'back flat, side view'),
    ]),
    'seated_row': (GYM, [
        ('Исходное положение: руки вытянуты, спина прямая',
         'seated cable row machine, feet on the platform, knees slightly bent, arms extended holding a V-handle, '
         'torso upright, side view'),
        ('Конечное положение: рукоять у живота, лопатки сведены',
         'seated cable row, V-handle pulled to the belly, elbows behind the torso, chest up, shoulder blades '
         'squeezed, torso upright, side view'),
    ]),
    'inverted_row': (HOME, [
        ('Исходное положение: под прочным столом, хват за край, тело прямое',
         'inverted row under a sturdy wooden table, lying on the floor holding the table edge with straight arms, '
         'heels on the floor, body straight like a plank, side view'),
        ('Конечное положение: грудь подтянута к краю стола',
         'inverted row top position under a sturdy table, chest pulled up to the table edge, elbows bent and back, '
         'body straight from head to heels, side view'),
    ]),
    'backpack_row': (HOME, [
        ('Исходное положение: наклон вперёд, спина прямая, рюкзак в руках',
         'bent-over row at home holding a loaded backpack by its straps with both hands, hips hinged back, back flat, '
         'knees soft, arms straight, side view'),
        ('Конечное положение: рюкзак подтянут к поясу',
         'bent-over backpack row top position, backpack pulled to the belly, elbows back, shoulder blades squeezed, '
         'back flat, side view'),
    ]),
    'superman': (HOME, [
        ('Исходное положение: лёжа на животе, руки вытянуты вперёд',
         'lying face down on a yoga mat, arms extended forward overhead, legs straight, relaxed, side view'),
        ('Конечное положение: руки и ноги приподняты, задержка 2 секунды',
         'superman exercise on a yoga mat, arms, chest and legs lifted a few centimeters off the floor, '
         'gaze down, neck neutral, side view'),
    ]),

    # ---------------- Плечи ----------------
    'ohp': (GYM, [
        ('Исходное положение: штанга на груди, локти чуть впереди грифа',
         'standing overhead press start, barbell resting on the front of the shoulders, elbows slightly in front of '
         'the bar, feet hip-width, glutes and core tight, side view'),
        ('Верхняя точка: штанга над головой, над серединой стопы',
         'standing overhead press lockout, barbell overhead with straight arms, bar stacked over the mid-foot, '
         'head slightly forward through the arms, body vertical, side view'),
        ('Ошибка: сильный прогиб в пояснице — так делать не нужно',
         'incorrect overhead press: excessive lower back arch and leaning back under the barbell, side view, subtle '
         'red tint on the lower back'),
    ]),
    'db_press': (GYM, [
        ('Исходное положение: сидя, гантели на уровне плеч',
         'seated on an upright bench with back support, dumbbells at shoulder height, palms forward, elbows under the '
         'wrists, front view'),
        ('Верхняя точка: гантели выжаты вверх, не ударяются друг о друга',
         'seated dumbbell shoulder press top, arms extended overhead, dumbbells close but not touching, '
         'back against the bench, front view'),
    ]),
    'lat_raise': (GYM, [
        ('Исходное положение: гантели у бёдер, локти слегка согнуты',
         'standing with dumbbells at the sides of the thighs, palms facing in, elbows slightly bent, '
         'shoulders down, front view'),
        ('Верхняя точка: руки подняты в стороны до уровня плеч',
         'lateral raise top position, arms raised out to the sides to shoulder height, elbows slightly bent, '
         'dumbbells level with shoulders, front view'),
    ]),
    'rear_delt': (GYM, [
        ('Исходное положение: наклон вперёд, гантели под грудью',
         'bent-over rear delt fly start, torso hinged forward almost parallel to the floor, back flat, light dumbbells '
         'hanging under the chest, elbows slightly bent, side view'),
        ('Конечное положение: руки разведены в стороны',
         'bent-over rear delt fly top, arms raised out to the sides to shoulder level, elbows slightly bent, '
         'back flat, front three-quarter view'),
    ]),
    'pike_pushup': (HOME, [
        ('Исходное положение: таз высоко, тело — перевёрнутая буква «V»',
         'pike push-up start on a yoga mat, hips raised high so the body forms an inverted V, arms straight, '
         'hands shoulder-width, legs straight, side view'),
        ('Нижняя точка: голова опускается между ладоней',
         'pike push-up bottom, elbows bent, top of the head lowered toward the floor between the hands, '
         'hips still high, side view'),
    ]),
    'backpack_press': (HOME, [
        ('Исходное положение: рюкзак или бутылки на уровне плеч',
         'standing at home holding two water bottles at shoulder height, palms forward, core tight, front view'),
        ('Верхняя точка: руки выпрямлены над головой',
         'standing at home pressing two water bottles overhead with straight arms, ribs down, no lower back arch, '
         'front view'),
    ]),
    'y_raise': (HOME, [
        ('Исходное положение: лёжа на животе, руки буквой «Y» на полу',
         'lying face down on a yoga mat, arms extended overhead in a Y shape resting on the floor, thumbs up, '
         'top view'),
        ('Конечное положение: руки приподняты, лопатки вниз',
         'lying face down on a yoga mat, arms in a Y shape lifted a few centimeters off the floor, thumbs up, '
         'shoulder blades pulled down, top view'),
    ]),

    # ---------------- Квадрицепс ----------------
    'squat': (GYM, [
        ('Исходное положение: штанга на трапециях, стопы на ширине плеч',
         'back squat start, barbell resting on the upper back, feet shoulder-width with toes slightly out, '
         'standing tall, chest up, side view'),
        ('Нижняя точка: бёдра параллельно полу или ниже, пятки на полу',
         'back squat bottom, hips below parallel, knees tracking over the toes, heels flat, neutral back, '
         'chest up, barbell over mid-foot, side view'),
        ('Колени по направлению носков — вид спереди',
         'front view of a back squat bottom position, knees pushed out in line with the toes, feet flat, '
         'symmetrical stance'),
    ]),
    'leg_press': (GYM, [
        ('Исходное положение: стопы на платформе на ширине плеч, ноги почти прямые',
         'seated in a 45-degree leg press machine, feet shoulder-width on the platform, legs extended but knees not '
         'locked, lower back pressed into the seat, side view'),
        ('Нижняя точка: колени согнуты ~90°, поясница прижата',
         'leg press bottom, knees bent about 90 degrees toward the chest, lower back and hips staying on the seat, '
         'side view'),
    ]),
    'lunge_db': (GYM, [
        ('Исходное положение: стоя ровно, гантели в опущенных руках',
         'standing tall holding dumbbells at the sides, feet hip-width, side view'),
        ('Нижняя точка: широкий шаг, заднее колено почти касается пола',
         'dumbbell lunge bottom, long step forward, front knee bent 90 degrees over the ankle, back knee just above '
         'the floor, torso upright, side view'),
    ]),
    'leg_ext': (GYM, [
        ('Исходное положение: колени согнуты, валик на голенях',
         'seated in a leg extension machine, knees bent at 90 degrees, ankle pad on the lower shins, '
         'hands on the handles, side view'),
        ('Верхняя точка: ноги выпрямлены, пауза 1 секунда',
         'leg extension top, legs fully straightened, quadriceps contracted, back against the seat, side view'),
    ]),
    'bw_squat': (HOME, [
        ('Исходное положение: стопы на ширине плеч, руки перед собой',
         'bodyweight squat start on a yoga mat, feet shoulder-width, toes slightly out, arms extended forward, '
         'standing tall, side view'),
        ('Нижняя точка: таз назад и вниз, пятки на полу, спина прямая',
         'bodyweight squat bottom, hips back and down below knee level, heels flat, back straight, '
         'arms forward for balance, side view'),
    ]),
    'split_squat': (HOME, [
        ('Исходное положение: задняя нога на стуле, передняя впереди',
         'Bulgarian split squat start, rear foot top resting on a chair seat behind, front foot planted forward, '
         'standing tall, side view'),
        ('Нижняя точка: переднее бедро параллельно полу, корпус чуть вперёд',
         'Bulgarian split squat bottom, front thigh parallel to the floor, rear knee lowered toward the floor, '
         'torso leaning slightly forward, side view'),
    ]),
    'lunges': (HOME, [
        ('Исходное положение: стоя ровно, руки на поясе',
         'standing tall on a yoga mat, hands on hips, feet hip-width, side view'),
        ('Нижняя точка выпада: оба колена под 90°',
         'forward lunge bottom, front knee at 90 degrees over the ankle, back knee just above the floor, '
         'torso upright, hands on hips, side view'),
    ]),
    'wall_sit': (HOME, [
        ('Подход к стене: спина прижата, стопы на шаг впереди',
         'standing with back flat against a wall, feet one step forward from the wall, side view'),
        ('Удержание: бёдра параллельно полу, колени под 90°',
         'wall sit hold, back flat against the wall, thighs parallel to the floor, knees at 90 degrees over the '
         'ankles, arms relaxed, side view'),
    ]),

    # ---------------- Бицепс бедра ----------------
    'rdl': (GYM, [
        ('Исходное положение: стоя со штангой у бёдер, колени слегка согнуты',
         'Romanian deadlift start, standing tall holding a barbell at the thighs with straight arms, knees slightly '
         'bent, shoulders back, side view'),
        ('Нижняя точка: таз отведён назад, гриф скользит по ногам до середины голени',
         'Romanian deadlift bottom, hips pushed far back, torso hinged forward with a flat back, bar sliding down '
         'close to the legs to mid-shin, knees soft, hamstrings stretched, side view'),
        ('Ключевое: спина прямая, гриф близко к ногам',
         'side close-up of Romanian deadlift mid-position emphasizing a straight neutral spine from head to pelvis '
         'and the barbell touching the thighs'),
    ]),
    'deadlift': (GYM, [
        ('Исходное положение: гриф над серединой стопы, спина прямая, плечи над грифом',
         'conventional deadlift setup, barbell on the floor over the mid-foot, shins touching the bar, hips higher '
         'than knees, flat back, shoulders slightly in front of the bar, arms straight, side view'),
        ('Конечное положение: стоя прямо, таз и колени выпрямлены',
         'deadlift lockout, standing fully upright holding the barbell at the hips, shoulders back, '
         'no leaning back, side view'),
        ('Ошибка: круглая спина при подъёме — так делать нельзя',
         'incorrect deadlift: rounded lower back while lifting the barbell from the floor, side view, subtle red tint '
         'on the rounded spine'),
    ]),
    'leg_curl': (GYM, [
        ('Исходное положение: лёжа, ноги прямые, валик над пятками',
         'lying face down on a leg curl machine, legs straight, ankle pad just above the heels, hands on the handles, '
         'side view'),
        ('Верхняя точка: ноги согнуты, таз прижат к скамье',
         'lying leg curl top, knees bent bringing heels toward the glutes, hips pressed into the pad, side view'),
    ]),
    'sl_rdl': (HOME, [
        ('Исходное положение: стоя на одной ноге, колено слегка согнуто',
         'standing on one leg on a yoga mat, standing knee slightly bent, other foot just off the floor, '
         'arms relaxed, side view'),
        ('Нижняя точка: корпус и свободная нога — одна прямая линия',
         'single-leg Romanian deadlift bottom, torso hinged forward nearly parallel to the floor, free leg extended '
         'straight back in line with the torso, flat back, hands reaching toward the floor, side view'),
    ]),
    'slider_curl': (HOME, [
        ('Исходное положение: лёжа на спине, таз поднят, пятки на полотенце, ноги прямые',
         'lying on the back on a smooth floor, hips lifted, heels on a small towel, legs extended straight, '
         'arms on the floor, side view'),
        ('Конечное положение: пятки подтянуты к ягодицам, таз высоко',
         'hamstring slider curl, heels on a towel pulled toward the glutes, knees bent, hips lifted high in a bridge, '
         'side view'),
    ]),

    # ---------------- Ягодицы ----------------
    'hip_thrust': (GYM, [
        ('Исходное положение: лопатки на скамье, штанга на тазу, таз опущен',
         'barbell hip thrust start, upper back resting on the edge of a flat bench, padded barbell across the hips, '
         'feet flat, hips lowered toward the floor, side view'),
        ('Верхняя точка: таз поднят, корпус параллелен полу, подбородок к груди',
         'barbell hip thrust top, hips extended so torso and thighs form a straight line parallel to the floor, '
         'shins vertical, chin tucked, glutes squeezed, side view'),
        ('Положение стоп: голени вертикальны в верхней точке',
         'side close-up of feet and shins at the top of a hip thrust, shins vertical, feet flat, knees over ankles'),
    ]),
    'cable_kickback': (GYM, [
        ('Исходное положение: манжета на щиколотке, лёгкий наклон вперёд',
         'standing facing a low cable machine, ankle cuff on one ankle, holding the frame, torso leaning slightly '
         'forward, working leg next to the standing leg, side view'),
        ('Конечное положение: нога отведена назад, корпус неподвижен',
         'cable glute kickback, working leg extended straight back, glute squeezed, torso and pelvis stable, side view'),
    ]),
    'glute_bridge': (HOME, [
        ('Исходное положение: лёжа на спине, стопы у таза',
         'lying on the back on a yoga mat, knees bent, feet flat close to the hips, arms by the sides, side view'),
        ('Верхняя точка: таз поднят, линия от коленей до плеч, пауза 2 секунды',
         'glute bridge top, hips lifted so knees, hips and shoulders form a straight line, glutes squeezed, '
         'side view'),
    ]),
    'sl_bridge': (HOME, [
        ('Исходное положение: одна стопа на полу, другая нога выпрямлена',
         'lying on the back on a yoga mat, one foot flat on the floor with knee bent, other leg extended straight '
         'up at an angle, side view'),
        ('Верхняя точка: таз поднят, без перекоса',
         'single-leg glute bridge top, hips lifted level, supporting foot flat, free leg extended in line with '
         'the thigh, side view'),
    ]),

    # ---------------- Бицепс ----------------
    'bb_curl': (GYM, [
        ('Исходное положение: штанга на прямых руках, локти прижаты',
         'standing barbell curl start, barbell held with underhand grip at the thighs, arms straight, elbows at the '
         'sides, side view'),
        ('Верхняя точка: штанга у плеч, локти не уходят вперёд',
         'barbell curl top, bar curled up to shoulder level, elbows staying at the sides, torso upright without '
         'swinging, side view'),
    ]),
    'hammer': (GYM, [
        ('Исходное положение: гантели у бёдер, ладони смотрят друг на друга',
         'standing with dumbbells at the sides, neutral grip with palms facing each other, front view'),
        ('Верхняя точка: гантели подняты к плечам нейтральным хватом',
         'hammer curl top, dumbbells curled to the shoulders with palms facing each other, elbows at the sides, '
         'front view'),
    ]),
    'chinup': (HOME, [
        ('Исходное положение: вис на турнике, ладони к себе',
         'dead hang from a doorway pull-up bar, underhand grip shoulder-width with palms facing the body, arms '
         'straight, front view'),
        ('Верхняя точка: подбородок выше перекладины',
         'chin-up top, chin above the bar, underhand grip, elbows in front and down, front view'),
    ]),
    'backpack_curl': (HOME, [
        ('Исходное положение: рюкзак или бутылки в опущенных руках',
         'standing at home holding two water bottles at the sides with palms forward, arms straight, front view'),
        ('Верхняя точка: руки согнуты, локти прижаты к корпусу',
         'bicep curl with water bottles at home, bottles curled to the shoulders, elbows at the sides, front view'),
    ]),
    'towel_curl': (HOME, [
        ('Положение: стоя на середине полотенца, концы в руках',
         'standing on the middle of a long towel, holding both ends with underhand grip, elbows bent 90 degrees, '
         'front view'),
        ('Удержание: тянуть полотенце вверх изо всех сил, локти у корпуса',
         'isometric towel bicep curl, pulling the towel ends upward with tense biceps, elbows at the sides, '
         'towel taut under the feet, side view'),
    ]),

    # ---------------- Трицепс ----------------
    'pushdown': (GYM, [
        ('Исходное положение: локти прижаты, предплечья параллельны полу',
         'standing at a cable machine with a straight bar attachment, elbows tucked at the sides, forearms parallel '
         'to the floor, slight forward lean, side view'),
        ('Конечное положение: руки полностью выпрямлены вниз',
         'triceps pushdown bottom, arms fully straight, bar at the thighs, elbows still at the sides, side view'),
    ]),
    'french': (GYM, [
        ('Исходное положение: лёжа, EZ-гриф на прямых руках над лбом',
         'lying on a flat bench holding an EZ curl bar with straight arms above the forehead, arms vertical, '
         'side view'),
        ('Нижняя точка: гриф опущен ко лбу, локти смотрят вверх',
         'lying triceps extension bottom, elbows bent with upper arms still vertical, EZ bar lowered toward the '
         'forehead, side view'),
    ]),
    'dips': (GYM, [
        ('Исходное положение: упор на брусьях на прямых руках',
         'parallel bar dips top position, arms straight supporting the body, torso upright, legs slightly bent '
         'behind, side view'),
        ('Нижняя точка: локти согнуты ~90°, корпус вертикально',
         'parallel bar dips bottom, elbows bent about 90 degrees and pointing back, torso upright, shoulders not '
         'shrugged, side view'),
    ]),
    'bench_dips': (HOME, [
        ('Исходное положение: руки на краю стула, спина близко к стулу',
         'bench dips at home, hands on the edge of a sturdy chair behind, arms straight, legs extended forward with '
         'heels on the floor, back close to the chair, side view'),
        ('Нижняя точка: локти согнуты ~90°, плечи не поднимаются к ушам',
         'bench dips bottom, elbows bent about 90 degrees pointing back, hips lowered close to the chair, '
         'shoulders down, side view'),
    ]),
    'bottle_ext': (HOME, [
        ('Исходное положение: бутылка над головой на прямых руках',
         'standing at home holding one large water bottle with both hands overhead, arms straight, front view'),
        ('Нижняя точка: бутылка опущена за голову, локти смотрят вверх',
         'overhead triceps extension, bottle lowered behind the head, elbows bent and pointing up, upper arms close '
         'to the head, side view'),
    ]),
    'diamond': (HOME, [
        ('Исходное положение: ладони вместе под грудью, образуют «ромб»',
         'diamond push-up start on a yoga mat, hands together under the chest with thumbs and index fingers forming a '
         'diamond, arms straight, body straight, front three-quarter view'),
        ('Нижняя точка: грудь к кистям, локти вдоль корпуса',
         'diamond push-up bottom, chest lowered to the hands, elbows close to the ribs pointing back, '
         'body straight, side view'),
    ]),

    # ---------------- Икры ----------------
    'calf_machine': (GYM, [
        ('Исходное положение: носки на краю платформы, пятки опущены вниз',
         'standing calf raise machine, shoulders under the pads, balls of the feet on the platform edge, heels '
         'lowered below the platform, calves stretched, side view'),
        ('Верхняя точка: подъём на носки, пауза',
         'standing calf raise top, rising high onto the toes, heels lifted, calves contracted, legs straight, '
         'side view'),
    ]),
    'calf_single': (HOME, [
        ('Исходное положение: носок на краю ступеньки, пятка ниже края',
         'single-leg calf raise on a home stair step, ball of one foot on the edge, heel lowered below the step, '
         'other foot hooked behind, hand on the wall for balance, side view'),
        ('Верхняя точка: подъём на носок как можно выше',
         'single-leg calf raise top on a stair step, rising high onto the toes, hand lightly on the wall, side view'),
    ]),

    # ---------------- Пресс ----------------
    'hanging_leg': (GYM, [
        ('Исходное положение: вис на перекладине, ноги прямые',
         'hanging from a pull-up bar, arms straight, legs straight down together, body still, side view'),
        ('Верхняя точка: ноги подняты, таз подкручен',
         'hanging leg raise top, legs raised to hip height or higher, pelvis tilted up, no swinging, side view'),
    ]),
    'cable_crunch': (GYM, [
        ('Исходное положение: на коленях у блока, канат у головы',
         'kneeling cable crunch start, kneeling facing a high cable pulley, rope handles held beside the head, '
         'hips above the knees, torso upright, side view'),
        ('Конечное положение: корпус скручен вниз, локти к бёдрам',
         'kneeling cable crunch bottom, spine flexed and rounded, elbows brought down toward the thighs, '
         'hips still, side view'),
    ]),
    'plank': (HOME, [
        ('Положение: упор на предплечья, тело — прямая линия',
         'forearm plank on a yoga mat, elbows under shoulders, body in a straight line from head to heels, '
         'core braced, side view'),
        ('Ошибка: таз провис или поднят слишком высоко',
         'two incorrect forearm plank variations side by side on a yoga mat: one with sagging hips, one with hips '
         'piked too high, side view, subtle red tint on the wrong areas'),
    ]),
    'crunch': (HOME, [
        ('Исходное положение: лёжа на спине, колени согнуты, руки у головы',
         'lying on the back on a yoga mat, knees bent, feet flat, fingertips lightly behind the ears, side view'),
        ('Верхняя точка: лопатки оторваны от пола, поясница прижата',
         'abdominal crunch top, shoulder blades lifted off the mat, lower back pressed to the floor, chin not pulled '
         'by the hands, side view'),
    ]),
    'dead_bug': (HOME, [
        ('Исходное положение: лёжа на спине, руки вверх, ноги согнуты под 90°',
         'dead bug start on a yoga mat, lying on the back, arms pointing straight up to the ceiling, hips and knees '
         'bent at 90 degrees, lower back pressed to the floor, side view'),
        ('Движение: противоположные рука и нога выпрямляются к полу',
         'dead bug movement, one arm extended overhead toward the floor and the opposite leg extended straight just '
         'above the floor, other limbs still, lower back flat, side view'),
    ]),
}


# Дополнительные упражнения (альтернативы для «🔄 Заменить»).
try:
    from extra_exercises import EXTRA as _EXTRA
except ImportError:  # pragma: no cover
    from fitness_bot.extra_exercises import EXTRA as _EXTRA
for _d in _EXTRA:
    EXERCISE_FRAMES[_d['id']] = (GYM if _d['places'][0] == 'gym' else HOME,
                                 [(caption, en) for caption, en, _ in _d['frames']])


def build_prompt(exercise_id, frame_index, female=False):
    place, frames = EXERCISE_FRAMES[exercise_id]
    _, description = frames[frame_index]
    style = STYLE
    if 'close-up' in description:
        style = style.replace('full body in frame, ', 'close-up detail shot, ')
    if 'incorrect' in description:  # кадр с типичной ошибкой — «правильная техника» здесь не нужна
        style = style.replace('correct exercise technique and accurate joint angles', 'clearly visible form mistake')
    description = description.replace('subtle red tint', 'soft red glow highlighting the mistake')
    person = FEMALE_PERSON if female else PERSON
    return f'{style}. A {person}, {place}, {description}.'


def prompts_for(exercise_id, female=False):
    """[(подпись, промт), ...] для упражнения."""
    place, frames = EXERCISE_FRAMES[exercise_id]
    return [(caption, build_prompt(exercise_id, i, female)) for i, (caption, _) in enumerate(frames)]


MIDJOURNEY_TIP = ('Совет для Midjourney: добавь в конец `--ar 4:3 --style raw --q 2`, для серии одного упражнения — '
                  'один и тот же `--seed` (или `--cref` со ссылкой на первое фото модели). Для 4K — сделай Upscale.')


def build_markdown(exercises):
    lines = ['# Промты для реалистичных фото техники (English)', '',
             'Для каждого кадра — две версии: 👨 мужчина и 👩 женщина. В «📖 Технике» мужчины видят мужские фото, '
             'девушки — женские. Русские промты — в `IMAGE_PROMPTS_RU.md`.', '',
             '**Как пользоваться**', '',
             '1. Скопируй промт в генератор (Midjourney, DALL·E, Flux, Stable Diffusion, Шедеврум, Kandinsky).',
             '2. Загрузи фото через бота: «🛠 Админ» → «🖼 Фото упражнений» → упражнение → «📤 Кадр N 👨» или «👩». '
             'Или отправь боту фото с подписью `bench 1` (мужская версия) / `bench 1 f` (женская).', '',
             f'Стиль серии: `{STYLE}`', '', MIDJOURNEY_TIP, '']
    for ex in exercises:
        if ex.id not in EXERCISE_FRAMES:
            continue
        lines += [f'## {ex.name} (`{ex.id}`)', '']
        male, female = prompts_for(ex.id), prompts_for(ex.id, female=True)
        for i, ((caption, m_prompt), (_, f_prompt)) in enumerate(zip(male, female), 1):
            lines += [f'**Кадр {i}.** {caption}', '',
                      f'👨 Мужчина — подпись `{ex.id} {i}`', '', '```', m_prompt, '```', '',
                      f'👩 Женщина — подпись `{ex.id} {i} f`', '', '```', f_prompt, '```', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    from pathlib import Path

    from fitness_bot import _EXERCISE_LIST

    out = Path(__file__).resolve().parent / 'IMAGE_PROMPTS.md'
    out.write_text(build_markdown(_EXERCISE_LIST), encoding='utf-8')
    print(f'Записано: {out}')
