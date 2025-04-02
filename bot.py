import logging
import re
import random
import string
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# --- Состояния диалога (индексы) ---
# 0: CHOOSING_CATEGORY
# 1: GETTING_PRICE
# 2: AFTER_CALC
# 3: ORDER_NAME
# 4: ORDER_LINK
# 5: ORDER_SCREENSHOT
# 6: FINISH_ORDER
# 7: PROMO_INPUT
# 8: ORDER_RECEIPT
(CHOOSING_CATEGORY, GETTING_PRICE, AFTER_CALC, ORDER_NAME, ORDER_LINK, 
 ORDER_SCREENSHOT, FINISH_ORDER, PROMO_INPUT, ORDER_RECEIPT) = range(9)

# Токен бота (всегда используем его)
TOKEN = "7883376612:AAElSoIAd02N7lFASiDDuw1OeM9NPyhEXz4"
ADMIN_ID = 733949485  # Ваш Telegram ID

# Глобальный список заказов (в оперативной памяти)
orders = []  # Каждый заказ – словарь

# Глобальный счётчик заказов
GLOBAL_ORDER_NUMBER = 1

# Возможные статусы заказа
STATUSES = [
    "создан",
    "оплачен",
    "на_подтверждении",
    "выкуплен",
    "ждет_отправки",
    "отправлен",
    "прибыл",
    "доставлен",
]

# Глобальные словари для промокодов и реферальных кодов
# promo_codes: key = промокод, value = {"type": "one-time"/"multi", "discount": int, "used_by": set()}
promo_codes = {}
# referral_codes: key = user_id, value = реферальный код
referral_codes = {}
# referral_bonus: key = user_id, value = сумма бонусов (в рублях)
referral_bonus = {}

# --- Логирование ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= Функции для генерации случайного кода =================

def generate_random_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# ================= Функции для постоянного меню =================

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        ["Личный кабинет", "Рассчитать"],
        ["Поддержка"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Главное меню:", reply_markup=get_main_menu_keyboard())

# ================= Пользовательский интерфейс =================

def get_categories_inline_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Одежда", callback_data="Одежда")],
        [InlineKeyboardButton("Обувь", callback_data="Обувь")],
        [InlineKeyboardButton("Аксессуары", callback_data="Аксессуары")],
        [InlineKeyboardButton("Сумки", callback_data="Сумки")],
        [InlineKeyboardButton("Часы", callback_data="Часы")],
        [InlineKeyboardButton("Парфюм", callback_data="Парфюм")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    args = update.message.text.split()
    if len(args) > 1:
        ref_code = args[1]
        context.user_data["referral_received"] = ref_code
    try:
        with open("category.jpg", "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption="Добро пожаловать! Пожалуйста, выберите категорию:",
                reply_markup=get_categories_inline_keyboard(),
            )
    except Exception as e:
        logger.error("Ошибка при отправке category.jpg: %s", e)
        await update.message.reply_text(
            "Добро пожаловать! Пожалуйста, выберите категорию:",
            reply_markup=get_categories_inline_keyboard(),
        )
    context.user_data["basket"] = []
    return CHOOSING_CATEGORY

async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["category"] = query.data
    try:
        await query.edit_message_caption(caption=f"Вы выбрали категорию: {query.data}")
    except Exception as e:
        logger.error("Ошибка редактирования подписи: %s", e)
    try:
        media = [
            InputMediaPhoto(media=open("instructions1.jpg", "rb")),
            InputMediaPhoto(media=open("instructions2.jpg", "rb")),
        ]
        await context.bot.send_media_group(chat_id=query.message.chat_id, media=media)
    except Exception as e:
        logger.error("Ошибка отправки медиа-группы: %s", e)
    await query.message.reply_text("Теперь введите цену в юанях для расчёта стоимости:")
    return GETTING_PRICE

async def calculate_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        price_yuan = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Ошибка: введите корректное число.")
        return GETTING_PRICE
    commission = 2500 if price_yuan > 3000 else 1500
    final_price = price_yuan * 13 + commission
    category = context.user_data.get("category", "не указана")
    context.user_data["order"] = {
        "user_id": update.effective_user.id,
        "username": update.effective_user.username or update.effective_user.first_name,
        "category": category,
        "price_yuan": price_yuan,
        "commission": commission,
        "final_price": final_price,
        "status": "создан",
        "created_at": datetime.now().isoformat(),
    }
    response_text = (
        f"**Рассчёт стоимости**\n"
        f"Категория: {category}\n"
        f"Цена в юанях: {price_yuan}\n"
        f"Курс: 13\n"
        f"Комиссия: {commission}\n"
        f"**Итоговая стоимость: {final_price}**"
    )
    await update.message.reply_text(response_text)
    keyboard = [
        [
            InlineKeyboardButton("Новый расчёт", callback_data="new_calc"),
            InlineKeyboardButton("Сделать заказ", callback_data="make_order"),
        ]
    ]
    await update.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))
    return AFTER_CALC

