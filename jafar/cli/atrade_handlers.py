import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from rich.console import Console
from rich import print_json
from PIL import Image
import io
import sys
import re
import json
import shlex
import concurrent.futures
from jafar.utils.gemini_api import ask_gemini_with_image, ask_gemini_text_only
from jafar.utils.news_api import get_unified_news
from jafar.utils.topstepx_api_client import TopstepXClient
from .telegram_handler import send_telegram_media_group, send_long_telegram_message
from .economic_calendar_fetcher import fetch_economic_calendar_data
from .muxlisa_voice_output_handler import speak_muxlisa_text

console = Console()
SCREENSHOT_DIR = Path("screenshot")
ATRADE_LOG_PATH = Path("/Users/macbook/projects/jr/jafar_unified/memory/atrade_analysis_log.md")

# --- НОВАЯ ФУНКЦИЯ ЛОГИРОВАНИЯ ---
def _log_atrade_summary(instrument: str, analysis_data: dict):
    """Сохраняет краткую сводку анализа в лог-файл в директории memory."""
    try:
        log_file = ATRADE_LOG_PATH
        log_file.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Извлекаем основные данные для сводки
        full_analysis = analysis_data.get("full_analysis_uzbek_cyrillic", "Таҳлил матни мавжуд эмас.")
        trade_data = analysis_data.get("trade_data", {})
        
        # Ищем ключевые выводы в тексте анализа (например, первый абзац)
        summary_paragraph = full_analysis.split('\n\n')[0]

        log_entry = f"""
---
**Дата:** {timestamp}
**Инструмент:** {instrument.upper()}
**План A:** {trade_data.get('action', 'N/A')} @ {trade_data.get('primary_entry', 'N/A')} (SL: {trade_data.get('stop_loss', 'N/A')}, TP1: {trade_data.get('take_profits', {}).get('tp1', 'N/A')})
**Ключевой вывод:** {summary_paragraph}
---
"""
        with log_file.open("a", encoding="utf-8") as f:
            f.write(log_entry)
        
        console.print(f"[dim green]Анализ '{instrument.upper()}' учун хулоса 'memory'га сақланди.[/dim green]")

    except Exception as e:
        console.print(f"[red]Лог файлига ёзишда хатолик: {e}[/red]")


# --- КОНСТАНТЫ И УТИЛИТЫ ---
DEPOSIT = 2000.0
MAX_RISK_PERCENT_DEFAULT = 0.02
MAX_RISK_GROUP_A = 450.0
WINNING_DAY_TARGET_USD = 150.0
# Заменяем константу на словарь
MAX_CONTRACTS_MAP = {
    "MGC": 50,
    "GC": 5,
    "CL": 10,
    "ES": 10,
    # Добавьте другие инструменты по мере необходимости
}
CONTRACT_MULTIPLIERS = {
    "GC": 100.0, "MGC": 10.0, "EURUSD": 100000.0, "GBPUSD": 100000.0,
    "USDJPY": 100000.0, "SPX500": 50.0,
}

def calculate_trade_metrics(entry_price, stop_loss, take_profit, contract_multiplier, max_risk_for_trade, contract_symbol: str):
    # ... (эта функция остается без изменений)
    risk_per_unit = abs(entry_price - stop_loss)
    if risk_per_unit == 0: return {"error": "Risk per unit is zero."}
    risk_per_contract = risk_per_unit * contract_multiplier
    if risk_per_contract == 0: return {"error": "Risk per contract is zero."}
    
    # Получаем правильный лимит для текущего инструмента
    max_contracts_for_instrument = MAX_CONTRACTS_MAP.get(contract_symbol, 1) # По умолчанию 1, если символ не найден

    calculated_position_size = max_risk_for_trade / risk_per_contract
    position_size = min(calculated_position_size, max_contracts_for_instrument)

    if position_size < 0.01: return {"error": f"Calculated position size ({position_size:.2f}) is too small."}
    profit_per_unit = abs(take_profit - entry_price)
    total_risk_usd = position_size * risk_per_contract
    total_profit_usd = position_size * profit_per_unit * contract_multiplier
    risk_reward_ratio = total_profit_usd / total_risk_usd if total_risk_usd > 0 else float("inf")
    return {
        "position_size": round(position_size, 2), "total_risk_usd": round(total_risk_usd, 2),
        "total_profit_usd": round(total_profit_usd, 2), "risk_reward_ratio": round(risk_reward_ratio, 2),
        "meets_winning_day_target": total_profit_usd >= WINNING_DAY_TARGET_USD,
    }

