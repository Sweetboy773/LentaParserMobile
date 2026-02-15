import requests
import uuid
import json
import time
import hashlib
import logging
from datetime import datetime, timezone

def get_localtime():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# https://7thzero.com/blog/extract-an-apk-from-android-devices-using-adb для извлечения apk
# APP_VERSION = 6.25.2 декомпилированная соль
# ДОЛГО И МУЧИТЕЛЬНО НО ДОБЫЛ
QRTR_SALT = "b4fad1ebab4532185b653330d593b472"

def generate_qrator_token(url: str) -> tuple[str, str]:
    """Генерирует Qrator-Token на основе URL и текущего времени."""
    timestamp = str(int(time.time()))  # Аналог System.currentTimeMillis() / 1000
    url_base = url.split('?', 1)[0]   # Аналог substringBefore(url, '?')

    # Формируем строку для хэширования (соль + URL + timestamp)
    raw_string = QRTR_SALT + url_base + timestamp
    md5_hash = hashlib.md5(raw_string.encode('utf-8')).digest()

    # Преобразуем байты в строку в 16-ричном формате с ведущими нулями
    token = ''.join(f"{byte:02x}" for byte in md5_hash)
    
    return token, timestamp

def setup_logging():
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": "lentaParser.log",
                "when": "midnight",
                # "atTime": "16H:59M:59S",
                "interval": 1,
                "backupCount": 0,
                "formatter": "default",
                "encoding": "utf-8",
                "level": "DEBUG",
            },
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": "DEBUG",
            }
        },
        "loggers": {
            "ReportLogger": {
                "handlers": ["file", "console"],
                "level": "DEBUG",
                "propagate": False
            },
        },
        "root": {
            "handlers": ["console"],
            "level": "WARNING"
        }
    }
    logging.config.dictConfig(logging_config)

logger = logging.getLogger("ReportLogger")


