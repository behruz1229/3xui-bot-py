#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import urllib.parse
import threading
import time
import os
import sys
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ParseMode, Message
)
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, CallbackContext,
    ConversationHandler, MessageHandler, Filters
)
import config
from xui_api import XUI_API

# --- Watchdog ---
last_update_time = time.time()
UPDATE_TIMEOUT = 600

def touch_handler(update: Update, context: CallbackContext):
    global last_update_time
    logger.info(f"Получено обновление: {update.update_id}")
    last_update_time = time.time()

def watchdog_check():
    global last_update_time
    while True:
        time.sleep(60)
        if time.time() - last_update_time > UPDATE_TIMEOUT:
            logging.error(f"Watchdog: нет обновлений более {UPDATE_TIMEOUT} секунд. Завершаем процесс.")
            os._exit(1)

# Глобальный словарь для хранения состояний редактирования
# Ключ: chat_id, значение: {'type': 'limit' или 'expiry', 'inbound_id': ..., 'client_id': ...}
edit_states = {}

api = XUI_API()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def restricted(func):
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != config.AUTHORIZED_USER_ID:
            if update.message:
                update.message.reply_text("⛔ Доступ запрещён.")
            elif update.callback_query:
                update.callback_query.answer("⛔ Доступ запрещён", show_alert=True)
            return
        return func(update, context, *args, **kwargs)
    return wrapped

def show_main_menu(message: Message, context: CallbackContext):
    keyboard = [
        [KeyboardButton("➕ Создание клиента")],
        [KeyboardButton("📋 Список пользователей")],
        [KeyboardButton("ℹ️ Информация о сервере")],
        [KeyboardButton("❓ Помощь")]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите действие"
    )
    message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=reply_markup
    )

@restricted
def start(update: Update, context: CallbackContext):
    show_main_menu(update.message, context)

def generate_vless_link(client_id, email, server_ip, port, inbound_settings, protocol_type="tcp"):
    security = "reality"
    encryption = "none"
    
    reality = inbound_settings.get("realitySettings", {})
    settings = reality.get("settings", {})
    pbk = settings.get("publicKey", "")
    fp = settings.get("fingerprint", "chrome")
    sni = reality.get("serverNames", [""])[0] if reality.get("serverNames") else server_ip
    short_ids = reality.get("shortIds", [])
    sid = short_ids[0] if short_ids else ""
    spiderX = settings.get("spiderX", "")
    pqv = settings.get("mldsa65Verify", "")
    spx = urllib.parse.quote(spiderX, safe='') if spiderX else ""
    
    params = f"encryption={encryption}&security={security}&pbk={pbk}&fp={fp}&sni={sni}"
    if sid:
        params += f"&sid={sid}"
    if spx:
        params += f"&spx={spx}"
    if pqv:
        params += f"&pqv={pqv}"
    
    if protocol_type == "grpc":
        grpc_settings = inbound_settings.get("grpcSettings", {})
        service_name = grpc_settings.get("serviceName", "")
        grpc_mode = grpc_settings.get("mode", "multi")
        authority = grpc_settings.get("authority", "")
        params = f"type=grpc&{params}"
        if service_name:
            params += f"&serviceName={service_name}"
        if grpc_mode:
            params += f"&mode={grpc_mode}"
        if authority:
            params += f"&authority={authority}"
        prefix = "grpc-"
    else:
        params = f"type=tcp&{params}"
        prefix = "tcp-"
    
    params += f"#{prefix}{email}"
    return f"vless://{client_id}@{server_ip}:{port}?{params}"

def get_inbound_port(inbound_id):
    inbounds = api.get_inbounds()
    if not inbounds:
        return None
    for inbound in inbounds:
        if inbound.get("id") == inbound_id:
            return inbound.get("port")
    return None

@restricted
def handle_other_buttons(update: Update, context: CallbackContext):
    text = update.message.text
    if text == "📋 Список пользователей":
        show_clients_list(update, context)
    elif text == "ℹ️ Информация о сервере":
        server_info(update, context)
    elif text == "❓ Помощь":
        help_text = (
            "Ссылка для (v2box) 🤖 https://goo.su/L0HcC8l \n"
            "\n"
            "Ссылка для (incy) 🤖 https://goo.su/6XjkbR \n"
            "\n"
            "Ссылка для (incy) 🍏 https://goo.su/eQe99mV \n"
            "\n"
            "Ссылка для (XRayClient) 🍏 https://goo.su/butr4n \n"
            "\n"
            "Ссылка для (Alice Ray) 🍏 https://goo.su/jCFdHZ \n"
            "\n"
            "Ссылка для (sing-box VT) 🍏 https://goo.su/QtoKjyG \n"
        )
        update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    else:
        pass