def get_formatted_topstepx_data(instrument_query: str, contract_id: str) -> tuple[str, dict, dict, list]:
    """
    Подключается к TopstepX API, реализует умный выбор счета, получает данные 
    параллельно и форматирует их в строку для промпта Gemini.
    Возвращает кортеж: (форматированная_строка, объект_аккаунта).
    """
    console.print("\n[blue]Загрузка данных из TopstepX API (параллельно)...[/blue]")
    try:
        client = TopstepXClient()
        
        # 1. Получаем список счетов
        accounts_response = client.get_account_list()
        if not accounts_response or not accounts_response.get("accounts"):
            return "  - Ошибка: Не удалось получить список счетов из TopstepX.", None
        
        all_accounts = accounts_response["accounts"]
        primary_account = None
        
        # 2. "Умный" выбор счета
        preferred_account_name = os.environ.get("TOPSTEPX_ACCOUNT_NAME")
        
        if preferred_account_name:
            for acc in all_accounts:
                if acc.get("name") == preferred_account_name:
                    primary_account = acc
                    console.print(f"[green]Используется счет из .env файла: {preferred_account_name}[/green]")
                    break
        
        if not primary_account:
            if preferred_account_name:
                console.print(f"[yellow]Счет '{preferred_account_name}', указанный в .env, не найден.[/yellow]")
            else:
                console.print("[yellow].env файле TOPSTEPX_ACCOUNT_NAME не указан.[/yellow]")

            console.print("[cyan]Пожалуйста, выберите счет для анализа:[/cyan]")
            for i, acc in enumerate(all_accounts):
                console.print(f"  [bold]{i + 1}[/bold]: {acc.get('name')} (Баланс: ${acc.get('balance', 0.0):,.2f})")
            
            while True:
                try:
                    choice = int(console.input("[bold]Введите номер счета: [/bold]"))
                    if 1 <= choice <= len(all_accounts):
                        primary_account = all_accounts[choice - 1]
                        break
                    else:
                        console.print("[red]Неверный номер. Попробуйте еще раз.[/red]")
                except ValueError:
                    console.print("[red]Пожалуйста, введите число.[/red]")

        account_id = primary_account["id"]
        
        # 3. Запускаем остальные запросы параллельно
        with concurrent.futures.ThreadPoolExecutor() as executor:
            end_time = datetime.utcnow()
            start_time_orders = end_time - timedelta(hours=8)
            start_time_bars = end_time - timedelta(minutes=30)

            future_positions = executor.submit(client.get_open_positions, account_id)
            future_orders = executor.submit(client.get_orders, account_id, start_time_orders, end_time)
            future_trades = executor.submit(client.get_trades, account_id, start_time_orders, end_time)
            future_bars = executor.submit(
                client.get_historical_bars, contract_id, start_time_bars, end_time,
                unit=2, unit_number=5, limit=6
            )
            
            open_positions = future_positions.result()
            orders = future_orders.result()
            trades = future_trades.result()
            bars_response = future_bars.result()

        # 4. Форматируем данные в строку
        status_lines = [f"**ҲИСОБ ҲОЛАТИ (API):**"]
        status_lines.append(f"- **Ҳисоб:** {primary_account.get('name', 'N/A')} (ID: {account_id})")
        status_lines.append(f"- **Баланс:** ${primary_account.get('balance', 0.0):,.2f}")

        # --- НОВЫЙ, НАДЕЖНЫЙ РАСЧЕТ ОТКРЫТЫХ ПОЗИЦИЙ ИЗ СДЕЛОК ---
        calculated_positions = {}
        if trades and trades.get("trades"):
            # Сортируем сделки по времени, чтобы правильно считать
            sorted_trades = sorted(trades["trades"], key=lambda x: x.get("creationTimestamp", ""))
            for trade in sorted_trades:
                contract = trade.get("contractId")
                size = trade.get("size", 0)
                side = trade.get("side", 0)
                
                # Покупка добавляет к позиции, продажа - отнимает
                position_change = size if side == 0 else -size
                
                if contract in calculated_positions:
                    calculated_positions[contract] += position_change
                else:
                    calculated_positions[contract] = position_change

        # Убираем закрытые позиции (где итоговый размер = 0)
        open_calculated_positions = {k: v for k, v in calculated_positions.items() if v != 0}

        if open_calculated_positions:
            status_lines.append(f"- **Очиқ Позициялар (ҳисобланган):** {len(open_calculated_positions)} та")
            for contract, size in open_calculated_positions.items():
                side_str = "Long" if size > 0 else "Short"
                # P&L и среднюю цену входа из этого метода получить сложно, поэтому пока опускаем
                status_lines.append(f"  - {contract}: {side_str} {abs(size)}")
        else:
            status_lines.append("- **Очиқ Позициялар:** Йўқ")

        active_orders = [o for o in orders.get("orders", []) if o.get("status") in [0, 1]] if orders else []
        if active_orders:
            status_lines.append(f"- **Актив Ордерлар:** {len(active_orders)} та")
            for order in active_orders:
                order_type = "Limit" if order.get('type', 0) == 0 else "Stop"
                side = "Buy" if order.get('side', 0) == 0 else "Sell"
                status_lines.append(f"  - {order.get('contractId')}: {side} {order_type} {order.get('size')} @ {order.get('limitPrice') or order.get('stopPrice')}")
        else:
            status_lines.append("- **Актив Ордерлар:** Йўқ")

        if trades and trades.get("trades"):
            status_lines.append(f"- **Бугунги Савдолар:** {len(trades['trades'])} та")
            for trade in trades["trades"]:
                side = "Sotish" if trade.get('side') == 1 else "Sotib olish"
                if 't' in trade:
                    trade_time = datetime.fromisoformat(trade['t'].replace('Z', '+00:00')).strftime('%H:%M:%S')
                    status_lines.append(f"  - {trade_time}: {side} {trade.get('size')} {trade.get('contractId')} @ {trade.get('price')} (ID: {trade.get('orderId')})")
        else:
            status_lines.append("- **Бугунги Савдолар:** Йўқ")
            
        status_lines.append("\n**БОЗОР МАЪЛУМОТЛАРИ (API):**")
        if bars_response and bars_response.get("bars"):
            status_lines.append(f"- **Охирги 5-дақиқалик свечалар ({contract_id}):**")
            for bar in bars_response["bars"]:
                ts = datetime.fromisoformat(bar['t'].replace('Z', '+00:00')).strftime('%H:%M')
                status_lines.append(f"  - {ts} | O: {bar['o']}, H: {bar['h']}, L: {bar['l']}, C: {bar['c']}, V: {bar['v']}")
        else:
            status_lines.append(f"- {contract_id} учун свечалар ҳақида маълумот олиб бўлмади.")

        console.print("[green]TopstepX API'дан маълумотлар муваффақиятли юкланди.[/green]")
        return "\n".join(status_lines), primary_account, open_positions, active_orders

    except Exception as e:
        console.print(f"[red]TopstepX API'дан маълумот олишда хатолик: {e}[/red]")
        return f"  - Ошибка: TopstepX API'дан маълумот олишда хатолик юз берди: {e}", None, None, None