class LentaAPI:
    LENTOCHKA_URL = "https://lentochka.lenta.com"
    API_LENTA_URL = "https://api.lenta.com"

    def __init__(self, app_version="6.25.2", client_version="android_14_6.25.2", marketing_partner_key="mp402-8a74f99040079ea25d64d14b5212b0e3"):
        """Инициализация API-клиента"""
        self.client_version = client_version
        self.device_id = f"A-{uuid.uuid4()}"  # Генерация уникального DeviceId
        self.request_id = uuid.uuid4().hex  # Уникальный RequestId
        self.marketing_partner_key = marketing_partner_key
        self.app_version = app_version
        self.session_token = None
        self.headers = {
            "Accept-Encoding": "gzip",
            "Client": self.client_version,
            "App-Version": self.app_version,
            "Connection": "Keep-Alive",
            "DeviceId": self.device_id,
            "baggage": "sentry-environment=production,sentry-public_key=f9ad84e90a2441998bd9ec0acb1a3dbe,sentry-release=com.icemobile.lenta.prod%406.25.2%2B2402",
            "sentry-trace": "a4edef4706eb4781805db2a04de7231b-1fd9d2771e6a4e96",
            "User-Agent": "okhttp/4.9.1",
            "X-Platform": "omniapp",
            "x-retail-brand": "lo"
        }
    
    def _update_qrator_token(self, url):
        self.headers['Qrator-Token'], self.headers['Timestamp'] = generate_qrator_token(url)
        self.headers["LocalTime"] = get_localtime()

    def get_session_token(self):
        """Запрос к API для получения SessionToken"""
        URL = f'{self.LENTOCHKA_URL}/api/rest/siteSettingsGet'
        payload = {
            "Head": {
                "Method": "siteSettingsGet",
                "RequestId": self.request_id,
                "DeviceId": self.device_id,
                "Client": self.client_version,
                "MarketingPartnerKey": self.marketing_partner_key
            }
        }
        params = {
            "request": json.dumps(payload)
        }

        self._update_qrator_token(URL)
        self.headers["SessionToken"] = None

        response = requests.get(URL, headers=self.headers, params=params)
        logger.info(f"📡 Отправка запроса на {URL} с параметрами: {json.dumps(payload, ensure_ascii=False)}")

        if response.status_code == 200:
            data = response.json()
            self.session_token = data.get("Head", {}).get("SessionToken")
            if self.session_token:
                self.headers["SessionToken"] = self.session_token
                logger.info(f"✅ Новый SessionToken: {self.session_token}")
                return self.session_token
            else:
                raise ValueError("SessionToken не найден в ответе API")
        else:
            raise requests.HTTPError(f"Ошибка API: {response.status_code}, {response.text}")

    def _ensure_session_token(self):
        """Проверяет, есть ли `SessionToken`, если нет – запрашивает его."""
        if not self.session_token:
            self.get_session_token()

    def get_catalog_items(self, category_id: int):
        """Получение товаров в наличии из каталога по ID категории
        формат ответа:
        {
            "categories": ...,
            "filters": ...,
            "items": [
                {
                    "badges": {}
                    "chipsPrices": [],
                    "count": 100,
                    "dimensions": {
                        "height": 0,
                        "length": 0,
                        "width": 0
                    },
                    "features": {
                        "isAdult": false,
                        "isAlcohol": false,
                        "isBlockedForSale": false,
                        "isFavorite": false,
                        "isMarkType": false,
                        "isMercurial": false,
                        "isOnlyPickup": false,
                        "isPartner": false,
                        "isPromo": false,
                        "isPurchased": false,
                        "isTobacco": false,
                        "isWeight": true
                    },
                    "id": 60715,
                    "images": []
                    "name": "Картофель ЛЕНТА FRESH Айдахо, весовой",
                    "prices": {
                        "cost": 50499,
                        "costRegular": 50499,
                        "isLoyaltyCardPrice": false,
                        "isPromoactionPrice": false,
                        "price": 15150,
                        "priceRegular": 15150
                    },
                    "quantityDiscount": [],
                    "rating": {
                        "rate": 4.6,
                        "votes": 835
                    },
                    "saleLimit": {
                        "foldQuantity": 1,
                        "maxSaleQuantity": 100,
                        "minSaleQuantity": 1
                    },
                    "slug": "kartofel-ajjdaho-ves-lenta-fresh-sp-rossiya",
                    "storeId": 1453,
                    "weight": {
                        "gross": 300,
                        "net": 300,
                        "package": ""
                    }
                },
            ],
            "total": 102
        }"""
        self._ensure_session_token()

        URL = f'{self.API_LENTA_URL}/v1/catalog/items'
        payload = {
            "categoryId": category_id,
            "filters": {
                "multicheckbox": [],
                "checkbox": [],
                "range": []
            },
            "sort": {
                "type": "popular",
                "order": "desc"
            },
            "limit": 200,
            "offset": 0
        }
        
        self._update_qrator_token(URL)
        response = requests.post(URL, headers=self.headers, data=json.dumps(payload))
        if response.ok:
            logger.info(f"✅ Успешный ответ ({response.status_code}): {response.text}")
            return response.json() if response.status_code == 200 else None
        else:
            raise requests.HTTPError(f"Ошибка API: {response.status_code}, {response.text}")

    def get_stores(self):
        """Получение списка всех доступных магазинов"""
        self._ensure_session_token()

        URL = f'{self.API_LENTA_URL}/v1/stores/pickup/search'
        self._update_qrator_token(URL)
        response = requests.post(URL, headers=self.headers, json={})
        if response.ok:
            logger.info(f"✅ Успешный ответ ({response.status_code}): {response.text}")
            return response.json() if response.status_code == 200 else None
        else:
            raise requests.HTTPError(f"Ошибка API: {response.status_code}, {response.text}")
    
    def set_delivery(self, store_id):
        """Выбирает город с которым будем работать"""
        self._ensure_session_token()

        # Устанавливаем доставку
        URL = f'{self.LENTOCHKA_URL}/jrpc/deliveryModeSet'
        payload = {
            "jsonrpc": "2.0",
            "method": "deliveryModeSet",
            "id": 1738855566367,
            "params": {
                "type": "shop",
                "storeId": store_id
            }
        }
        self._update_qrator_token(URL)
        response = requests.post(URL, headers=self.headers, data=json.dumps(payload))
        if response.ok:
            logger.info(f"✅ Успешный ответ ({response.status_code}): {response.text}")
        else:
            raise requests.HTTPError(f"Ошибка API: {response.status_code}, {response.text}")

    def set_store(self, store_id):
        self._ensure_session_token()

        # Устанавливаем магазин
        URL = f'{self.LENTOCHKA_URL}/jrpc/pickupStoreSelectedSet'
        payload = {
            "jsonrpc": "2.0",
            "method": "pickupStoreSelectedSet",
            "id": 1738855567174,
            "params": {
                "storeId": store_id
            }
        }
        self._update_qrator_token(URL)
        response = requests.post(URL, headers=self.headers, data=json.dumps(payload))
        if response.ok:
            logger.info(f"✅ Успешный ответ ({response.status_code}): {response.text}")
            logger.info(f"🏪 Установлен магазин по адресу: {response.json()['result']['addressFull']}")
        else:
            raise requests.HTTPError(f"Ошибка API: {response.status_code}, {response.text}")

    def get_categories(self) -> dict:
        """Получение списка категорий товаров в формате 
        {
            "badges": [],
            "hasChildren": true,
            "iconUrl": "https://cdn.lentochka.lenta.com/resample/0x0/category_images_v2/17036/icon/caf12d1751e99418.png",
            "id": 17036,
            "imageUrl": "https://cdn.lentochka.lenta.com/resample/0x0/category_images_v2/17036/image/6bed6a18d129f906.png",
            "imageWebUrl": "https://cdn.lentochka.lenta.com/resample/0x0/category_images_v2/17036/image_web/6f32fe2eeb5386e2.png",
            "isAdult": true,
            "level": 1,
            "name": "Алкоголь",
            "parentId": 0,
            "parentName": "",
            "slug": "alkogol"
        }"""
        self._ensure_session_token()

        URL = f'{self.API_LENTA_URL}/v1/catalog/categories'
        self._update_qrator_token(URL)
        response = requests.get(URL, headers=self.headers)
        if response.status_code == 200:
            return response.json()["categories"]
        else:
            raise requests.HTTPError(f"Ошибка API: {response.status_code}, {response.text}")

    def get_catalog_item(self, item_id) -> dict:
        """Получение подробностей про товар"""
        self._ensure_session_token()

        URL = f'{self.API_LENTA_URL}/v1/catalog/items/{item_id}'
        self._update_qrator_token(URL)
        response = requests.get(URL, headers=self.headers)
        if response.status_code == 200:
            return response.json()
        else:
            raise requests.HTTPError(f"Ошибка API: {response.status_code}, {response.text}", response=response)

if __name__ == "__main__":
    setup_logging()
    api = LentaAPI()
    print(api.get_categories())