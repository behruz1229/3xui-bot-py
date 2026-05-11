import requests
import json
import uuid
import time
import logging
from datetime import datetime, timedelta
import config

# Отключаем предупреждения о самоподписанном сертификате
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

class XUI_API:
    def __init__(self):
        self.base_url = config.PANEL_URL.rstrip('/')
        self.session = requests.Session()
        self.session.verify = False
        self.logged_in = False
        self.timeout = 15

    def login(self):
        login_url = f"{self.base_url}/login"
        payload = {"username": config.PANEL_LOGIN, "password": config.PANEL_PASSWORD}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        try:
            response = self.session.post(login_url, json=payload, headers=headers, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    self.logged_in = True
                    logger.info("Успешный вход в панель 3x-ui")
                    return True
                else:
                    logger.error(f"Ошибка входа: {data.get('msg', 'неизвестная ошибка')}")
                    return False
            else:
                logger.error(f"Ошибка HTTP при входе: {response.status_code}")
                return False
        except requests.exceptions.Timeout:
            logger.error("Таймаут при входе в панель")
            return False
        except Exception as e:
            logger.error(f"Исключение при входе: {e}")
            return False

    def _ensure_login(self):
        if not self.logged_in:
            return self.login()
        return True

    def _request_with_auth(self, method, url, **kwargs):
        start = time.time()
        if not self._ensure_login():
            return None
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.timeout
        try:
            resp = self.session.request(method, url, **kwargs)
            if resp.status_code == 401:
                logger.warning("Получен 401, пробуем повторный логин...")
                if self.login():
                    resp = self.session.request(method, url, **kwargs)
                else:
                    logger.error("Повторный логин не удался")
                    return None
            elapsed = time.time() - start
            if elapsed > 5:
                logger.warning(f"Долгий запрос {method} {url}: {elapsed:.2f} сек")
            return resp
        except requests.exceptions.Timeout:
            elapsed = time.time() - start
            logger.error(f"Таймаут {method} {url} через {elapsed:.2f} сек")
            return None
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"Исключение {method} {url} через {elapsed:.2f} сек: {e}")
            return None

    def get_inbounds(self):
        url = f"{self.base_url}/panel/api/inbounds/list"
        resp = self._request_with_auth('GET', url)
        if resp is None or resp.status_code != 200:
            return None
        try:
            data = resp.json()
            if data.get("success"):
                return data.get("obj", [])
            else:
                logger.error(f"Ошибка получения списка inbound'ов: {data.get('msg')}")
                return None
        except Exception as e:
            logger.error(f"Ошибка разбора JSON: {e}")
            return None

    def get_inbounds_list(self):
        all_inbounds = self.get_inbounds()
        if all_inbounds is None:
            return None
        result = []
        for inbound_cfg in config.INBOUNDS:
            inbound_id = inbound_cfg["id"]
            inbound_data = None
            for ib in all_inbounds:
                if ib.get("id") == inbound_id:
                    inbound_data = ib
                    break
            if inbound_data is None:
                logger.warning(f"Inbound с id {inbound_id} не найден в панели")
                continue
            stream_settings_str = inbound_data.get("streamSettings", "{}")
            try:
                stream_settings = json.loads(stream_settings_str)
            except json.JSONDecodeError:
                stream_settings = {}
            result.append({
                "id": inbound_id,
                "remark": inbound_cfg["remark"],
                "protocol": inbound_cfg.get("protocol", "vless"),
                "streamSettings": stream_settings,
                "port": inbound_data.get("port"),
                "raw": inbound_data
            })
        return result

    def get_clients_from_inbound(self, inbound_id):
        inbounds = self.get_inbounds()
        if inbounds is None:
            return None
        for inbound in inbounds:
            if inbound.get("id") == inbound_id:
                settings = inbound.get("settings", "{}")
                try:
                    settings_json = json.loads(settings)
                    clients = settings_json.get("clients", [])
                    return clients
                except json.JSONDecodeError:
                    logger.error("Ошибка разбора settings")
                    return []
        return []

    def get_clients_from_all_inbounds(self):
        all_clients = []
        inbound_list = self.get_inbounds_list()
        if not inbound_list:
            return []
        for inbound in inbound_list:
            inbound_id = inbound["id"]
            inbound_remark = inbound["remark"]
            clients = self.get_clients_from_inbound(inbound_id)
            if clients:
                for client in clients:
                    client["inbound_id"] = inbound_id
                    client["inbound_remark"] = inbound_remark
                all_clients.extend(clients)
        return all_clients

    def add_client(self, inbound_id, email, total_gb, expiry_days):
        client_uuid = str(uuid.uuid4())
        if expiry_days > 0:
            expiry_time = int((datetime.now() + timedelta(days=expiry_days)).timestamp() * 1000)
        else:
            expiry_time = 0

        client_data = {
            "id": client_uuid,
            "email": email,
            "limitIp": 0,
            "totalGB": total_gb * 1024**3,
            "expiryTime": expiry_time,
            "enable": True,
            "flow": "",
            "subId": None,
            "tgId": None
        }

        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_data]})
        }

        url = f"{self.base_url}/panel/api/inbounds/addClient"
        resp = self._request_with_auth('POST', url, json=payload)
        if resp is None:
            return False, "Ошибка соединения с панелью"
        if resp.status_code == 200:
            try:
                result = resp.json()
                if result.get("success"):
                    return True, f"Клиент {email} успешно создан.\nUUID: `{client_uuid}`"
                else:
                    return False, f"Ошибка API: {result.get('msg', 'неизвестная ошибка')}"
            except Exception as e:
                return False, f"Ошибка разбора ответа: {e}"
        else:
            return False, f"Ошибка HTTP {resp.status_code}"

    def delete_client(self, inbound_id, client_id):
        url = f"{self.base_url}/panel/api/inbounds/{inbound_id}/delClient/{client_id}"
        resp = self._request_with_auth('POST', url)
        if resp is None:
            return False, "Ошибка соединения с панелью"
        if resp.status_code == 200:
            try:
                result = resp.json()
                if result.get("success"):
                    return True, "Клиент удалён"
                else:
                    return False, f"Ошибка API: {result.get('msg')}"
            except Exception as e:
                return False, f"Ошибка разбора ответа: {e}"
        else:
            return False, f"Ошибка HTTP {resp.status_code}"

    def get_client_traffic(self, email):
        url1 = f"{self.base_url}/panel/api/inbounds/getClientTraffics/{email}"
        resp = self._request_with_auth('GET', url1)
        if resp is not None and resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("success"):
                    return data.get("obj")
            except:
                pass

        url2 = f"{self.base_url}/panel/api/inbounds/stats"
        resp = self._request_with_auth('GET', url2)
        if resp is not None and resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("success"):
                    stats_list = data.get("obj", [])
                    for stat in stats_list:
                        if stat.get("email") == email:
                            return stat
            except:
                pass
        return None

    def get_inbound_settings(self, inbound_id):
        inbounds = self.get_inbounds()
        if inbounds is None:
            return None
        for inbound in inbounds:
            if inbound.get("id") == inbound_id:
                stream_settings_str = inbound.get("streamSettings", "{}")
                try:
                    return json.loads(stream_settings_str)
                except json.JSONDecodeError:
                    logger.error(f"Ошибка разбора streamSettings для inbound {inbound_id}")
                    return None
        return None

    def get_online_users(self):
        url = f"{self.base_url}/panel/api/inbounds/onlines"
        resp = self._request_with_auth('POST', url, data={})
        if resp is not None and resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("success"):
                    return data.get("obj", [])
            except Exception as e:
                logger.error(f"Ошибка разбора ответа onlines: {e}")
        return []

    def restart_xray(self):
        url = f"{self.base_url}/panel/api/server/restartXrayService"
        resp = self._request_with_auth('POST', url, data={})
        if resp is None:
            return True, "Запрос на перезапуск отправлен (соединение могло быть разорвано). Проверьте статус Xray."
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("success"):
                    return True, "Сервис Xray успешно перезапущен."
                else:
                    return False, f"Ошибка API: {data.get('msg', 'неизвестная ошибка')}"
            except Exception as e:
                return False, f"Ошибка разбора ответа: {e}"
        else:
            return False, f"Ошибка HTTP {resp.status_code} при перезапуске Xray"

    # === НОВЫЕ МЕТОДЫ ДЛЯ РЕДАКТИРОВАНИЯ КЛИЕНТА ===
    def update_client(self, inbound_id, client_id, new_total_gb=None, new_expiry_days=None):
        """
        Обновляет лимит трафика и/или срок действия клиента.
        Если параметр None, то соответствующее поле не меняется.
        Возвращает (success, message)
        """
        # 1. Получить текущего клиента
        clients = self.get_clients_from_inbound(inbound_id)
        if not clients:
            return False, "Клиент не найден"
        client = next((c for c in clients if c.get('id') == client_id), None)
        if not client:
            return False, "Клиент не найден"

        # 2. Подготовить обновлённые данные
        updated_client = client.copy()
        if new_total_gb is not None:
            updated_client['totalGB'] = new_total_gb * 1024**3
        if new_expiry_days is not None:
            if new_expiry_days > 0:
                expiry_time = int((datetime.now() + timedelta(days=new_expiry_days)).timestamp() * 1000)
            else:
                expiry_time = 0
            updated_client['expiryTime'] = expiry_time

        # 3. Сформировать payload как в браузере
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [updated_client]})
        }

        url = f"{self.base_url}/panel/api/inbounds/updateClient/{client_id}"
        resp = self._request_with_auth('POST', url, data=payload)  # data, не json, так как в браузере application/x-www-form-urlencoded
        if resp is None:
            return False, "Ошибка соединения с панелью"
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("success"):
                    return True, "Клиент успешно обновлён"
                else:
                    return False, f"Ошибка API: {data.get('msg', 'неизвестная ошибка')}"
            except Exception as e:
                return False, f"Ошибка разбора ответа: {e}"
        else:
            return False, f"Ошибка HTTP {resp.status_code}"

    def reset_client_traffic(self, inbound_id, email):
        """
        Сбрасывает использованный трафик клиента.
        Возвращает (success, message)
        """
        url = f"{self.base_url}/panel/api/inbounds/{inbound_id}/resetClientTraffic/{email}"
        resp = self._request_with_auth('POST', url, data={})
        if resp is None:
            return False, "Ошибка соединения с панелью"
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("success"):
                    return True, "Трафик успешно сброшен"
                else:
                    return False, f"Ошибка API: {data.get('msg', 'неизвестная ошибка')}"
            except Exception as e:
                return False, f"Ошибка разбора ответа: {e}"
        else:
            return False, f"Ошибка HTTP {resp.status_code}"

    def close(self):
        if self.session:
            self.session.close()