# --- НОВОЕ ЯДРО АНАЛИЗА ("API") ---
def run_atrade_analysis(instrument_query: str, contract_symbol: str, screenshot_files: list[str]) -> str:
    """
    Выполняет полный "супер-анализ" на основе предоставленных данных.
    """
    client = TopstepXClient()

    # --- ШАГ 0: Получаем правильный ID контракта и Tick Size ---
    console.print(f"\n[blue]Поиск актуального контракта для '{contract_symbol}'...[/blue]")
    try:
        contract_info = client.search_contract(name=contract_symbol)
        if not contract_info or not contract_info.get("contracts"):
            return f"Ошибка: Не удалось найти активный контракт для символа '{contract_symbol}'."
        
        # Берем первый активный контракт из списка
        active_contract = next((c for c in contract_info["contracts"] if c.get("activeContract")), None)
        if not active_contract:
            return f"Ошибка: Не найдено активных контрактов для символа '{contract_symbol}'."

        full_contract_id = active_contract.get("id")
        tick_size = active_contract.get("tickSize")
        console.print(f"[green]Найден активный контракт: {full_contract_id} (Tick Size: {tick_size})[/green]")

    except Exception as e:
        return f"Ошибка при поиске контракта: {e}"


    # --- ШАГ 1: Сбор данных из API ---
    topstepx_data, primary_account, open_positions, active_orders = get_formatted_topstepx_data(instrument_query, full_contract_id)
    if not primary_account:
        return "Ошибка: Не удалось получить данные об аккаунте для расчета рисков."
    
    console.print(f"\n[blue]'{instrument_query}' учун янгиликлар юкланмоқда...[/blue]")
    try:
        # Для золота, делаем два отдельных запроса, чтобы получить больше новостей
        if instrument_query.lower() in ["gold", "mgc", "gc", "oltin", "zoloto"]:
            console.print("[cyan] (DXY учун ҳам янгиликлар қидирилмоқда...) [/cyan]")
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future_gold = executor.submit(get_unified_news, instrument="gold")
                future_dxy = executor.submit(get_unified_news, instrument="DXY")
                
                news_results_gold = future_gold.result()
                news_results_dxy = future_dxy.result()

            news_results = f"**Gold News:**\n{news_results_gold}\n\n**DXY (US Dollar Index) News:**\n{news_results_dxy}"
        else:
            news_results = get_unified_news(instrument=instrument_query)

    except Exception as e:
        news_results = f"Ошибка при загрузке новостей: {e}"
    console.print("[green]Янгиликлар юкланди.[/green]")

    economic_calendar_data = fetch_economic_calendar_data()

    # --- ЭТАП 1.5: Предварительный анализ сентимента ---
    news_sentiment = _get_sentiment_from_data("Новости", news_results, instrument_query)
    calendar_sentiment = _get_sentiment_from_data("Экономический календарь", economic_calendar_data, instrument_query)
    _log_market_sentiment(instrument_query, news_sentiment, calendar_sentiment)

    # --- ШАГ 2: Формирование промпта для Gemini ---
    console.print("\n[bold blue]Супер-комплекс таҳлил бошланмоқда...[/bold blue]")
    prompt = f"""Simulation. Role: experienced intraday trader. Instrument for analysis: {instrument_query}.
    Task: develop a detailed and flexible trading plan for the next 2-4 hours.
    Input data: 3 screenshots, news, economic calendar, and REAL DATA FROM THE TRADING ACCOUNT.

    **MY PRE-ANALYZED SENTIMENTS (IMPORTANT CONTEXT):**
    - News Sentiment: {news_sentiment}
    - Calendar Sentiment: {calendar_sentiment}

    **DATA FROM TRADING ACCOUNT (TopstepX API):**
    ```{topstepx_data}```

    **NEWS ({instrument_query}):**
    ```{news_results}```

    **ECONOMIC CALENDAR:**
    ```{economic_calendar_data}```

    **TASK:**

    1.  **Analysis:** Analyze **ALL** sources in English. Determine the trend, sentiment, key levels, and forecast confidence (A, B, C). **Crucially, you must consider the impact of economic calendar events from all regions (USA, Europe, Asia) and not ignore non-US news.**
    2.  **Plan A (Primary):** Formulate the primary trading plan in English (Action, Entry, Stop-Loss, Targets TP1/TP2).
    3.  **Plan B (Alternative):** Describe a brief alternative plan in English if the price moves against the primary scenario.
    4.  **Translation:** Immediately translate the complete text analysis into the Uzbek language (Cyrillic script).
    5.  **Voice Summary:** Generate a very brief summary (2-3 sentences) in the Uzbek language (Cyrillic script) for the voice assistant, voicing only the **primary plan (Plan A)**.

    **OUTPUT FORMAT:**
    Provide the response STRICTLY as a single JSON object. Do not add any text before or after the JSON.

    **EXAMPLE JSON OUTPUT:**
    ```json
    {{
      "full_analysis_english": "Full text analysis in English...",
      "full_analysis_uzbek_cyrillic": "Рус тилидаги таҳлилнинг ўзбекча (кирилл) таржимаси...",
      "trade_data": {{
        "action": "BUY",
        "forecast_strength": "B",
        "primary_entry": 2350.5,
        "stop_loss": 2335.0,
        "take_profits": {{
          "tp1": 2365.0,
          "tp2": 2380.0
        }}
      }},
      "voice_summary_uzbek_cyrillic": "Буқа сентименти. А режаси: 2350.5 дан сотиб олиш, стоп-лосс 2335. Мақсадлар: 2365 ва 2380."
    }}
    ```
    """
    try:
        image_objects = [Image.open(p) for p in screenshot_files]
        # Теперь мы ожидаем от Gemini сразу готовый JSON
        raw_response = ask_gemini_with_image(prompt, image_objects)
        
        # --- Извлечение и парсинг JSON ---
        analysis_data = None
        json_match = re.search(r'```json\n({.*?})\n```', raw_response, re.DOTALL)
        if not json_match:
            json_match = re.search(r'({.*?})', raw_response, re.DOTALL)

        if json_match:
            json_string = json_match.group(1)
            try:
                analysis_data = json.loads(json_string)
            except json.JSONDecodeError:
                console.print("[red]Ошибка декодирования JSON от Gemini. Вывод сырого ответа:[/red]")
                console.print(raw_response)
                return f"Ошибка: Невалидный JSON от Gemini: {raw_response}"
        else:
            console.print("[red]Ответ Gemini не содержит ожидаемый JSON блок. Вывод сырого ответа:[/red]")
            console.print(raw_response)
            return f"Ошибка: Ответ Gemini не в формате JSON: {raw_response}"

        if not analysis_data:
            return "Ошибка: Не удалось получить структурированные данные от Gemini."

        # --- Извлекаем данные из полученного JSON ---
        text_analysis_uzbek_cyrillic = analysis_data.get("full_analysis_uzbek_cyrillic", "Таҳлил матни топилмади.")
        voice_summary_uzbek_cyrillic = analysis_data.get("voice_summary_uzbek_cyrillic")
        trade_data = analysis_data.get("trade_data")
        
        # --- Отображение полного анализа в терминале (на узбекском, кириллица) ---
        console.print(text_analysis_uzbek_cyrillic)

        # --- Обработка и красивый вывод JSON (обновленного) ---
        if trade_data:
            console.print("\n[bold green]--- JSON Data ---[/bold green]")
            print_json(data=trade_data)
        
        # --- Озвучивание голосовой сводки (на узбекском, кириллица) ---
        if voice_summary_uzbek_cyrillic:
            console.print("\n[bold cyan]Озвучиваю краткую сводку (на узбекском, кириллица)...[/bold cyan]")
            speak_muxlisa_text(voice_summary_uzbek_cyrillic)
        else:
            console.print("[yellow]Голосовая сводка не найдена в ответе.[/yellow]")

        # --- ИНТЕРАКТИВНОЕ РАЗМЕЩЕНИЕ ОРДЕРА ---
        if trade_data:
            try:
                action = trade_data.get("action", "").upper()
                
                # --- Логика для новых ордеров ---
                if action in ["BUY", "SELL"] and trade_data.get("primary_entry"):
                    entry_price = float(trade_data["primary_entry"])
                    stop_loss = float(trade_data["stop_loss"])
                    take_profit = float(trade_data["take_profits"]["tp1"])

                    # --- РАСЧЕТ РАЗМЕРА ПОЗИЦИИ ---
                    balance = primary_account.get("balance", 0.0)
                    max_risk_for_trade = balance * 0.30  # 30% риска от баланса
                    
                    # Множитель контракта = стоимость тика / размер тика
                    contract_multiplier = active_contract.get("tickValue") / active_contract.get("tickSize")

                    metrics = calculate_trade_metrics(
                        entry_price, stop_loss, take_profit, 
                        contract_multiplier, max_risk_for_trade, contract_symbol
                    )
                    
                    if "error" in metrics:
                        console.print(f"[red]Ошибка расчета метрик: {metrics['error']}[/red]")
                        position_size = 1 # Фоллбэк на 1 контракт в случае ошибки
                    else:
                        position_size = metrics.get("position_size", 1)
                        console.print("\n[bold cyan]--- Управление Рисками ---[/bold cyan]")
                        print_json(data=metrics)

                    # --- ПРОВЕРКА И ЗАКРЫТИЕ СУЩЕСТВУЮЩИХ ПОЗИЦИЙ/ОРДЕРОВ ---
                    has_open_positions = open_positions and open_positions.get("positions")
                    has_active_orders = active_orders and len(active_orders) > 0

                    if has_open_positions or has_active_orders:
                        console.print("\n" + "="*50)
                        console.print("[bold yellow]ВНИМАНИЕ: Обнаружены активные позиции или ордера по этому инструменту![/bold yellow]")
                        if has_open_positions:
                            console.print("[yellow]  - Открытые позиции:[/yellow]")
                            for pos in open_positions["positions"]:
                                side_str = "Short" if pos.get('side') == 1 else "Long"
                                console.print(f"    - {pos.get('contractId')}: {side_str} {pos.get('size')} @ {pos.get('price')}")
                        if has_active_orders:
                            console.print("[yellow]  - Активные ордера:[/yellow]")
                            for order in active_orders:
                                order_type_str = "Limit" if order.get('type', 0) == 0 else "Stop"
                                side_str = "Buy" if order.get('side', 0) == 0 else "Sell"
                                console.print(f"    - {order.get('contractId')}: {side_str} {order_type_str} {order.get('size')} @ {order.get('limitPrice') or order.get('stopPrice')}")
                        console.print("="*50 + "\n")

                        confirmation = console.input("[bold yellow]Закрыть все открытые позиции и отменить все активные ордера по этому инструменту перед размещением нового ордера? (да/нет): [/bold yellow]").lower()

                        if confirmation in ["да", "ха", "yes", "да", "1"]:
                            console.print("[cyan]Закрытие позиций и отмена ордеров...[/cyan]")
                            
                            # --- НОВАЯ ЛОГИКА OCO ---
                            # Сначала получаем свежий список всех ордеров для поиска customTag
                            end_time = datetime.utcnow()
                            start_time = end_time - timedelta(hours=24)
                            all_orders_response = client.get_orders(primary_account["id"], start_time, end_time)
                            all_orders = all_orders_response.get("orders", []) if all_orders_response else []

                            # Закрытие открытых позиций
                            if has_open_positions:
                                for pos in open_positions["positions"]:
                                    console.print(f"[cyan]Закрытие позиции: {pos.get('contractId')} {pos.get('size')} @ Market...[/cyan]")
                                    close_side = 1 if pos.get('side') == 0 else 0 # Противоположная сторона
                                    close_result = client.place_order(
                                        contract_id=full_contract_id, account_id=primary_account["id"],
                                        side=close_side, order_type=2, size=pos.get('size'), # 2 = Market
                                        tick_size=tick_size
                                    )
                                    handle_order_result(close_result)

                                    # Ищем связанные SL/TP ордера и отменяем их
                                    original_order_id = pos.get("orderId")
                                    original_order = next((o for o in all_orders if o.get("id") == original_order_id), None)
                                    
                                    if original_order and original_order.get("customTag"):
                                        bracket_tag = original_order["customTag"]
                                        for order_to_cancel in all_orders:
                                            if order_to_cancel.get("customTag") and bracket_tag in order_to_cancel["customTag"] and order_to_cancel.get("status") == 1:
                                                console.print(f"[cyan]Отмена связанного ордера ID: {order_to_cancel.get('id')}...[/cyan]")
                                                cancel_result = client.cancel_order(account_id=primary_account["id"], order_id=order_to_cancel.get('id'))
                                                handle_order_result(cancel_result)

                            # Отмена оставшихся активных ордеров
                            if has_active_orders:
                                for order in active_orders:
                                    console.print(f"[cyan]Отмена ордера ID: {order.get('id')}...[/cyan]")
                                    cancel_result = client.cancel_order(account_id=primary_account["id"], order_id=order.get('id'))
                                    handle_order_result(cancel_result)
                        else:
                            console.print("[yellow]Открытие нового ордера отменено, так как существуют активные позиции/ордера.[/yellow]")
                            return "Открытие нового ордера отменено."


                    console.print("\n" + "="*50)
                    console.print(f"[bold yellow]ЯНГИ ОРДЕР ЖОЙЛАШТИРИШ ТАКЛИФИ[/bold yellow]")
                    console.print(f"  - Инструмент: {full_contract_id}")
                    console.print(f"  - Йўналиш: [bold green]{action}[/bold green]" if action == "BUY" else f"  - Йўналиш: [bold red]{action}[/bold red]")
                    console.print(f"  - Кириш нархи (Limit): {entry_price}")
                    console.print(f"  - Stop-Loss: {stop_loss}")
                    console.print(f"  - Take-Profit: {take_profit}")
                    console.print(f"  - Ҳажм: [bold]{int(position_size)}[/bold] контракт(ов) (Риск: ${metrics.get('total_risk_usd', 'N/A')})")

                    console.print("[bold cyan]Автоматик тасдиқлаш режими ёқилган. Ордер автоматик равишда жойлаштирилади...[/bold cyan]")
                    confirmation = "ҳа" # Автоматик тасдиқлаш

                    if confirmation in ["ҳа", "ха", "yes", "да", "1"]:
                        console.print("[cyan]Ордерни жойлаштириш учун TopstepX'га уланилмоқда...[/cyan]")
                        
                        if not primary_account:
                            console.print("[red]Ордер жойлаштириш учун ҳисоб топилмади.[/red]")
                        else:
                            order_result = client.place_order(
                                contract_id=full_contract_id, account_id=primary_account["id"],
                                side=0 if action == "BUY" else 1, order_type=0, size=int(position_size), # 0 = Limit
                                limit_price=entry_price,
                                stop_loss=stop_loss,
                                take_profit=take_profit,
                                tick_size=tick_size
                            )
                            handle_order_result(order_result)
                    else:
                        console.print("[yellow]Ордер жойлаштириш бекор қилинди.[/yellow]")

                # --- Логика для закрытия существующих позиций ---
                elif action in ["SELL_TO_CLOSE", "BUY_TO_CLOSE"]:
                    close_action = "SELL" if action == "SELL_TO_CLOSE" else "BUY"
                    
                    console.print("\n" + "="*50)
                    console.print(f"[bold yellow]ПОЗИЦИЯНИ ЁПИШ ТАКЛИФИ[/bold yellow]")
                    console.print(f"  - Инструмент: {full_contract_id}")
                    console.print(f"  - Йўналиш: [bold red]Бозор нархида {close_action}[/bold red]")
                    console.print(f"  - Ҳажм: 1 контракт (мавжуд позицияни ёпиш учун)")
                    console.print("="*50 + "\n")
                    
                    confirmation = console.input("[bold]Ушбу позицияни бозор нархида ёпайми? (ҳа/1 ёки йўқ/0): [/bold]").lower()

                    if confirmation in ["ҳа", "ха", "yes", "да", "1"]:
                        console.print("[cyan]Позицияни ёпиш учун TopstepX'га уланилмоқда...[/cyan]")
                        client = TopstepXClient()
                        primary_account = get_primary_account(client)
                        if not primary_account:
                            console.print("[red]Ордер жойлаштириш учун ҳисоб топилмади.[/red]")
                        else:
                            order_result = client.place_order(
                                contract_id=full_contract_id, account_id=primary_account["id"],
                                side=1 if action == "SELL_TO_CLOSE" else 0,
                                order_type=2, size=1 # 2 = Market
                            )
                            handle_order_result(order_result)
                    else:
                        console.print("[yellow]Позицияни ёпиш бекор қилинди.[/yellow]")
                
                else:
                    raise ValueError(f"JSON'да нотўғри 'action' қиймати: '{action}'")

            except (ValueError, KeyError, TypeError) as e:
                console.print(f"[red]Ордерни автоматик жойлаштириш учун JSON'да маълумот етарли емас ёки нотўғри: {e}[/red]")

        # --- Отправка единого, форматированного сообщения в Telegram ---
        # Убираем ЛЮБОЕ форматирование, чтобы избежать ошибок парсинга
        if trade_data:
            plan_details = [
                "⚡️ Савдо Режаси ⚡️",
                f"   - Инструмент: {full_contract_id}",
                f"   - Йўналиш: {trade_data.get('action', 'N/A')}",
                f"   - Прогноз Ишончи: {trade_data.get('forecast_strength', 'N/A')}",
                "",
                "Нуқталар:",
                f"   - Кириш: {trade_data.get('primary_entry', 'N/A')}",
                f"   - Stop-Loss: {trade_data.get('stop_loss', 'N/A')}",
                f"   - TP1: {trade_data.get('take_profits', {}).get('tp1', 'N/A')}",
                f"   - TP2: {trade_data.get('take_profits', {}).get('tp2', 'N/A')}",
            ]
            plan_text = "\n".join(plan_details)
            telegram_message_uzbek_cyrillic = f"{text_analysis_uzbek_cyrillic}\n\n{plan_text}"
        else:
            telegram_message_uzbek_cyrillic = text_analysis_uzbek_cyrillic

        # Отправляем как обычный текст, без parse_mode
        send_long_telegram_message(telegram_message_uzbek_cyrillic)
        
        # --- ВЫЗОВ НОВОЙ ФУНКЦИИ ЛОГИРОВАНИЯ ---
        _log_atrade_summary(instrument_query, analysis_data)

        return telegram_message_uzbek_cyrillic
    except Exception as e:
        error_msg = f"Произошла ошибка при анализе: {e}"
        console.print(f"[red]{error_msg}[/red]")
        return error_msg

