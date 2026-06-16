import logging
import os
import re
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from gsheets import append_row

load_dotenv(override=True)

BOT_TOKEN = os.getenv('BOT_TOKEN')
GOOGLE_CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
SPREADSHEET_URL = os.getenv('SPREADSHEET_URL')

# --- Геймификация / конфигурация ---
POINTS_PER_CORRECT = 20
POINTS_FOR_SUBSCRIPTION = 50
WINNING_THRESHOLD = 110

# Канал для проверки подписки (бот должен быть админом канала)
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME', '@talentmind')   # для getChatMember
CHANNEL_URL = os.getenv('CHANNEL_URL', 'https://t.me/talentmind')  # ссылка-кнопка «Подписаться»

# Финальные материалы
CALCULATOR_URL = os.getenv('CALCULATOR_URL', 'https://talentmind.ru/calculator')
BROCHURE_FILE = os.getenv('BROCHURE_FILE', 'HR-СТАТИСТИКА.pdf')
EVENT_INFO = os.getenv('EVENT_INFO', '19 июня в 15:00 на стенде TalentMind')

# Московское время для отметок времени в Google Таблице
MSK = timezone(timedelta(hours=3))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    exit('Ошибка: Не указан BOT_TOKEN в .env файле')

# Состояния диалога
QUIZ, SUBSCRIBE, CONTACT, EMAIL = range(4)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
EMAIL_BUTTON_TEXT = '✉️ Указать email вместо этого'