async def after_calc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "new_calc":
        context.user_data["basket"] = []
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=open("category.jpg", "rb"),
            caption="Добро пожаловать! Пожалуйста, выберите категорию:",
            reply_markup=get_categories_inline_keyboard(),
        )
        return CHOOSING_CATEGORY
    elif query.data == "make_order":
        if query.message.photo:
            await query.edit_message_caption(
                caption="Укажите название заказа.\n(Например: Кроссовки Nike Air Max 96, 44 размер, жёлто-белые)"
            )
        else:
            await query.edit_message_text(
                "Укажите название заказа.\n(Например: Кроссовки Nike Air Max 96, 44 размер, жёлто-белые)"
            )
        return ORDER_NAME

async def order_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    order_name = update.message.text.strip()
    context.user_data["order"]["order_name"] = order_name
    try:
        with open("link.jpg", "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption="Что покупаем?\nУкажите ссылку на товар с сайта Poizon 🔗",
            )
    except Exception as e:
        logger.error("Ошибка при отправке link.jpg: %s", e)
        await update.message.reply_text("Что покупаем? Укажите ссылку на товар с сайта Poizon 🔗")
    return ORDER_LINK

async def order_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text_received = update.message.text.strip()
    match = re.search(r"(https?://\S*dw4\.co\S*)", text_received)
    extracted_link = match.group(0) if match else text_received
    context.user_data["order"]["order_link"] = extracted_link
    try:
        with open("screenorder.jpg", "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption="Отправьте скриншот, на котором будет видно: Товар, размер, цвет",
            )
    except Exception as e:
        logger.error("Ошибка при отправке screenorder.jpg: %s", e)
        await update.message.reply_text("Отправьте скриншот, на котором будет видно: Товар, размер, цвет")
    return ORDER_SCREENSHOT

async def order_screenshot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo_file_id = update.message.photo[-1].file_id
    context.user_data["order"]["screenshot"] = photo_file_id
    order = context.user_data.get("order")
    if order:
        basket = context.user_data.get("basket", [])
        basket.append(order)
        context.user_data["basket"] = basket
        final_text = (
            f"Название: {order.get('order_name')}\n"
            f"Итоговая стоимость: {order.get('final_price')}\n"
            f"Ссылка: {order.get('order_link')}\n"
            f"Статус: {order.get('status')}"
        )
        keyboard = [
            [
                InlineKeyboardButton("Добавить товар", callback_data="add_product"),
                InlineKeyboardButton("Завершить оформление заказа", callback_data="finish_order"),
            ]
        ]
        await update.message.reply_photo(
            photo=photo_file_id,
            caption=final_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.message.reply_text("Ошибка: данные заказа отсутствуют.")
    return FINISH_ORDER

async def order_finalization_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    logger.info("Order finalization callback triggered with data: %s", query.data)
    if query.data == "add_product":
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=open("category.jpg", "rb"),
            caption="Добро пожаловать! Пожалуйста, выберите категорию:",
            reply_markup=get_categories_inline_keyboard(),
        )
        return CHOOSING_CATEGORY
    elif query.data == "finish_order":
        basket = context.user_data.get("basket", [])
        if not basket:
            await query.edit_message_text("Корзина пуста.")
            return ConversationHandler.END
        global GLOBAL_ORDER_NUMBER
        for index, item in enumerate(basket):
            item["order_id"] = f"{GLOBAL_ORDER_NUMBER}-{index+1}"
            orders.append(item)
        GLOBAL_ORDER_NUMBER += 1
        total_cost = sum(item.get("final_price", 0) for item in basket)
        details = "Ваш заказ:\n"
        for item in basket:
            details += (
                f"ID: {item.get('order_id')}. {item.get('order_name')} – {item.get('final_price')}\n"
                f"Ссылка: {item.get('order_link')}\n"
            )
        details += f"\nОбщая стоимость: {total_cost}"
        prompt_text = "\n\nЕсли у вас есть промокод или реферальный код, введите его.\nЕсли нет, введите 'Нет'."
        full_text = details + prompt_text
        if query.message.text:
            await query.edit_message_text(full_text)
        else:
            await context.bot.send_message(chat_id=query.message.chat_id, text=full_text)
        return PROMO_INPUT