def get_primary_account(client: TopstepXClient):
    """Вспомогательная функция для получения основного счета."""
    accounts_response = client.get_account_list()
    if not accounts_response or not accounts_response.get("accounts"):
        return None
    preferred_account_name = os.environ.get("TOPSTEPX_ACCOUNT_NAME")
    return next((acc for acc in accounts_response["accounts"] if acc.get("name") == preferred_account_name), accounts_response["accounts"][0])

def handle_order_result(order_result):
    """Вспомогательная функция для обработки ответа от API после размещения ордера."""
    if order_result and order_result.get("success"):
        console.print("[bold green]✅ Ордер муваффақиятли жойлаштирилди![/bold green]")
        print_json(data=order_result)
    else:
        console.print("[bold red]❌ Ордер жойлаштиришда хатолик юз берди.[/bold red]")
        if order_result:
            print_json(data=order_result)

# --- НОВАЯ ФУНКЦИЯ ДЛЯ АНАЛИЗА СЕНТИМЕНТА ---
def _get_sentiment_from_data(data_type: str, data_content: str, instrument: str) -> str:
    """
    Получает мнение (сентимент) от Gemini по поводу новостей или данных календаря.
    """
    console.print(f"\n[blue]Анализ сентимента для '{data_type}' по инструменту '{instrument}'...[/blue]")
    if not data_content or data_content.strip() == "Свежих новостей не найдено.":
        return "Значимых данных для анализа сентимента не найдено."
        
    try:
        prompt = f"""
        Проанализируй следующие данные для инструмента '{instrument}'.
        Тип данных: {data_type}
        Содержание данных:
        ---
        {data_content}
        ---
        Задача: Дай краткий анализ сентимента на русском языке (2-3 предложения).
        Какой общий сентимент: Бычий, Медвежий или Нейтральный?
        Назови 1-2 ключевых фактора, влияющих на этот сентимент.
        """
        response = ask_gemini_text_only(prompt)
        
        if isinstance(response, dict) and (response.get("message") or response.get("explanation")):
            sentiment_analysis = response.get("message") or response.get("explanation")
        else:
            sentiment_analysis = str(response)

        console.print(f"[green]Сентимент для '{data_type}' получен.[/green]")
        return sentiment_analysis.strip()
    except Exception as e:
        error_msg = f"Ошибка при анализе сентимента для '{data_type}': {e}"
        console.print(f"[red]{error_msg}[/red]")
        return error_msg