QUIZ_QUESTIONS = [
    {
        'title': 'Вопрос 1. Soft skills в эпоху автоматизации',
        'text': (
            'По данным Всемирного экономического форума (Future of Jobs Report), '
            'какая доля существующих навыков работников к 2029 году потребует обновления '
            'или замены в связи с развитием технологий?'
        ),
        'options': [
            'Около 10% — автоматизация затронет только узкоспециализированные профессии',
            'Около 25% — преимущественно рутинные физические операции',
            'Около 44% — включая значительную часть когнитивных задач',
            'Более 80% — большинство профессий исчезнет в течение 5 лет',
        ],
        'correct': 2,
        'explanation': (
            'ВЭФ фиксирует, что автоматизация затрагивает не только физический труд, но и рутинные '
            'когнитивные задачи. На этом фоне soft skills — адаптивность, критическое мышление, '
            'эмоциональный интеллект — становятся главным конкурентным преимуществом сотрудника, '
            'поскольку именно они с трудом поддаются автоматизации. Это меняет приоритеты при найме: '
            'оценивать нужно не только то, что человек умеет сегодня, но и его способность меняться.'
        ),
        'next_label': 'Следующий вопрос ▶️',
    },
    {
        'title': 'Вопрос 2. Стоимость найма',
        'text': (
            'По данным SHRM (Society for Human Resource Management), во сколько обходится компании '
            'замена одного сотрудника, если выразить это в процентах от его годового дохода?'
        ),
        'options': [
            'Около 5–10% — преимущественно расходы на публикацию вакансии',
            'Около 15–20% — стоимость услуг рекрутингового агентства',
            'От 50% до 200% годового дохода сотрудника — в зависимости от уровня позиции',
            'Более 500% — замена любого сотрудника катастрофически дорога',
        ],
        'correct': 2,
        'explanation': (
            'SHRM оценивает полную стоимость замены сотрудника в 50–200% его годовой зарплаты. Для линейного '
            'персонала это ближе к нижней границе, для менеджеров и экспертов — к верхней. В расчёт входят: '
            'прямые затраты на поиск, потеря производительности во время вакансии, время коллег на адаптацию '
            'нового человека и период выхода на плановую эффективность (обычно 3–6 месяцев). Большинство '
            'компаний учитывают только прямые расходы и систематически недооценивают реальные потери.'
        ),
        'next_label': 'Следующий вопрос ▶️',
    },
    {
        'title': 'Вопрос 3. Тихое увольнение',
        'text': (
            'Согласно исследованию Gallup 2024 года, какая доля сотрудников в мире относится к категории '
            '«тихих увольняющихся» (quiet quitters) — людей, которые формально выполняют свои обязанности, '
            'но не прикладывают дополнительных усилий?'
        ),
        'options': [
            'Около 10% — это маргинальное явление, преувеличенное медиа',
            'Около 25% — примерно каждый четвёртый',
            'Около 50% — половина глобальной рабочей силы',
            'Более 80% — подавляющее большинство сотрудников',
        ],
        'correct': 2,
        'explanation': (
            'Gallup фиксирует, что 50% сотрудников глобально находятся в состоянии «тихого увольнения»: '
            'они присутствуют на работе, но не вкладываются сверх минимума. Дополнительно 17% — «активно '
            'отстранённые», которые могут негативно влиять на коллег. Итого лишь около 30% сотрудников '
            'действительно вовлечены. Это означает, что культурное соответствие и мотивационный профиль '
            'кандидата при найме критически важны — иначе компания получает человека, который «тихо '
            'уволился» ещё до выхода на работу.'
        ),
        'next_label': 'Квиз на 60% пройден. Продолжим ▶️',
    },
    {
        'title': 'Вопрос 4. Когнитивные искажения при найме',
        'text': (
            'Согласно исследованиям в области когнитивной психологии, какой из перечисленных когнитивных '
            'эффектов наиболее часто приводит к тому, что интервьюеры отдают предпочтение кандидатам, '
            'похожим на них самих?'
        ),
        'options': [
            'Эффект Даннинга-Крюгера — переоценка собственной компетентности',
            'Эффект якоря — чрезмерная опора на первую полученную информацию',
            'Аффинити-байас (affinity bias) — неосознанное предпочтение людей с похожим бэкграундом, ценностями или стилем общения',
            'Эффект ореола — перенос одного позитивного качества на общую оценку',
        ],
        'correct': 2,
        'explanation': (
            'Аффинити-байас — один из самых распространённых и труднозаметных когнитивных искажений при найме. '
            'Интервьюер неосознанно оценивает выше тех, кто учился в том же университете, разделяет его хобби '
            'или говорит в схожем стиле. Это не злой умысел, а нейробиологический механизм. Результат — '
            'снижение разнообразия команд и воспроизводство одних и тех же паттернов, даже если компания '
            'декларирует ценность diversity.'
        ),
        'next_label': 'Финальный вопрос ▶️',
    },
    {
        'title': 'Вопрос 5. Организационная культура',
        'text': (
            'Согласно исследованию Eagle Hill Consulting, какая доля сотрудников называет корпоративную '
            'культуру главным фактором своей удовлетворённости работой?'
        ),
        'options': [
            'Около 20% — большинство людей ставят на первое место зарплату',
            'Около 45% — примерно половина сотрудников',
            '73% — корпоративная культура важнее зарплаты и льгот для большинства',
            'Около 90% — культура абсолютно доминирует над всеми остальными факторами',
        ],
        'correct': 2,
        'explanation': (
            '73% сотрудников называют корпоративную культуру главным драйвером удовлетворённости — это выше, '
            'чем зарплата, карьерные возможности или гибкость графика. При этом «культура» — не абстракция: '
            'это конкретные паттерны поведения, которые поощряются и наказываются в компании. Разрыв между '
            'декларируемыми ценностями и реальными практиками — одна из главных причин, по которым новые '
            'сотрудники уходят в первые 90 дней.'
        ),
        'next_label': 'К результатам 📊',
    },
]

# Короткие подписи для кнопок (полный текст вариантов — в сообщении).
# Кнопки в Telegram не переносят строки, поэтому подписи делаем компактными.
SHORT_LABELS = [
    ['Около 10%', 'Около 25%', 'Около 44%', 'Более 80%'],
    ['Около 5–10%', 'Около 15–20%', '50–200%', 'Более 500%'],
    ['Около 10%', 'Около 25%', 'Около 50%', 'Более 80%'],
    ['Даннинг-Крюгер', 'Эффект якоря', 'Аффинити-байас', 'Эффект ореола'],
    ['Около 20%', 'Около 45%', '73%', 'Около 90%'],
]

COMPLETED_USERS_FILE = 'completed_users.txt'