async def promo_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    promo_input = update.message.text.strip()
    order = context.user_data.get("order")
    discount = 300
    if promo_input.lower() == "нет":
        final_price = order.get("final_price")
    else:
        valid = False
        if promo_input in promo_codes:
            data = promo_codes[promo_input]
            if data["type"] == "one-time" and update.effective_user.id in data["used_by"]:
                valid = False
            else:
                valid = True
                data["used_by"].add(update.effective_user.id)
        if not valid:
            if promo_input in referral_codes.values():
                # Начисляем бонус рефереру
                for uid, ref_code in referral_codes.items():
                    if ref_code == promo_input:
                        referral_bonus[uid] = referral_bonus.get(uid, 0) + discount
                        valid = True
                        break
        if valid:
            final_price = max(order.get("final_price") - discount, 0)
            order["discount"] = discount
            order["promo_code_used"] = promo_input
            await update.message.reply_text(f"Код принят! Скидка {discount}₽ применена.")
        else:
            await update.message.reply_text("Введённый код недействителен. Скидка не применена.")
            final_price = order.get("final_price")
    order["final_price"] = final_price
    payment_text = (
        "Заказ проверен нашими менеджерами и готов к дальнейшему оформлению.\n\n"
        "Доставка по России оплачивается отдельно.\n"
        "Мы выкупаем товар в течение 72 часов после оплаты. Товар будет у нас примерно через 25 дней.\n\n"
        f"Итоговая стоимость с учетом скидки: {final_price}₽\n"
        "Для оплаты переведите указанную сумму на карту Альфа-Банк: 79955006566\n"
        "Внимательно проверяйте получателя!\n"
        "После оплаты отправьте фото квитанции."
    )
    keyboard = [
        [
            InlineKeyboardButton("Главное меню", callback_data="main_menu"),
            InlineKeyboardButton("Личный кабинет", callback_data="cabinet_menu"),
        ]
    ]
    await update.message.reply_text(payment_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ORDER_RECEIPT

async def order_receipt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    receipt_file_id = update.message.photo[-1].file_id
    basket = context.user_data.get("basket", [])
    if basket:
        basket[-1]["receipt"] = receipt_file_id
        order = basket[-1]
        order["status"] = "на_подтверждении"
        admin_text = (
            f"Заказ №{order.get('order_id')} перешёл в статус 'на_подтверждении'.\n"
            f"Пользователь: {order.get('username')} (ID: {order.get('user_id')})\n"
            f"Название: {order.get('order_name')}\n"
            f"Ссылка: {order.get('order_link')}\n"
            f"Итог: {order.get('final_price')}\n"
            f"Квитанция: получена"
        )
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=receipt_file_id,
                caption=admin_text,
            )
        except Exception as e:
            logger.error("Ошибка уведомления админа о квитанции: %s", e)
        await update.message.reply_text("Квитанция получена. Ваш заказ передан в обработку!")
    else:
        await update.message.reply_text("Ошибка: заказ не найден.")
    return ConversationHandler.END

