import json
import time
import random
from requests import HTTPError

from LentaAPI import LentaAPI
from logger import get_logger
logger = get_logger()

class LentaParser:
    """Класс для автоматического парсинга товаров в наличии из приложения Лента в МСК и Питере, где более 100 товаров"""
    
    TARGET_CITIES = {"Москва", "Санкт-Петербург"}
    REQUEST_DELAY = 2  # Задержка между запросами в секундах
    BATCH_SIZE = 10  # Количество запросов перед длинной паузой
    BATCH_DELAY = 15  # Длинная пауза после батча

    def __init__(self, api: LentaAPI):
        self.api: LentaAPI = api
        self.city_stores = {"Москва": [], "Санкт-Петербург": []}
        self.last_request_time = 0
    
    def _rate_limited_request(self):
        """Обеспечивает задержку между запросами"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.REQUEST_DELAY:
            time.sleep(random.uniform(1.2, 2.4))
        self.last_request_time = time.time()

    def _get_target_stores(self):
        """Фильтрует магазины только в Москве и Санкт-Петербурге"""
        stores = self.api.get_stores()
        for store in stores["items"]:
            for city in self.TARGET_CITIES:
                if city in store["addressFull"] and store['marketType'] == "HM": # Проверка на город и Гипермаркет(больше товаров)
                    self.city_stores[city].append((store["id"], store["addressFull"]))
                    break
        
        if not self.city_stores:
            raise ValueError("Нет доступных магазинов в Москве и Санкт-Петербурге")

    def _get_brand_of_product(self, product_id, max_retries=7, backoff_factor=3):
        """Получает бренд товара по его ID с повторными попытками при ошибках"""
        import uuid
        self._rate_limited_request()  # Добавляем задержку перед каждым запросом

        attempt = 0
        while attempt < max_retries: # Дефолтное значение будет доходить до целой минуты
            try:
                data = self.api.get_catalog_item(product_id)
                for attribute in data.get('attributes', []):
                    if attribute['alias'] == 'brand' or attribute['name'] == 'Бренд' or attribute['slug'] == 'brand':
                        return attribute['value']
                
                return "Без бренда"
            except HTTPError as e:
                logger.error(f"❌ Ошибка HTTP: {e.response.status_code} - {e.response.text}")
                if e.response.status_code == 429:
                    # wait_time = (backoff_factor ** attempt) + random.uniform(1, 3)
                    wait_time = 60 * (attempt + 1)
                    print(f"⚠️ Превышен лимит запросов (попытка {attempt+1}/{max_retries}), пауза {wait_time:.1f}с")
                    time.sleep(wait_time)
                    self.api.device_id = f"A-{uuid.uuid4()}"
                    self.api.headers["DeviceId"] = self.api.device_id
                    self.api.get_session_token()
                    attempt += 1
                else:
                    raise

        raise TimeoutError(f"❌ Не удалось получить бренд товара за {max_retries} попыток."
                           " Лучше перезапустить программу и подождать некоторое время")

    def run(self):
        """Основная логика парсинга"""
        self._get_target_stores()

        # Получаем категории первого уровня в МСК
        moscow_stores = self.city_stores["Москва"]
        moscow_store, moscow_store_location = random.choice(moscow_stores)
        print(f"📍 Москва, магазин ID: {moscow_store}, адрес: {moscow_store_location}")
        self.api.set_delivery(moscow_store)
        self.api.set_store(moscow_store)
        moscow_categories_level_1 = {
            x['slug']: x['id']
            for x in self.api.get_categories()
            if x['level'] == 1
        }
        
        # Получаем категории первого уровня в Питере
        piter_stores = self.city_stores["Санкт-Петербург"]
        piter_store, piter_store_location = random.choice(piter_stores)
        print(f"📍 Питер, магазин ID: {piter_store}, адрес: {piter_store_location}")
        self.api.set_delivery(piter_store)
        self.api.set_store(piter_store)
        piter_categories_level_1 = {
            x['slug']: x['id']
            for x in self.api.get_categories()
            if x['level'] == 1
        }

        # Поиск общих категорий (навсякий случай)
        common_categories = set(moscow_categories_level_1.keys()) & set(piter_categories_level_1.keys())
        for category_slug in common_categories:
            print(f"\n🔍 Поиск общих товаров в категории {category_slug}")

            # Получаем товары из категории в мск
            self.api.set_delivery(moscow_store)
            self.api.set_store(moscow_store)
            moscow_items = self.api.get_catalog_items(moscow_categories_level_1[category_slug])
            print("Делаем задержку на 5 секунд")
            time.sleep(5)

            # Получаем товары из категории в питере
            self.api.set_delivery(piter_store)
            self.api.set_store(piter_store)
            piter_items = self.api.get_catalog_items(piter_categories_level_1[category_slug])
            
            # Сравниваем товары
            if piter_items['total'] < 100 or moscow_items['total'] < 100:
                print(f"❌ Нехватка товаров для сравнения в категории {category_slug}")
                continue

            # Находим общие товары по id
            moscow_ids = {item["id"]: item for item in moscow_items['items'] if item["count"] > 0 and not item["features"]["isBlockedForSale"]}
            piter_ids = {item["id"]: item for item in piter_items['items'] if item["count"] > 0 and not item["features"]["isBlockedForSale"]}
            
            for item in moscow_items['items']:
                print(item.keys())


            common_products = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "regular_price": item["prices"]["costRegular"] / 100,
                    "promo_price": item["prices"]["cost"] / 100
                }
                for item_id, item in moscow_ids.items()
                if item_id in piter_ids
            ]
            
            common_products = common_products[:101] # 101 товаров

            # Проверяем результаты
            if len(common_products) < 100:
                print(f"❌ Нехватка общих товаров в категории {category_slug}")
                continue

            print(f"✅ Найдено {len(common_products)} общих товаров в категории {category_slug}")
            
            # Добавялем бренды к товарам
            for i, common_products_item in enumerate(common_products):
                common_products_item["brand"] = self._get_brand_of_product(common_products_item["id"])
                print(f"🛒 {common_products_item['name']} ({common_products_item['id']}) добавлен в список ({i+1}/{len(common_products)})")

                # Длинная пауза после каждого батча
                if (i + 1) % self.BATCH_SIZE == 0 and i < len(common_products) - 1:
                    print(f"⏸️  Обработано {i+1} товаров, делаем паузу {self.BATCH_DELAY}с...")
                    time.sleep(self.BATCH_DELAY)

            return common_products
        
        print("❌ Не найдено общих категорий, где больше 100 общих товаров в наличии в Москве и Питере")
        return []

    def save_results(self, data):
        """Сохраняет результаты в JSON"""
        with open("lenta_products_piter_moscow.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print("✅ Данные сохранены в lenta_products_piter_moscow.json")

if __name__ == "__main__":
    api = LentaAPI()
    parser = LentaParser(api)
    
    results = parser.run()  # Запускаем парсер
    parser.save_results(results)  # Сохраняем в JSON