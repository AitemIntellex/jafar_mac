import os
import requests
from dotenv import load_dotenv
from rich.console import Console
from datetime import datetime, timedelta

# Загружаем переменные окружения из корневой папки проекта
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
console = Console()

# --- Конфигурация API ---
API_BASE_URL = "https://api.topstepx.com/api" 
API_KEY = os.environ.get("TOPSTEPX_API_KEY")
USERNAME = os.environ.get("TOPSTEPX_USERNAME")

class TopstepXClient:
    def __init__(self):
        self._api_key = os.environ.get("TOPSTEPX_API_KEY")
        self._username = os.environ.get("TOPSTEPX_USERNAME")
        
        if not self._api_key or not self._username:
            raise ValueError("API ключ или имя пользователя не найдены. Убедитесь, что TOPSTEPX_API_KEY и TOPSTEPX_USERNAME заданы в .env файле.")
        
        self._session_token = None
        self._token_expiry = None
        self._headers = {"Content-Type": "application/json", "accept": "text/plain"}
        self._authenticate()

    def _authenticate(self):
        """Получает и сохраняет токен доступа."""
        console.print("[cyan]Аутентификация и получение токена доступа...[/cyan]")
        endpoint = "/Auth/loginKey"
        url = f"{API_BASE_URL}{endpoint}"
        
        payload = {
            "userName": self._username,
            "apiKey": self._api_key
        }
        
        try:
            response = requests.post(url, headers=self._headers, json=payload)
            response.raise_for_status()
            data = response.json()
            
            if not data.get("success"):
                error_msg = data.get('errorMessage', 'Неизвестная ошибка аутентификации')
                raise ValueError(f"Ошибка аутентификации: {error_msg} (Код: {data.get('errorCode')})")

            self._session_token = data.get("token")
            # Устанавливаем срок действия токена (например, 24 часа, нужно уточнить в документации)
            self._token_expiry = datetime.now() + timedelta(hours=24) 
            
            if not self._session_token:
                raise ValueError("Не удалось получить токен доступа из ответа API.")

            # Обновляем заголовок для последующих запросов
            self._headers["Authorization"] = f"Bearer {self._session_token}"
            console.print("[bold green]Аутентификация прошла успешно![/bold green]")

        except requests.exceptions.HTTPError as http_err:
            console.print(f"[bold red]HTTP ошибка при аутентификации: {http_err}[/bold red]")
            console.print(f"Текст ответа: {response.text}")
            raise
        except requests.exceptions.RequestException as req_err:
            console.print(f"[bold red]Ошибка запроса при аутентификации: {req_err}[/bold red]")
            raise
        except ValueError as val_err:
            console.print(f"[bold red]{val_err}[/bold red]")
            raise

    def _is_token_expired(self):
        """Проверяет, не истек ли срок действия токена."""
        if not self._token_expiry:
            return True
        return datetime.now() >= self._token_expiry

    def _make_request(self, method: str, endpoint: str, params: dict = None, data: dict = None, tick_size: float = None):
        """Универсальная функция для выполнения запросов к API."""
        if self._is_token_expired():
            console.print("[yellow]Токен доступа истек. Повторная аутентификация...[/yellow]")
            self._authenticate()

        url = f"{API_BASE_URL}{endpoint}"
        try:
            response = requests.request(method, url, headers=self._headers, params=params, json=data)
            response.raise_for_status()
            # Для некоторых запросов API может возвращать пустой ответ с кодом 200
            if response.text:
                return response.json()
            return None
        except requests.exceptions.HTTPError as http_err:
            console.print(f"[bold red]HTTP ошибка: {http_err}[/bold red]")
            console.print(f"Текст ответа: {response.text}")
        except requests.exceptions.RequestException as req_err:
            console.print(f"[bold red]Ошибка запроса: {req_err}[/bold red]")
        return None

    # --- Методы для работы с аккаунтом ---
    def get_account_list(self):
        """
        Получает список всех активных счетов.
        """
        console.print("[cyan]Запрос списка счетов...[/cyan]")
        payload = {"onlyActiveAccounts": True}
        return self._make_request("POST", "/Account/search", data=payload)

    def get_account_details(self, account_id: int):
        """
        Получает детали по конкретному счету, фильтруя из списка всех счетов.
        """
        console.print(f"[cyan]Запрос деталей для счета ID: {account_id}...[/cyan]")
        accounts_response = self.get_account_list()
        if accounts_response and accounts_response.get("accounts"):
            for account in accounts_response["accounts"]:
                if account["id"] == account_id:
                    return account
        console.print(f"[yellow]Счет с ID {account_id} не найден.[/yellow]")
        return None

    # --- Методы для работы с позициями и ордерами ---
    def get_open_positions(self, account_id: int):
        """
        Получает список всех открытых позиций для указанного счета.
        """
        console.print(f"[cyan]Запрос открытых позиций для счета {account_id}...[/cyan]")
        payload = {"accountId": account_id}
        return self._make_request("POST", "/Position/searchOpen", data=payload)

    def get_orders(self, account_id: int, start_timestamp: datetime, end_timestamp: datetime):
        """
        Получает список ордеров за указанный период для конкретного счета.
        """
        console.print(f"[cyan]Запрос ордеров для счета {account_id} с {start_timestamp} по {end_timestamp}...[/cyan]")
        payload = {
            "accountId": account_id,
            "startTimestamp": start_timestamp.isoformat(timespec='milliseconds') + 'Z',
            "endTimestamp": end_timestamp.isoformat(timespec='milliseconds') + 'Z'
        }
        return self._make_request("POST", "/Order/search", data=payload)

    def get_trades(self, account_id: int, start_timestamp: datetime, end_timestamp: datetime):
        """
        Получает список сделок (trades) за указанный период для конкретного счета.
        """
        console.print(f"[cyan]Запрос сделок для счета {account_id} с {start_timestamp} по {end_timestamp}...[/cyan]")
        payload = {
            "accountId": account_id,
            "startTimestamp": start_timestamp.isoformat(timespec='milliseconds') + 'Z',
            "endTimestamp": end_timestamp.isoformat(timespec='milliseconds') + 'Z'
        }
        return self._make_request("POST", "/Trade/search", data=payload)

    def get_historical_bars(self, contract_id: str, start_time: datetime, end_time: datetime, 
                            unit: int, unit_number: int, limit: int = 100, include_partial_bar: bool = False):
        """
        Получает исторические бары для указанного контракта и периода.
        Unit: 0=Tick, 1=Second, 2=Minute, 3=Hour, 4=Day, 5=Week, 6=Month, 7=Year
        """
        console.print(f"[cyan]Запрос исторических баров для контракта {contract_id} с {start_time} по {end_time}...[/cyan]")
        payload = {
            "contractId": contract_id,
            "live": False, # Для исторических данных обычно False
            "startTime": start_time.isoformat(timespec='milliseconds') + 'Z',
            "endTime": end_time.isoformat(timespec='milliseconds') + 'Z',
            "unit": unit,
            "unitNumber": unit_number,
            "limit": limit,
            "includePartialBar": include_partial_bar
        }
        return self._make_request("POST", "/History/retrieveBars", data=payload)

    def search_contract(self, name: str):
        """
        Ищет контракт по его имени (например, "GC").
        """
        console.print(f"[cyan]Поиск контракта по имени '{name}'...[/cyan]")
        payload = {"searchText": name, "live": False}
        return self._make_request("POST", "/Contract/search", data=payload)

    def cancel_order(self, account_id: int, order_id: int):
        """
        Отменяет активный ордер по его ID.
        """
        console.print(f"[cyan]Отмена ордера ID: {order_id} для счета {account_id}...[/cyan]")
        payload = {"accountId": account_id, "orderId": order_id}
        return self._make_request("POST", "/Order/cancel", data=payload)

    def place_order(self, contract_id: str, account_id: int, side: int, order_type: int, size: int, 
                    tick_size: float, limit_price: float = None, stop_price: float = None, 
                    stop_loss: float = None, take_profit: float = None):
        """
        Размещает торговый ордер согласно официальной документации ProjectX.
        side: 0 = Buy, 1 = Sell
        order_type (internal): 0 = Limit, 1 = Stop, 2 = Market
        """
        # --- Маппинг внутренних типов ордеров на типы API ---
        # API: 1=Limit, 2=Market, 4=Stop
        type_map = {
            0: 1, # Наш Limit (0) -> API Limit (1)
            1: 4, # Наш Stop (1) -> API Stop (4)
            2: 2, # Наш Market (2) -> API Market (2)
        }
        api_order_type = type_map.get(order_type)
        if api_order_type is None:
            raise ValueError(f"Неподдерживаемый внутренний тип ордера: {order_type}")

        console.print(f"[bold yellow]Размещение ордера: side={side}, type={api_order_type}, size={size}, contract={contract_id} @ {limit_price or stop_price or 'Market'}[/bold yellow]")
        
        payload = {
            "contractId": contract_id,
            "accountId": account_id,
            "side": side,
            "type": api_order_type,
            "size": size,
        }
        
        # 'limitPrice' обязателен для Limit ордеров
        if api_order_type == 1 and limit_price is not None:
            payload["limitPrice"] = limit_price
        # 'stopPrice' обязателен для Stop ордеров
        if api_order_type == 4 and stop_price is not None:
            payload["stopPrice"] = stop_price
            
        # --- НОВАЯ ЛОГИКА BRACKET ORDERS (SL/TP) ---
        # ВАЖНО: API ожидает SL/TP в ТИКАХ, а не в абсолютной цене.
        # Используем динамический tick_size
        
        entry_price_for_ticks = limit_price if limit_price is not None else stop_price
        
        if entry_price_for_ticks:
            if stop_loss:
                sl_ticks = (stop_loss - entry_price_for_ticks) / tick_size
                payload["stopLossBracket"] = {
                    "ticks": int(sl_ticks),
                    "type": 4 # API требует Stop Market ордер для SL
                }
                console.print(f"[cyan]Stop-Loss: {stop_loss} ({int(sl_ticks)} тиков)[/cyan]")

            if take_profit:
                tp_ticks = (take_profit - entry_price_for_ticks) / tick_size
                payload["takeProfitBracket"] = {
                    "ticks": int(tp_ticks),
                    "type": 1 # Limit order
                }
                console.print(f"[cyan]Take-Profit: {take_profit} ({int(tp_ticks)} тиков)[/cyan]")

        return self._make_request("POST", "/Order/place", data=payload, tick_size=tick_size)