# --- НОВАЯ ФУНКЦИЯ ЛОГИРОВАНИЯ СЕНТИМЕНТА ---
def _log_market_sentiment(instrument: str, news_sentiment: str, calendar_sentiment: str):
    """
    Сохраняет сентимент по новостям и календарю в лог-файл.
    """
    try:
        instrument_dir = Path("/Users/macbook/projects/jr/jafar_unified/memory") / instrument.lower()
        instrument_dir.mkdir(parents=True, exist_ok=True)
        log_file = instrument_dir / "market_sentiment_log.md"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_entry = f"""
---
date: '{timestamp}'
instrument: {instrument.upper()}
tags:
- sentiment_analysis
---

**Мнение по новостям:**
{news_sentiment}

**Мнение по экономическому календарю:**
{calendar_sentiment}
"""
        with log_file.open("a", encoding="utf-8") as f:
            f.write(log_entry)
        
        console.print(f"[dim green]Сентимент '{instrument.upper()}' учун 'memory'га сақланди.[/dim green]")

    except Exception as e:
        console.print(f"[red]Сентимент лог файлига ёзишда хатолик: {e}[/red]")

# --- СТАРЫЙ ОБРАБОТЧИК КОМАНД (ТЕПЕРЬ ИСПОЛЬЗУЕТ "API") ---
def atrade_command(args: str = None):
    """Интерактивная оболочка для запуска супер-анализа."""
    
    console.print(f"[bold blue][DEBUG] atrade_command received args: '{args}'[/bold blue]")

    instrument_map = {
        # Oltin (теперь по умолчанию MGC)
        "gold": "MGC", "mgc": "MGC", "oltin": "MGC", "zoloto": "MGC",
        # Явно указываем GC для большого контракта
        "gc": "GC",
        # Neft
        "oil": "CL", "cl": "CL", "neft": "CL",
        # S&P 500
        "s&p": "ES", "es": "ES", "sipi": "ES",
        # NASDAQ
        "nasdaq": "NQ", "nq": "NQ",
        # Bitcoin
        "bitcoin": "BTC", "btc": "BTC", "bitkoin": "BTC",
        # Ethereum
        "ethereum": "ETH", "eth": "ETH", "efir": "ETH",
        # Valyutalar
        "evro": "EURUSD", "eurusd": "EURUSD",
        "frank": "USDCHF", "usdchf": "USDCHF",
        "pound": "GBPUSD", "gbpusd": "GBPUSD",
    }
    
    screenshot_files = []
    instrument_query = None
    contract_id = None

    if args:
        parts = shlex.split(args)
        instrument_query = parts[0].lower()
        console.print(f"[bold blue][DEBUG] Parsed instrument_query: '{instrument_query}'[/bold blue]")
    
    if not instrument_query:
        instrument_query = console.input("[bold yellow]Инструмент номини киритинг (масалан, gold, oil, es): [/bold yellow]").lower()

    if not instrument_query:
        console.print("[red]Инструмент номи киритилмади. Таҳлил тўхтатилди.[/red]"); return

    contract_id = instrument_map.get(instrument_query)
    console.print(f"[bold blue][DEBUG] Looked up '{instrument_query}' in instrument_map. Result: '{contract_id}'[/bold blue]")

    if not contract_id:
        console.print(f"[red]'{instrument_query}' учун API тикери топилмади. Луғатни текширинг.[/red]"); return

    console.print(f"[cyan]Таҳлил учун танланди: {instrument_query.capitalize()} (API Ticker: {contract_id})[/cyan]")
    console.print("[yellow]Интерактив скриншот олиш режими...[/yellow]")
    
    timestamp_folder = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_QTrade_CLI")
    current_batch_dir = SCREENSHOT_DIR / timestamp_folder
    current_batch_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        console.print(f"\n[cyan]Скриншот #{i + 1}/3 учун тайёрланинг (3 сония)...[/cyan]")
        time.sleep(3)
        path = current_batch_dir / f"screenshot_{i + 1}.png"
        os.system(f'screencapture -w "{str(path)}"')
        if not path.exists() or path.stat().st_size == 0:
            console.print("[red]Скриншот олиш бекор қилинди.[/red]"); return
        console.print(f"[green]Скриншот #{i + 1} сақланди.[/green]")
        screenshot_files.append(str(path))

    if len(screenshot_files) == 3:
        # Вызываем новое ядро анализа с обоими именами
        return run_atrade_analysis(instrument_query, contract_id, screenshot_files)
    else:
        msg = "3 та скриншот олишнинг иложи бўлмади."
        console.print(f"[red]{msg}[/red]")
        return msg