async def payment_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Пожалуйста, отправьте фото квитанции об оплате.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Операция отменена. Для нового расчёта введите /start.")
    return ConversationHandler.END

# ================= Команды для личного кабинета и реферальной программы =================

async def personal_cabinet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_orders = [o for o in orders if o.get("user_id") == user_id]
    total_sum = sum(o.get("final_price", 0) for o in user_orders)
    promo_info = ""
    if user_id in promo_codes:
        promo_info = f"Ваш промокод для следующего заказа: {promo_codes[user_id]}"
    else:
        promo_info = "Промокод появится после доставки первого заказа."
    bonus = referral_bonus.get(user_id, 0)
    text = (
        f"Личный кабинет:\n\n"
        f"История заказов: {len(user_orders)}\n"
        f"Общая сумма заказов: {total_sum}\n"
        f"Ваш бонус: {bonus}₽\n\n"
        f"{promo_info}\n\n"
        "Выберите пункт:"
    )
    keyboard = [
        [InlineKeyboardButton("История заказов", callback_data="cabinet_history")],
        [InlineKeyboardButton("Отслеживание заказов", callback_data="user_orders")],
        [InlineKeyboardButton("Реферальная программа", callback_data="referral_program")],
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# Функция user_orders_callback определена ниже, чтобы не возникало NameError
async def user_orders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.message.chat_id
    user_orders = [o for o in orders if o.get("user_id") == user_id]
    if not user_orders:
        await query.edit_message_text("У вас пока нет заказов.")
        return
    text = "Ваши заказы:\n"
    for o in user_orders:
        text += f"ID: {o.get('order_id')}, {o.get('order_name')} — {o.get('status')}\n"
    await query.edit_message_text(text)

async def referral_program_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in referral_codes:
        referral_codes[user_id] = generate_random_code()
    referral_link = f"t.me/7883376612:AAElSoIAd02N7lFASiDDuw1OeM9NPyhEXz4?start={referral_codes[user_id]}"
    text = (
        "Реферальная программа:\n\n"
        "Приглашайте друзей и получите скидку 300₽ на первый заказ!\n"
        "Ваш реферальная ссылка:\n"
        f"{referral_link}\n\n"
        "Если ваш друг оформит заказ по этой ссылке и его заказ будет доставлен, вы получите 300₽ на следующий заказ.\n"
        "Повторное использование кода недопустимо."
    )
    await update.callback_query.edit_message_text(text)

async def calculate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Свяжитесь с нашим менеджером: t.me/blvck_td")

# ================= Команды для администратора: промокоды =================

async def addpromo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Используйте: /addpromo <код> <тип: one-time/multi> <скидка>")
        return
    code = args[0]
    promo_type = args[1]
    try:
        discount = int(args[2])
    except ValueError:
        await update.message.reply_text("Скидка должна быть числом.")
        return
    promo_codes[code] = {"type": promo_type, "discount": discount, "used_by": set()}
    await update.message.reply_text(f"Промокод {code} ({promo_type}, скидка {discount}₽) добавлен.")

async def listpromos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    if not promo_codes:
        await update.message.reply_text("Нет активных промокодов.")
        return
    text = "Активные промокоды:\n"
    for code, data in promo_codes.items():
        text += f"{code} – тип: {data['type']}, скидка: {data['discount']}₽, использован: {len(data['used_by'])} раз(а)\n"
    await update.message.reply_text(text)

# ================= Административный интерфейс =================

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Новые заказы (создан)", callback_data="admin_status_создан")],
        [InlineKeyboardButton("Оплаченные заказы", callback_data="admin_status_оплачен")],
        [InlineKeyboardButton("Заказы на подтверждении", callback_data="admin_status_на_подтверждении")],
        [InlineKeyboardButton("Заказы в работе", callback_data="admin_status_в_работе")],
        [InlineKeyboardButton("Завершённые заказы (доставлен)", callback_data="admin_status_доставлен")],
        [InlineKeyboardButton("Аналитика", callback_data="admin_analytics")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    await update.message.reply_text("Админ-консоль:", reply_markup=get_admin_panel_keyboard())

async def admin_console_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("admin_status_"):
        status_filter = data.split("_", 2)[-1]
        if status_filter == "в_работе":
            filtered = [o for o in orders if o.get("status") in ["выкуплен", "ждет_отправки", "отправлен", "прибыл"]]
        else:
            filtered = [o for o in orders if o.get("status") == status_filter]
        if not filtered:
            await query.edit_message_text(f"Заказов со статусом '{status_filter}' не найдено.")
            return
        keyboard = []
        for o in filtered:
            keyboard.append([InlineKeyboardButton(f"{o.get('order_id')}: {o.get('order_name')}", callback_data=f"admin_order_{o.get('order_id')}")])
        await query.edit_message_text(f"Заказы со статусом '{status_filter}':", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "admin_analytics":
        paid_orders = [o for o in orders if o.get("status") in ["оплачен", "выкуплен", "отправлен", "доставлен"]]
        total_count = len(paid_orders)
        total_sum = sum(o.get("final_price", 0) for o in paid_orders)
        text = f"Оплаченные заказы: {total_count}\nОбщая сумма: {total_sum}"
        await query.edit_message_text(text)

async def orders_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    args = context.args
    if args:
        status_filter = args[0].lower()
        filtered = [o for o in orders if o.get("status", "").lower() == status_filter]
    else:
        filtered = orders
    if not filtered:
        await update.message.reply_text("Заказов не найдено по указанному статусу.")
        return
    text = "Список заказов:\n"
    for o in filtered:
        text += f"ID: {o.get('order_id')}, {o.get('order_name')} — {o.get('status')}\n"
    await update.message.reply_text(text)

async def order_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /order_details <order_id>")
        return
    order_id = args[0]
    order = next((o for o in orders if o.get("order_id") == order_id), None)
    if not order:
        await update.message.reply_text("Заказ не найден.")
        return
    details = (
        f"ID: {order.get('order_id')}\n"
        f"Пользователь: {order.get('username')} (ID: {order.get('user_id')})\n"
        f"Категория: {order.get('category')}\n"
        f"Цена: {order.get('price_yuan')}\n"
        f"Комиссия: {order.get('commission')}\n"
        f"Итог: {order.get('final_price')}\n"
        f"Название: {order.get('order_name')}\n"
        f"Ссылка: {order.get('order_link')}\n"
        f"Статус: {order.get('status')}\n"
        f"Дата: {order.get('created_at')}\n"
        f"Квитанция: {'Да' if order.get('receipt') else 'Нет'}"
    )
    keyboard = []
    row = []
    for status in STATUSES:
        row.append(InlineKeyboardButton(status, callback_data=f"update_{order.get('order_id')}_{status}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(details, reply_markup=reply_markup)

async def admin_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split("_", 2)
    if len(data) < 3:
        await query.edit_message_text("Неверный формат данных.")
        return
    order_id = data[2]
    order = next((o for o in orders if o.get("order_id") == order_id), None)
    if not order:
        await query.edit_message_text("Заказ не найден.")
        return
    details = (
        f"ID: {order.get('order_id')}\n"
        f"Пользователь: {order.get('username')} (ID: {order.get('user_id')})\n"
        f"Категория: {order.get('category')}\n"
        f"Цена: {order.get('price_yuan')}\n"
        f"Комиссия: {order.get('commission')}\n"
        f"Итог: {order.get('final_price')}\n"
        f"Название: {order.get('order_name')}\n"
        f"Ссылка: {order.get('order_link')}\n"
        f"Статус: {order.get('status')}\n"
        f"Дата: {order.get('created_at')}\n"
        f"Квитанция: {'Да' if order.get('receipt') else 'Нет'}"
    )
    keyboard = []
    row = []
    for status in STATUSES:
        row.append(InlineKeyboardButton(status, callback_data=f"update_{order.get('order_id')}_{status}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(details, reply_markup=reply_markup)

async def update_order_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split("_", 2)
    if len(data) < 3:
        await query.edit_message_text("Неверный формат данных.")
        return
    order_id = data[1]
    new_status = data[2]
    order = next((o for o in orders if o.get("order_id") == order_id), None)
    if not order:
        await query.edit_message_text("Заказ не найден.")
        return
    order["status"] = new_status
    notification = f"Ваш заказ №{order_id} обновлён. Новый статус: {new_status}."
    try:
        await context.bot.send_message(chat_id=order.get("user_id"), text=notification)
    except Exception as e:
        logger.error("Ошибка отправки уведомления: %s", e)
    details = (
        f"ID: {order.get('order_id')}\n"
        f"Пользователь: {order.get('username')} (ID: {order.get('user_id')})\n"
        f"Категория: {order.get('category')}\n"
        f"Цена: {order.get('price_yuan')}\n"
        f"Комиссия: {order.get('commission')}\n"
        f"Итог: {order.get('final_price')}\n"
        f"Название: {order.get('order_name')}\n"
        f"Ссылка: {order.get('order_link')}\n"
        f"Статус: {order.get('status')}\n"
        f"Дата: {order.get('created_at')}\n"
        f"Квитанция: {'Да' if order.get('receipt') else 'Нет'}"
    )
    keyboard = []
    row = []
    for status in STATUSES:
        row.append(InlineKeyboardButton(status, callback_data=f"update_{order.get('order_id')}_{status}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(details, reply_markup=reply_markup)

async def payment_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Пожалуйста, отправьте фото квитанции об оплате.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Операция отменена. Для нового расчёта введите /start.")
    return ConversationHandler.END

# ================= Команды для личного кабинета и реферальной программы =================

async def calculate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Свяжитесь с нашим менеджером: t.me/blvck_td")

# ================= Команды для администратора: промокоды =================

async def addpromo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Используйте: /addpromo <код> <тип: one-time/multi> <скидка>")
        return
    code = args[0]
    promo_type = args[1]
    try:
        discount = int(args[2])
    except ValueError:
        await update.message.reply_text("Скидка должна быть числом.")
        return
    promo_codes[code] = {"type": promo_type, "discount": discount, "used_by": set()}
    await update.message.reply_text(f"Промокод {code} ({promo_type}, скидка {discount}₽) добавлен.")

async def listpromos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    if not promo_codes:
        await update.message.reply_text("Нет активных промокодов.")
        return
    text = "Активные промокоды:\n"
    for code, data in promo_codes.items():
        text += f"{code} – тип: {data['type']}, скидка: {data['discount']}₽, использован: {len(data['used_by'])} раз(а)\n"
    await update.message.reply_text(text)

# ================= Административный интерфейс =================

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Новые заказы (создан)", callback_data="admin_status_создан")],
        [InlineKeyboardButton("Оплаченные заказы", callback_data="admin_status_оплачен")],
        [InlineKeyboardButton("Заказы на подтверждении", callback_data="admin_status_на_подтверждении")],
        [InlineKeyboardButton("Заказы в работе", callback_data="admin_status_в_работе")],
        [InlineKeyboardButton("Завершённые заказы (доставлен)", callback_data="admin_status_доставлен")],
        [InlineKeyboardButton("Аналитика", callback_data="admin_analytics")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    await update.message.reply_text("Админ-консоль:", reply_markup=get_admin_panel_keyboard())

async def admin_console_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("admin_status_"):
        status_filter = data.split("_", 2)[-1]
        if status_filter == "в_работе":
            filtered = [o for o in orders if o.get("status") in ["выкуплен", "ждет_отправки", "отправлен", "прибыл"]]
        else:
            filtered = [o for o in orders if o.get("status") == status_filter]
        if not filtered:
            await query.edit_message_text(f"Заказов со статусом '{status_filter}' не найдено.")
            return
        keyboard = []
        for o in filtered:
            keyboard.append([InlineKeyboardButton(f"{o.get('order_id')}: {o.get('order_name')}", callback_data=f"admin_order_{o.get('order_id')}")])
        await query.edit_message_text(f"Заказы со статусом '{status_filter}':", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "admin_analytics":
        paid_orders = [o for o in orders if o.get("status") in ["оплачен", "выкуплен", "отправлен", "доставлен"]]
        total_count = len(paid_orders)
        total_sum = sum(o.get("final_price", 0) for o in paid_orders)
        text = f"Оплаченные заказы: {total_count}\nОбщая сумма: {total_sum}"
        await query.edit_message_text(text)

async def orders_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    args = context.args
    if args:
        status_filter = args[0].lower()
        filtered = [o for o in orders if o.get("status", "").lower() == status_filter]
    else:
        filtered = orders
    if not filtered:
        await update.message.reply_text("Заказов не найдено по указанному статусу.")
        return
    text = "Список заказов:\n"
    for o in filtered:
        text += f"ID: {o.get('order_id')}, {o.get('order_name')} — {o.get('status')}\n"
    await update.message.reply_text(text)

async def order_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /order_details <order_id>")
        return
    order_id = args[0]
    order = next((o for o in orders if o.get("order_id") == order_id), None)
    if not order:
        await update.message.reply_text("Заказ не найден.")
        return
    details = (
        f"ID: {order.get('order_id')}\n"
        f"Пользователь: {order.get('username')} (ID: {order.get('user_id')})\n"
        f"Категория: {order.get('category')}\n"
        f"Цена: {order.get('price_yuan')}\n"
        f"Комиссия: {order.get('commission')}\n"
        f"Итог: {order.get('final_price')}\n"
        f"Название: {order.get('order_name')}\n"
        f"Ссылка: {order.get('order_link')}\n"
        f"Статус: {order.get('status')}\n"
        f"Дата: {order.get('created_at')}\n"
        f"Квитанция: {'Да' if order.get('receipt') else 'Нет'}"
    )
    keyboard = []
    row = []
    for status in STATUSES:
        row.append(InlineKeyboardButton(status, callback_data=f"update_{order.get('order_id')}_{status}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(details, reply_markup=reply_markup)

async def admin_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split("_", 2)
    if len(data) < 3:
        await query.edit_message_text("Неверный формат данных.")
        return
    order_id = data[2]
    order = next((o for o in orders if o.get("order_id") == order_id), None)
    if not order:
        await query.edit_message_text("Заказ не найден.")
        return
    details = (
        f"ID: {order.get('order_id')}\n"
        f"Пользователь: {order.get('username')} (ID: {order.get('user_id')})\n"
        f"Категория: {order.get('category')}\n"
        f"Цена: {order.get('price_yuan')}\n"
        f"Комиссия: {order.get('commission')}\n"
        f"Итог: {order.get('final_price')}\n"
        f"Название: {order.get('order_name')}\n"
        f"Ссылка: {order.get('order_link')}\n"
        f"Статус: {order.get('status')}\n"
        f"Дата: {order.get('created_at')}\n"
        f"Квитанция: {'Да' if order.get('receipt') else 'Нет'}"
    )
    keyboard = []
    row = []
    for status in STATUSES:
        row.append(InlineKeyboardButton(status, callback_data=f"update_{order.get('order_id')}_{status}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(details, reply_markup=reply_markup)

async def update_order_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split("_", 2)
    if len(data) < 3:
        await query.edit_message_text("Неверный формат данных.")
        return
    order_id = data[1]
    new_status = data[2]
    order = next((o for o in orders if o.get("order_id") == order_id), None)
    if not order:
        await query.edit_message_text("Заказ не найден.")
        return
    order["status"] = new_status
    notification = f"Ваш заказ №{order_id} обновлён. Новый статус: {new_status}."
    try:
        await context.bot.send_message(chat_id=order.get("user_id"), text=notification)
    except Exception as e:
        logger.error("Ошибка отправки уведомления: %s", e)
    details = (
        f"ID: {order.get('order_id')}\n"
        f"Пользователь: {order.get('username')} (ID: {order.get('user_id')})\n"
        f"Категория: {order.get('category')}\n"
        f"Цена: {order.get('price_yuan')}\n"
        f"Комиссия: {order.get('commission')}\n"
        f"Итог: {order.get('final_price')}\n"
        f"Название: {order.get('order_name')}\n"
        f"Ссылка: {order.get('order_link')}\n"
        f"Статус: {order.get('status')}\n"
        f"Дата: {order.get('created_at')}\n"
        f"Квитанция: {'Да' if order.get('receipt') else 'Нет'}"
    )
    keyboard = []
    row = []
    for status in STATUSES:
        row.append(InlineKeyboardButton(status, callback_data=f"update_{order.get('order_id')}_{status}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(details, reply_markup=reply_markup)

async def payment_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Пожалуйста, отправьте фото квитанции об оплате.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Операция отменена. Для нового расчёта введите /start.")
    return ConversationHandler.END

# ================= Команды для личного кабинета и реферальной программы =================

async def calculate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Свяжитесь с нашим менеджером: t.me/blvck_td")

# ================= Команды для администратора: промокоды =================

async def addpromo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Используйте: /addpromo <код> <тип: one-time/multi> <скидка>")
        return
    code = args[0]
    promo_type = args[1]
    try:
        discount = int(args[2])
    except ValueError:
        await update.message.reply_text("Скидка должна быть числом.")
        return
    promo_codes[code] = {"type": promo_type, "discount": discount, "used_by": set()}
    await update.message.reply_text(f"Промокод {code} ({promo_type}, скидка {discount}₽) добавлен.")

async def listpromos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    if not promo_codes:
        await update.message.reply_text("Нет активных промокодов.")
        return
    text = "Активные промокоды:\n"
    for code, data in promo_codes.items():
        text += f"{code} – тип: {data['type']}, скидка: {data['discount']}₽, использован: {len(data['used_by'])} раз(а)\n"
    await update.message.reply_text(text)

# ================= Основной запуск =================

def main():
    global GLOBAL_ORDER_NUMBER
    GLOBAL_ORDER_NUMBER = 1

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_CATEGORY: [CallbackQueryHandler(category_chosen)],
            GETTING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, calculate_price)],
            AFTER_CALC: [CallbackQueryHandler(after_calc, pattern="^(new_calc|make_order)$")],
            ORDER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_name_handler)],
            ORDER_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_link_handler)],
            ORDER_SCREENSHOT: [MessageHandler(filters.PHOTO, order_screenshot_handler)],
            FINISH_ORDER: [CallbackQueryHandler(order_finalization_callback, pattern="^(add_product|finish_order)$")],
            PROMO_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_input_handler)],
            ORDER_RECEIPT: [MessageHandler(filters.PHOTO, order_receipt_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Пользовательские команды
    application.add_handler(CommandHandler("menu", menu_handler))
    application.add_handler(CommandHandler("cabinet", personal_cabinet_handler))
    application.add_handler(CommandHandler("calculate", calculate_handler))
    application.add_handler(CommandHandler("support", support_handler))
    
    # Команды для администратора
    application.add_handler(CommandHandler("admin", admin_panel_handler))
    application.add_handler(CommandHandler("orders_status", orders_status_handler))
    application.add_handler(CommandHandler("order_details", order_details_handler))
    application.add_handler(CommandHandler("analytics", lambda update, context: update.message.reply_text("Аналитика...")))
    application.add_handler(CommandHandler("support", lambda update, context: update.message.reply_text("support@example.com")))
    # Команды для промокодов
    application.add_handler(CommandHandler("addpromo", addpromo_handler))
    application.add_handler(CommandHandler("listpromos", listpromos_handler))
    
    # CallbackQueryHandler для админ-консоли и заказов
    application.add_handler(CallbackQueryHandler(admin_console_callback, pattern=r"^admin_status_.*|^admin_analytics$"))
    application.add_handler(CallbackQueryHandler(update_order_status_callback, pattern=r"^update_\S+_.+"))
    application.add_handler(CallbackQueryHandler(payment_confirmation_callback, pattern=r"^confirm_payment$"))
    application.add_handler(CallbackQueryHandler(admin_order_callback, pattern=r"^admin_order_\S+$"))
    application.add_handler(CallbackQueryHandler(user_orders_callback, pattern=r"^user_orders$"))
    
    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()