# --- Тестовый запуск ---
if __name__ == "__main__":
    console.print("[bold yellow]--- Тестирование API клиента TopstepX ---[/bold yellow]")
    
    if not API_KEY or not USERNAME:
        console.print("[bold red]Ошибка: TOPSTEPX_API_KEY или TOPSTEPX_USERNAME не найдены в .env файле.[/bold red]")
    else:
        try:
            client = TopstepXClient()
            
            # 1. Получаем список счетов
            accounts_response = client.get_account_list()
            
            if accounts_response and accounts_response.get("accounts"):
                console.print("[bold green]Список счетов успешно получен:[/bold green]")
                from rich import print_json
                print_json(data=accounts_response)
                
                # Берем ID первого счета для дальнейших тестов
                first_account_id = accounts_response["accounts"][0]["id"]
                
                # 2. Получаем детали по первому счету
                account_details = client.get_account_details(first_account_id)
                if account_details:
                    console.print(f"[bold green]Детали для счета {first_account_id} успешно получены:[/bold green]")
                    print_json(data=account_details)

                # 3. Получаем открытые позиции
                open_positions = client.get_open_positions(first_account_id)
                if open_positions:
                    console.print("[bold green]Открытые позиции успешно получены:[/bold green]")
                    print_json(data=open_positions)
                else:
                    console.print("[yellow]Открытых позиций нет или эндпоинт не вернул данных.[/yellow]")

                # Для теста возьмем данные за последние 24 часа
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(days=1)

                # 4. Получаем ордера
                orders = client.get_orders(first_account_id, start_time, end_time)
                if orders:
                    console.print("[bold green]Ордера успешно получены:[/bold green]")
                    print_json(data=orders)
                else:
                    console.print("[yellow]Ордеров нет или эндпоинт не вернул данных.[/yellow]")

                # 5. Получаем историю сделок (trades)
                trades = client.get_trades(first_account_id, start_time, end_time)
                if trades:
                    console.print("[bold green]История сделок (trades) успешно получена:[/bold green]")
                    print_json(data=trades)
                else:
                    console.print("[yellow]Истории сделок нет или эндпоинт не вернул данных.[/yellow]")

                # 6. Получаем исторические бары (для примера, используем placeholder contractId)
                # Вам нужно будет заменить 'YOUR_CONTRACT_ID' на реальный ID контракта (например, для золота)
                # Unit: 2 = Minute, unitNumber = 5 (5-минутные бары)
                console.print("[bold yellow]Тестирование получения исторических баров...[/bold yellow]")
                test_contract_id = "ESM2025" # Пример, замените на реальный ID контракта
                bar_start_time = datetime.utcnow() - timedelta(hours=1)
                bar_end_time = datetime.utcnow()
                historical_bars = client.get_historical_bars(test_contract_id, bar_start_time, bar_end_time, 
                                                             unit=2, unit_number=5, limit=10)
                if historical_bars:
                    console.print(f"[bold green]Исторические бары для {test_contract_id} успешно получены:[/bold green]")
                    print_json(data=historical_bars)
                else:
                    console.print(f"[yellow]Исторические бары для {test_contract_id} не получены или эндпоинт не вернул данных.[/yellow]")

            else:
                console.print("[yellow]Запрос выполнен, но список счетов пуст или эндпоинт не вернул данных.[/yellow]")

        except (ValueError, requests.exceptions.RequestException) as e:
            # Ошибки уже логируются внутри методов, здесь просто финальное сообщение
            console.print(f"[bold red]Не удалось выполнить тестовый запуск клиента.[/bold red]")