def has_user_completed(user_id):
    if not os.path.exists(COMPLETED_USERS_FILE):
        return False
    with open(COMPLETED_USERS_FILE, 'r') as f:
        completed = set(line.strip() for line in f)
    return str(user_id) in completed


def mark_user_completed(user_id):
    with open(COMPLETED_USERS_FILE, 'a') as f:
        f.write(f'{user_id}\n')


def is_answer_correct(q_index: int, chosen: int) -> bool:
    return chosen == QUIZ_QUESTIONS[q_index]['correct']


def quiz_score(context: ContextTypes.DEFAULT_TYPE) -> int:
    # answers: {q_index: chosen_option_index}
    answers = context.user_data.get('answers', {})
    return sum(
        POINTS_PER_CORRECT
        for q_index, chosen in answers.items()
        if is_answer_correct(q_index, chosen)
    )


def answer_cell(q_index: int, chosen: int) -> str:
    """Готовит ячейку для Google Таблицы: выбранный вариант + вердикт."""
    label = SHORT_LABELS[q_index][chosen]
    verdict = 'верно' if is_answer_correct(q_index, chosen) else 'неверно'
    return f'{chosen + 1}. {label} ({verdict})'


def total_score(context: ContextTypes.DEFAULT_TYPE) -> int:
    bonus = POINTS_FOR_SUBSCRIPTION if context.user_data.get('subscribed') else 0
    return quiz_score(context) + bonus


def render_question(q_index: int) -> str:
    q = QUIZ_QUESTIONS[q_index]
    options = '\n'.join(f'{i + 1}. {opt}' for i, opt in enumerate(q['options']))
    return f'<b>{q["title"]}</b>\n\n{q["text"]}\n\n{options}'


