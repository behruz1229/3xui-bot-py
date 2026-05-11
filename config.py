# config.py

# Telegram Bot Token
TOKEN = "0123456789:AAAAAAAAAAAAAAAAAAAAAAAAAA"  # замените на свой токен! который можно созать через @BotFather
# Панель управления 3x-ui
PANEL_URL = "https://exemple.org:port/panel"  # ваш URL панели, https://exemple.org:port/root_panel
PANEL_LOGIN = "Admin"
PANEL_PASSWORD = "admin"

# Внешний IP сервера для генерации ссылок
SERVER_IP = "XXX.XXX.XXX.XXX"  # ваш IP Сервера VPS

# ID авторизованного пользователя Telegram
AUTHORIZED_USER_ID = 0123456789  # ID Telegram того человека который будет доступ к боту

# Список inbound'ов, с которыми работает бот
# Каждый inbound: id, remark (отображаемое имя), protocol (пока не используется)
INBOUNDS = [
    {"id": X, "remark": "tcp-443", "protocol": "vless"},
    {"id": X, "remark": "gRPC-1443", "protocol": "vless"},
]