def show_clients_list(update: Update, context: CallbackContext):
    all_clients = api.get_clients_from_all_inbounds()
    if all_clients is None:
        update.message.reply_text("❌ Ошибка получения списка клиентов.")
        return
    if not all_clients:
        update.message.reply_text("📭 Список клиентов пуст.")
        return

    all_clients.sort(key=lambda x: (x.get("inbound_id", 0), x.get("email", "")))
    online_emails = api.get_online_users()
    
    text = "📋 **Список клиентов:**"
    keyboard = []
    for client in all_clients:
        email = client.get('email', 'no-email')
        cid = client.get('id', '')
        inbound_id = client.get("inbound_id")
        inbound_remark = client.get("inbound_remark", str(inbound_id))
        status_icon = "🟢" if email in online_emails else "🔴"
        keyboard.append([
            InlineKeyboardButton(f"{status_icon} {email} ({inbound_remark})", callback_data=f'info_{inbound_id}_{cid}'),
            InlineKeyboardButton(f"🗑 Удалить", callback_data=f'delete_{inbound_id}_{cid}')
        ])
    keyboard.append([InlineKeyboardButton("🔙 Главное меню", callback_data='back_main')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

def server_info(update: Update, context: CallbackContext):
    info = (
        "ℹ️ **Информация о сервере**\n\n"
        f"Панель: {config.PANEL_URL}\n"
        "Доступные inbound'ы:\n"
    )
    for inbound in config.INBOUNDS:
        info += f"- {inbound['remark']} (id {inbound['id']})\n"
    keyboard = [
        [InlineKeyboardButton("🔄 Перезапустить Xray", callback_data='restart_xray')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='back_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(info, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

@restricted
def inline_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data

    if data == 'back_main':
        query.delete_message()
        show_main_menu(query.message, context)
        return

    if data == 'restart_xray':
        success, msg = api.restart_xray()
        query.edit_message_text(f"{'✅' if success else '❌'} {msg}")
        return

    if data.startswith('info_'):
        parts = data.split('_')
        if len(parts) < 3:
            query.edit_message_text("❌ Ошибка формата данных.")
            return
        inbound_id = int(parts[1])
        client_id = parts[2]
        
        port = get_inbound_port(inbound_id)
        if not port:
            query.edit_message_text("❌ Не удалось определить порт inbound.")
            return
        
        inbound_settings = api.get_inbound_settings(inbound_id)
        if not inbound_settings:
            query.edit_message_text("❌ Ошибка получения настроек inbound.")
            return
        
        clients = api.get_clients_from_inbound(inbound_id)
        if not clients:
            query.edit_message_text("❌ Клиент не найден.")
            return
        client = next((c for c in clients if c.get('id') == client_id), None)
        if not client:
            query.edit_message_text("❌ Клиент не найден.")
            return
        
        email = client.get('email', 'N/A')
        total_gb = client.get('totalGB', 0) / (1024**3)
        expiry = client.get('expiryTime', 0)
        expiry_date = datetime.fromtimestamp(expiry/1000).strftime('%Y-%m-%d') if expiry > 0 else "бессрочно"
        enable = "Да" if client.get('enable', False) else "Нет"
        
        traffic_info = ""
        try:
            td = api.get_client_traffic(email)
            if td:
                up = td.get('up', 0) / (1024**3)
                down = td.get('down', 0) / (1024**3)
                traffic_info = f"📊 **Использовано:** {up+down:.2f} GB (↑{up:.2f} ↓{down:.2f})\n"
            else:
                traffic_info = "📊 **Использовано:** недоступно\n"
        except Exception as e:
            logger.error(f"Ошибка трафика {email}: {e}")
            traffic_info = "📊 **Использовано:** ошибка\n"
        
        protocol_type = "grpc" if inbound_settings.get("grpcSettings") else "tcp"
        link = generate_vless_link(client_id, email, config.SERVER_IP, port, inbound_settings, protocol_type)
        
        info_text = (
            f"📧 **Email:** {email}\n"
            f"{traffic_info}"
            f"📦 **Лимит:** {total_gb:.2f} GB\n"
            f"📅 **Истекает:** {expiry_date}\n"
            f"✅ **Активен:** {enable}\n"
            f"🔌 **Inbound:** {inbound_id}"
        )
        kb = [
            [InlineKeyboardButton("📋 Копировать ссылку", callback_data=f'copy_{inbound_id}_{client_id}')],
            [InlineKeyboardButton("📦 Изменить лимит (GB)", callback_data=f'edit_limit_{inbound_id}_{client_id}')],
            [InlineKeyboardButton("📅 Изменить срок (дни)", callback_data=f'edit_expiry_{inbound_id}_{client_id}')],
            [InlineKeyboardButton("🔄 Сбросить трафик", callback_data=f'reset_traffic_{inbound_id}_{email}')],
            [InlineKeyboardButton("🔙 Назад", callback_data='list_back')]
        ]
        query.edit_message_text(info_text, parse_mode=ParseMode.MARKDOWN,
                                reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith('copy_'):
        parts = data.split('_')
        if len(parts) < 3:
            query.answer("❌ Ошибка формата", show_alert=True)
            return
        inbound_id = int(parts[1])
        client_id = parts[2]
        
        port = get_inbound_port(inbound_id)
        if not port:
            query.answer("❌ Не удалось определить порт", show_alert=True)
            return
        
        inbound_settings = api.get_inbound_settings(inbound_id)
        if not inbound_settings:
            query.answer("❌ Ошибка настроек", show_alert=True)
            return
        clients = api.get_clients_from_inbound(inbound_id)
        if not clients:
            query.answer("❌ Клиент не найден", show_alert=True)
            return
        client = next((c for c in clients if c.get('id') == client_id), None)
        if not client:
            query.answer("❌ Клиент не найден", show_alert=True)
            return
        email = client.get('email', '')
        protocol_type = "grpc" if inbound_settings.get("grpcSettings") else "tcp"
        link = generate_vless_link(client_id, email, config.SERVER_IP, port, inbound_settings, protocol_type)
        query.message.reply_text(f"```\n{link}\n```", parse_mode=ParseMode.MARKDOWN)
        query.answer("✅ Ссылка отправлена", show_alert=False)
        return

    if data.startswith('edit_limit_'):
        parts = data.split('_')
        if len(parts) < 3:
            query.answer("❌ Ошибка формата", show_alert=True)
            return
        inbound_id = int(parts[2])
        client_id = parts[3]
        chat_id = update.effective_chat.id
        edit_states[chat_id] = {'type': 'limit', 'inbound_id': inbound_id, 'client_id': client_id}
        query.edit_message_text("Введите новый лимит трафика в GB (целое число, 0 - безлимит):")
        return

    if data.startswith('edit_expiry_'):
        parts = data.split('_')
        if len(parts) < 3:
            query.answer("❌ Ошибка формата", show_alert=True)
            return
        inbound_id = int(parts[2])
        client_id = parts[3]
        chat_id = update.effective_chat.id
        edit_states[chat_id] = {'type': 'expiry', 'inbound_id': inbound_id, 'client_id': client_id}
        query.edit_message_text("Введите новый срок действия в днях (целое число, 0 - бессрочно):")
        return

    if data.startswith('reset_traffic_'):
        parts = data.split('_')
        if len(parts) < 3:
            query.answer("❌ Ошибка формата", show_alert=True)
            return
        inbound_id = int(parts[2])
        email = parts[3]
        success, msg = api.reset_client_traffic(inbound_id, email)
        query.answer(msg, show_alert=True)
        if success:
            query.edit_message_text(f"✅ {msg}\n\nНажмите кнопку Назад и откройте карточку снова для обновления статистики.")
        else:
            query.edit_message_text(f"❌ {msg}")
        return

    if data.startswith('delete_'):
        parts = data.split('_')
        if len(parts) < 3:
            query.edit_message_text("❌ Ошибка формата.")
            return
        inbound_id = int(parts[1])
        client_id = parts[2]
        kb = [
            [InlineKeyboardButton("✅ Да", callback_data=f'confirm_{inbound_id}_{client_id}')],
            [InlineKeyboardButton("❌ Нет", callback_data='list_back')]
        ]
        query.edit_message_text("⚠️ Удалить клиента?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith('confirm_'):
        parts = data.split('_')
        if len(parts) < 3:
            query.edit_message_text("❌ Ошибка формата.")
            return
        inbound_id = int(parts[1])
        client_id = parts[2]
        success, msg = api.delete_client(inbound_id, client_id)
        if success:
            query.edit_message_text(f"✅ {msg}", reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 К списку", callback_data='list_back')
            ]]))
        else:
            query.edit_message_text(f"❌ {msg}", reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data='list_back')
            ]]))
        return

    if data == 'list_back':
        all_clients = api.get_clients_from_all_inbounds()
        if not all_clients:
            query.edit_message_text("📭 Список пуст.")
            return
        all_clients.sort(key=lambda x: (x.get("inbound_id", 0), x.get("email", "")))
        online_emails = api.get_online_users()
        text = "📋 **Список клиентов:**"
        kb = []
        for client in all_clients:
            email = client.get('email', 'no-email')
            cid = client.get('id', '')
            inbound_id = client.get("inbound_id")
            inbound_remark = client.get("inbound_remark", str(inbound_id))
            status_icon = "🟢" if email in online_emails else "🔴"
            kb.append([
                InlineKeyboardButton(f"{status_icon} {email} ({inbound_remark})", callback_data=f'info_{inbound_id}_{cid}'),
                InlineKeyboardButton(f"🗑 Удалить", callback_data=f'delete_{inbound_id}_{cid}')
            ])
        kb.append([InlineKeyboardButton("🔙 Главное меню", callback_data='back_main')])
        query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                reply_markup=InlineKeyboardMarkup(kb))
        return