def question_keyboard(q_index: int) -> InlineKeyboardMarkup:
    # Полный текст вариантов — в сообщении; на кнопках — короткие подписи (по 2 в ряд)
    labels = SHORT_LABELS[q_index]
    buttons = [
        InlineKeyboardButton(f'{i + 1}. {labels[i]}', callback_data=f'ans:{q_index}:{i}')
        for i in range(len(labels))
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


# --- Обработчики ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    if has_user_completed(user.id):
        await update.message.reply_text('👋 Вы уже участвовали в квизе. Спасибо! Удачи в розыгрыше 🍀')
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data['answers'] = {}

    text = (
        'Готовы проверить свою HR-интуицию? 🧠\n\n'
        'Пройдите наш квиз из 5 вопросов об ИИ в рекрутинге и выиграйте приз!\n\n'
        '<b>Правила просты:</b>\n'
        '• Отвечайте на 5 вопросов.\n'
        f'• За каждый правильный ответ — {POINTS_PER_CORRECT} баллов.\n'
        f'• Подпишитесь на наш канал и получите ещё {POINTS_FOR_SUBSCRIPTION} баллов.\n\n'
        f'Для участия в розыгрыше приза нужно набрать {WINNING_THRESHOLD} баллов и более.\n\n'
        'Для начала, пожалуйста, поделитесь контактом — нажмите кнопку ниже ⬇️'
    )
    contact_button = KeyboardButton(text='📱 Поделиться контактом', request_contact=True)
    keyboard = ReplyKeyboardMarkup(
        [[contact_button], [KeyboardButton(EMAIL_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')
    return CONTACT


async def begin_quiz(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Контакт получен — убираем reply-клавиатуру и предлагаем начать квиз."""
    name = context.user_data.get('first_name') or ''
    await message.reply_text(
        f'Спасибо{", " + name if name else ""}! Контакт получен ✅',
        reply_markup=ReplyKeyboardRemove(),
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton('🚀 Начать квиз', callback_data='start_quiz')]])
    await message.reply_text(
        'Нажмите кнопку, чтобы начать квиз из 5 вопросов.',
        reply_markup=keyboard,
    )
    return QUIZ


async def send_question(message, q_index: int) -> None:
    """Отправляет вопрос отдельным НОВЫМ сообщением (история чата сохраняется)."""
    await message.reply_text(
        render_question(q_index),
        reply_markup=question_keyboard(q_index),
        parse_mode='HTML',
    )


async def on_start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.setdefault('answers', {})
    # Убираем кнопку «Начать квиз» у приветствия, но само сообщение оставляем в истории
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await send_question(query.message, 0)
    return QUIZ


async def on_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    _, q_str, opt_str = query.data.split(':')
    q_index, chosen = int(q_str), int(opt_str)
    answers = context.user_data.setdefault('answers', {})

    if q_index in answers:
        # Уже отвечали на этот вопрос — игнорируем повторное нажатие
        await query.answer('Вы уже ответили на этот вопрос')
        return QUIZ

    q = QUIZ_QUESTIONS[q_index]
    is_correct = chosen == q['correct']
    answers[q_index] = chosen  # храним выбранный вариант, корректность считаем по нему
    await query.answer('Верно! +20' if is_correct else 'Неверно')

    verdict = (
        f'✅ <b>Верно!</b> (+{POINTS_PER_CORRECT} баллов)'
        if is_correct
        else '❌ <b>Неверно.</b> (+0 баллов)'
    )
    # Сообщение с вопросом превращается в постоянную запись: вопрос + ваш ответ + пояснение
    body = (
        f'{render_question(q_index)}\n\n'
        f'{verdict}\n'
        f'Ваш ответ: {chosen + 1}. {q["options"][chosen]}\n'
        f'Правильный ответ: {q["correct"] + 1}. {q["options"][q["correct"]]}\n\n'
        f'💡 {q["explanation"]}'
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(q['next_label'], callback_data=f'next:{q_index}')]]
    )
    await query.edit_message_text(body, reply_markup=keyboard, parse_mode='HTML')
    return QUIZ


async def on_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    q_index = int(query.data.split(':')[1])

    # Замораживаем запись по текущему вопросу: убираем кнопку «Далее», но сообщение остаётся в истории
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    next_index = q_index + 1
    if next_index < len(QUIZ_QUESTIONS):
        await send_question(query.message, next_index)
        return QUIZ

    # Квиз завершён — промежуточный итог отдельным сообщением
    score = quiz_score(context)
    text = (
        'Отличная работа! Квиз пройден. 🎯\n\n'
        f'<b>Ваш результат — {score} баллов</b>\n\n'
        f'Чтобы принять участие в розыгрыше приза, вам необходимо преодолеть порог в {WINNING_THRESHOLD} баллов.\n'
        'Для этого нужно подписаться на наш Telegram-канал TalentMind и получить +50 баллов.'
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton('📢 Подписаться на канал', url=CHANNEL_URL)],
        [InlineKeyboardButton('🔄 Проверить подписку', callback_data='check_sub')],
    ])
    await query.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')
    return SUBSCRIBE


async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ('member', 'administrator', 'creator', 'owner')
    except Exception as e:
        logger.error(f'Ошибка проверки подписки на {CHANNEL_USERNAME}: {e}')
        return False


async def on_check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    subscribed = await is_subscribed(context, user_id)

    if subscribed:
        context.user_data['subscribed'] = True
        await query.answer('Подписка подтверждена!')
        total = total_score(context)
        text = (
            f'✅ Успешно! Подписка подтверждена. Вам начислено {POINTS_FOR_SUBSCRIPTION} баллов.\n\n'
            f'<b>Ваш итоговый счёт: {total} баллов</b>'
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton('✅ Подтверждаю участие в розыгрыше', callback_data='confirm_draw')]]
        )
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        return SUBSCRIBE

    await query.answer('Подписка не найдена', show_alert=True)
    text = (
        '⚠️ Мы не нашли вашу подписку на канал. Пожалуйста, подпишитесь, чтобы забрать '
        f'{POINTS_FOR_SUBSCRIPTION} баллов и принять участие в розыгрыше приза.'
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton('📢 Подписаться на канал', url=CHANNEL_URL)],
        [InlineKeyboardButton('🔄 Проверить подписку', callback_data='check_sub')],
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
    return SUBSCRIBE


async def on_confirm_draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Контакт уже получен в начале — сразу выдаём материалы и сохраняем данные
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    return await finalize(query.message, query.from_user, context)


async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    contact = update.message.contact
    context.user_data['phone'] = contact.phone_number
    context.user_data['first_name'] = contact.first_name or update.message.from_user.first_name or ''
    context.user_data['last_name'] = contact.last_name or ''
    return await begin_quiz(update.message, context)


async def on_contact_reprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        'Пожалуйста, нажмите кнопку «📱 Поделиться контактом» внизу экрана '
        'или выберите «✉️ Указать email вместо этого».'
    )
    return CONTACT


async def on_use_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        'Пожалуйста, введите ваш email, чтобы мы могли связаться с вами.',
        reply_markup=ReplyKeyboardRemove(),
    )
    return EMAIL


async def on_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text('Это не похоже на email. Попробуйте ещё раз, например: name@company.ru')
        return EMAIL
    context.user_data['email'] = email
    context.user_data.setdefault('first_name', update.message.from_user.first_name or '')
    return await begin_quiz(update.message, context)


async def finalize(message, user, context: ContextTypes.DEFAULT_TYPE) -> int:
    congrats = (
        f'🎉 Поздравляем! Вы зарегистрированы в розыгрыше приза. Он состоится {EVENT_INFO}. Удачи!\n\n'
        'А пока мы подготовили для вас полезные материалы:\n\n'
        '🧮 <b>Калькулятор стоимости кадровых ошибок</b> — рассчитайте экономию для вашей компании.\n'
        '📗 <b>Брошюра TalentMind</b> с подробным описанием технологии Culture Scan (во вложении).'
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton('🧮 Открыть калькулятор', url=CALCULATOR_URL)]]
    )
    await message.reply_text(congrats, reply_markup=keyboard, parse_mode='HTML')
    await message.reply_text('HR-интуиция — хорошо. Данные — лучше. 📊')

    try:
        with open(BROCHURE_FILE, 'rb') as pdf:
            await message.reply_document(document=pdf)
    except Exception as e:
        logger.error(f'Ошибка отправки брошюры {BROCHURE_FILE}: {e}')

    # Сохраняем все данные участника в Google Таблицу:
    # время, контакты, ответ по каждому вопросу, баллы за квиз, подписку и итог
    answers = context.user_data.get('answers', {})
    row_data = [
        datetime.now(MSK).strftime('%d.%m.%Y %H:%M'),
        context.user_data.get('first_name', ''),
        context.user_data.get('last_name', ''),
        f'@{user.username}' if user.username else '',
        context.user_data.get('phone', ''),
        context.user_data.get('email', ''),
    ] + [
        answer_cell(i, answers[i]) if i in answers else '—'
        for i in range(len(QUIZ_QUESTIONS))
    ] + [
        quiz_score(context),
        'да' if context.user_data.get('subscribed') else 'нет',
        total_score(context),
    ]

    try:
        await append_row(GOOGLE_CREDENTIALS_FILE, SPREADSHEET_URL, row_data)
        logger.info(f'Записан лид: {row_data}')
    except Exception as e:
        import traceback
        logger.error(f'Ошибка при записи в Google Таблицу: {e}')
        logger.error(traceback.format_exc())

    mark_user_completed(user.id)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Квиз отменён. Чтобы начать заново, отправьте /start.', reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            QUIZ: [
                CallbackQueryHandler(on_start_quiz, pattern='^start_quiz$'),
                CallbackQueryHandler(on_answer, pattern='^ans:'),
                CallbackQueryHandler(on_next, pattern='^next:'),
            ],
            SUBSCRIBE: [
                CallbackQueryHandler(on_check_sub, pattern='^check_sub$'),
                CallbackQueryHandler(on_confirm_draw, pattern='^confirm_draw$'),
            ],
            CONTACT: [
                MessageHandler(filters.CONTACT, on_contact),
                MessageHandler(filters.Regex(f'^{re.escape(EMAIL_BUTTON_TEXT)}$'), on_use_email),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_contact_reprompt),
            ],
            EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_email),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', start)],
    )

    app.add_handler(conv_handler)

    print('Бот успешно запущен и готов к работе!')
    app.run_polling()


if __name__ == '__main__':
    main()