# --- Обработчик текстовых сообщений (для редактирования) ---
@restricted
def handle_text_input(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if chat_id in edit_states:
        state = edit_states[chat_id]
        try:
            value = int(update.message.text)
            if value < 0:
                raise ValueError
        except ValueError:
            update.message.reply_text("❌ Введите целое число >= 0.")
            return
        inbound_id = state['inbound_id']
        client_id = state['client_id']
        if state['type'] == 'limit':
            success, msg = api.update_client(inbound_id, client_id, new_total_gb=value)
        elif state['type'] == 'expiry':
            success, msg = api.update_client(inbound_id, client_id, new_expiry_days=value)
        else:
            update.message.reply_text("❌ Неизвестный тип операции.")
            return
        update.message.reply_text(f"{'✅' if success else '❌'} {msg}")
        # Удаляем состояние
        del edit_states[chat_id]
        # Возвращаем главное меню
        start(update, context)
    else:
        # Если нет активного редактирования, игнорируем текст
        pass

# --- Диалог создания клиента (ConversationHandler) ---
SELECT_INBOUND, NAME = range(2)

@restricted
def create_start(update: Update, context: CallbackContext):
    keyboard = []
    for inbound in config.INBOUNDS:
        keyboard.append([InlineKeyboardButton(inbound["remark"], callback_data=f"inbound_{inbound['id']}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выберите inbound для нового клиента:", reply_markup=reply_markup)
    return SELECT_INBOUND

@restricted
def select_inbound(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("inbound_"):
        inbound_id = int(data.split("_")[1])
        context.user_data['inbound_id'] = inbound_id
        query.edit_message_text("Введите имя клиента (email):")
        return NAME
    else:
        query.edit_message_text("Пожалуйста, выберите inbound из кнопок.")
        return SELECT_INBOUND

@restricted
def create_name(update: Update, context: CallbackContext):
    name = update.message.text
    inbound_id = context.user_data.get('inbound_id')
    if not inbound_id:
        update.message.reply_text("❌ Ошибка: inbound не выбран. Начните заново.")
        start(update, context)
        return ConversationHandler.END
    success, msg = api.add_client(inbound_id, name, 0, 0)
    if success:
        update.message.reply_text(f"✅ {msg}", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text(f"❌ {msg}")
    context.user_data.clear()
    start(update, context)
    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Операция отменена.")
    context.user_data.clear()
    start(update, context)
    return ConversationHandler.END

# --- Основная функция ---
def main():
    if not api.login():
        logger.error("Не удалось войти в панель. Проверьте настройки.")
        return

    updater = Updater(config.TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(MessageHandler(Filters.all, touch_handler), group=-1)
    dp.add_handler(CallbackQueryHandler(touch_handler), group=-1)

    dp.add_handler(CommandHandler("start", start))

    # Диалог создания клиента
    conv_create = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex('^➕ Создание клиента$'), create_start)],
        states={
            SELECT_INBOUND: [CallbackQueryHandler(select_inbound, pattern='^inbound_')],
            NAME: [MessageHandler(Filters.text & ~Filters.command, create_name)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    dp.add_handler(conv_create)

    # Обработчик обычных кнопок
    dp.add_handler(MessageHandler(
        Filters.regex('^(📋 Список пользователей|ℹ️ Информация о сервере|❓ Помощь)$'),
        handle_other_buttons
    ))

    # Обработчик инлайн-кнопок (все)
    dp.add_handler(CallbackQueryHandler(inline_handler))

    # Обработчик текстовых сообщений (для редактирования)
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_input))

    watchdog_thread = threading.Thread(target=watchdog_check, daemon=True)
    watchdog_thread.start()

    updater.start_polling(timeout=30, read_latency=2, bootstrap_retries=5)
    logger.info("Бот запущен с поддержкой редактирования (глобальный словарь)")
    updater.idle()

if __name__ == '__main__':
    main()