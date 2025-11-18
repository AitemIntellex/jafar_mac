from .muxlisa_voice_output_handler import speak_muxlisa_text
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from rich.console import Console
from rich import print_json
from rich.panel import Panel # Добавляем импорт Panel
from PIL import Image
import io
import sys
import re
import json
import shlex
import concurrent.futures
import yaml  # Импортируем новую библиотеку
from jafar.utils.gemini_api import ask_gemini_with_image, ask_gemini_text_only

console = Console()
SCREENSHOT_DIR = Path("screenshot")
MEMORY_BASE_DIR = Path("/Users/macbook/projects/jr/jafar_unified/memory")

# --- ОБНОВЛЕННАЯ ФУНКЦИЯ ПРОВЕРКИ ВРЕМЕНИ РАБОТЫ РЫНКА ---
def _check_market_hours(instrument_query: str) -> str:
    """
    Проверяет статус рынка для данного инструмента, используя UTC.
    Возвращает "OPEN", "CLOSED", или "CRYPTO".
    """
    instrument_query = instrument_query.lower()
    
    crypto_keywords = ["btc", "bitcoin", "eth", "ethereum"]
    if any(keyword in instrument_query for keyword in crypto_keywords):
        return "CRYPTO"

    # --- Логика для традиционных рынков (CME Globex) на основе UTC ---
    now_utc = datetime.utcnow()
    weekday = now_utc.weekday()  # 0=Пн, 4=Пт, 5=Сб, 6=Вс
    hour = now_utc.hour

    # Рынок закрыт с 21:00 UTC пятницы до 22:00 UTC воскресенья
    is_closed = (weekday == 4 and hour >= 21) or \
                (weekday == 5) or \
                (weekday == 6 and hour < 22)

    if is_closed:
        return "CLOSED"
    
    return "OPEN"

# --- ФУНКЦИИ ЛОГИРОВАНИЯ (без изменений) ---

def _log_market_sentiment(instrument: str, news_sentiment: str, calendar_sentiment: str):
    """Сохраняет сентимент в лог-файл с YAML Front Matter."""
    try:
        instrument_dir = MEMORY_BASE_DIR / instrument.lower()
        instrument_dir.mkdir(parents=True, exist_ok=True)
        log_file = instrument_dir / "market_sentiment_log.md"
        
        timestamp = datetime.now()

        metadata = {
            'date': timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            'instrument': instrument.upper(),
            'tags': ['sentiment_analysis']
        }
        yaml_front_matter = yaml.dump(metadata, default_flow_style=False, allow_unicode=True)

        log_content = f"""
**Мнение по новостям:**
{news_sentiment}

**Мнение по экономическому календарю:**
{calendar_sentiment}
"""
        
        log_entry = f"---\n{yaml_front_matter}---\n{log_content}"

        with log_file.open("a", encoding="utf-8") as f:
            f.write(log_entry)
        console.print(f"[dim green]Сентимент рынка для '{instrument.upper()}' сохранен в 'memory/{instrument.lower()}'.[/dim green]")

    except Exception as e:
        console.print(f"[red]Ошибка при записи в лог сентимента: {e}[/red]")


def _log_atrade_summary(instrument: str, analysis_data: dict):
    """Сохраняет краткую сводку анализа в лог-файл с YAML Front Matter."""
    try:
        instrument_dir = MEMORY_BASE_DIR / instrument.lower()
        instrument_dir.mkdir(parents=True, exist_ok=True)
        log_file = instrument_dir / "atrade_analysis_log.md"

        timestamp = datetime.now()
        
        # --- Извлечение данных из нового/старого формата ---
        plan_a_data = analysis_data.get("plan_a_primary", analysis_data.get("trade_data", {}))
        
        # --- Очистка и извлечение числовых значений ---
        def clean_and_extract_float(raw_value):
            if raw_value is None: return None
            match = re.search(r'(\d+\.?\d*)', str(raw_value))
            return float(match.group(1)) if match else None

        # --- Формирование метаданных для YAML ---
        metadata = {
            'date': timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            'instrument': instrument.upper(),
            'sentiment': analysis_data.get('sentiment'),
            'strategy': plan_a_data.get('strategy_name'),
            'key_event': analysis_data.get('key_event'),
            'tags': analysis_data.get('tags', []),
            'plan': {
                'action': plan_a_data.get('action'),
                'entry': clean_and_extract_float(plan_a_data.get('entry')),
                'stop_loss': clean_and_extract_float(plan_a_data.get('stop_loss')),
                'tp1': clean_and_extract_float(plan_a_data.get('take_profit_1'))
            }
        }
        yaml_front_matter = yaml.dump(metadata, default_flow_style=False, allow_unicode=True)

        # --- Формирование основного текста лога ---
        full_analysis_text = analysis_data.get("full_analysis_uzbek_cyrillic", "Таҳлил матни мавжуд эмас.")
        
        log_content = ""
        if isinstance(full_analysis_text, str):
            log_content = full_analysis_text
        elif isinstance(full_analysis_text, dict):
            error_message = full_analysis_text.get('error', full_analysis_text.get('message', str(full_analysis_text)))
            log_content = f"### ОШИБКА АНАЛИЗА\n{error_message}"
        else:
            log_content = str(full_analysis_text)

        log_entry = f"---\n{yaml_front_matter}---\n\n{log_content}\n"

        with log_file.open("a", encoding="utf-8") as f:
            f.write(log_entry)
        
        console.print(f"[dim green]Анализ '{instrument.upper()}' учун хулоса 'memory/{instrument.lower()}'га сақланди.[/dim green]")

    except Exception as e:
        console.print(f"[red]Лог файлига ёзишда хатолик: {e}[/red]")


# --- НОВАЯ ФУНКЦИЯ ЗАГРУЗКИ ПАМЯТИ ---
def _load_memory_for_prompt(instrument: str, num_entries: int = 3) -> str:
    """
    Загружает последние записи из лога анализа для указанного инструмента
    и форматирует их в виде строки для промпта.
    """
    console.print(f"[cyan]Загрузка памяти для '{instrument.upper()}'...[/cyan]")
    instrument_dir = MEMORY_BASE_DIR / instrument.lower()
    log_file = instrument_dir / "atrade_analysis_log.md"

    if not log_file.exists():
        return "Предыдущий анализ в памяти не найден."

    memory_lines = ["Вот краткая сводка моих предыдущих анализов (моя память):"]
    
    try:
        with log_file.open("r", encoding="utf-8") as f:
            content = f.read()
        
        entries = content.split('---')
        recent_entries = [entry for entry in entries if entry.strip()][-num_entries:]

        for entry in recent_entries:
            try:
                metadata = yaml.safe_load(entry)
                if not metadata: continue

                date = metadata.get('date', 'N/A')
                plan = metadata.get('plan', {})
                action = plan.get('action', 'N/A')
                sentiment = metadata.get('sentiment', 'N/A')
                strategy = metadata.get('strategy', 'N/A')
                
                summary = f"- {date}: Сентимент был '{sentiment}'. Основная стратегия: '{strategy}', План: {action}."
                memory_lines.append(summary)

            except yaml.YAMLError:
                continue
    except Exception as e:
        console.print(f"[red]Ошибка при чтении файла памяти: {e}[/red]")
        return "Ошибка при чтении памяти."

    if len(memory_lines) == 1: # Только заголовок
        return "Предыдущий анализ в памяти не найден."

    console.print(f"[green]Память успешно загружена. Найдено {len(memory_lines) - 1} записей.[/green]")
    return "\n".join(memory_lines)


# --- ЯДРО АНАЛИЗА ---
from jafar.utils.news_api import get_unified_news
from jafar.utils.topstepx_api_client import TopstepXClient
from .telegram_handler import send_telegram_media_group, send_long_telegram_message
from .economic_calendar_fetcher import fetch_economic_calendar_data
from .muxlisa_voice_output_handler import speak_muxlisa_text

def run_atrade_analysis(instrument_query: str, contract_id: str, screenshot_files: list[str]) -> str:
    """
    Выполняет полный "супер-анализ" с генерацией метаданных.
    """
    # --- ЭТАП 1.2: Сбор новостей из Marketaux ---
    console.print(f"\n[blue]'{instrument_query}' учун янгиликлар юкланмоқда (Marketaux)...[/blue]")
    
    try:
        news_results = get_unified_news(instrument=instrument_query)
    except Exception as e:
        news_results = f"Ошибка при загрузке новостей из Marketaux: {e}"

    console.print("[green]Янгиликлар юкланди.[/green]")

    # --- ЭТАП 1.3: Сбор данных экономического календаря ---
    economic_calendar_data = fetch_economic_calendar_data()

    # --- ЭТАП 1.5: Предварительный анализ сентимента ---
    news_sentiment = _get_sentiment_from_data("Новости", news_results, instrument_query)
    calendar_sentiment = _get_sentiment_from_data("Экономический календарь", economic_calendar_data, instrument_query)
    _log_market_sentiment(instrument_query, news_sentiment, calendar_sentiment)

    # --- ЭТАП 1.7: Загрузка памяти для промпта ---
    memory_summary = _load_memory_for_prompt(instrument_query)
    
    topstepx_data = "TopstepX API data is not available at the moment."

    # --- ШАГ 2: Формирование основного промпта для Gemini ---
    console.print("\n[bold blue]Основной комплексный анализ...[/bold blue]")
    prompt = f"""
    Simulation. Role: experienced intraday trader. Instrument for analysis: {instrument_query}.
    Task: develop a detailed and flexible trading plan and generate structured metadata.
    Input data: my memory of previous analyses, 3 screenshots, news from Marketaux, calendar, trading account data, and my pre-analyzed sentiments.

    **PREVIOUS ANALYSIS SUMMARY (MY MEMORY):**
    {memory_summary}

    **MY PRE-ANALYZED SENTIMENTS (IMPORTANT CONTEXT):**
    - News Sentiment: {news_sentiment}
    - Calendar Sentiment: {calendar_sentiment}

    **DATA FROM TRADING ACCOUNT (TopstepX API):**
    ```{topstepx_data}```

    **NEWS (FROM SPECIALIZED SOURCE - Marketaux):**
    ```{news_results}```

    **ECONOMIC CALENDAR:**
    ```{economic_calendar_data}```

    **TASK:**

    1.  **Analysis:** Analyze **ALL** sources in English. Determine the trend, sentiment, key levels, and forecast confidence (A, B, C).
    2.  **Plan A (Primary):** Formulate the primary trading plan in English (Action, Entry, Stop-Loss, Targets TP1/TP2).
    3.  **Plan B (Alternative):** Describe a brief alternative plan in English if the price moves against the primary scenario.
    4.  **Trade Management:** Provide a detailed plan for managing the trade *after* entry. Specify the price level at which the stop-loss should be moved to break-even. Suggest a price for taking partial profits (e.g., at TP1) and what percentage of the position to close.
    5.  **Translation:** Immediately translate the complete text analysis AND the trade management plan into the Uzbek language (Cyrillic script).
    6.  **Voice Summary:** Generate a very brief summary (2-3 sentences) in the Uzbek language (Cyrillic script) for the voice assistant, voicing only the **primary plan (Plan A)**.

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
        }},
        "trade_management": {{
            "move_sl_to_be_price": 2365.0,
            "partial_tp_price": 2365.0,
            "partial_tp_percentage": 50,
            "management_summary_uzbek_cyrillic": "ТП1 (2365.0) га етганда, стоп-лоссни кириш нуқтасига (2350.5) кўчиринг ва позициянинг 50%ини ёпинг."
        }}
      }},
      "voice_summary_uzbek_cyrillic": "Буқа сентименти. А режаси: 2350.5 дан сотиб олиш, стоп-лосс 2335. Мақсадлар: 2365 ва 2380.",
      "metadata": {{
          "sentiment": "Bullish",
          "strategy": "Trend Continuation",
          "key_event": "Anticipation of US CPI data",
          "tags": ["bullish_trend", "support_bounce", "moving_average", "gold_futures"]
      }}
    }}
    ```
    """
    try:
        image_objects = [Image.open(p) for p in screenshot_files]
        raw_response = ask_gemini_with_image(prompt, image_objects)
        
        analysis_data = None
        json_match = re.search(r'```json\n({.*?})\n```', raw_response, re.DOTALL)
        if not json_match:
            json_match = re.search(r'({.*?})', raw_response, re.DOTALL)

        if json_match:
            json_string = json_match.group(1)
            try:
                analysis_data = json.loads(json_string)
            except json.JSONDecodeError:
                console.print("[red]Ошибка декодирования JSON от Gemini.[/red]")
                return f"Ошибка: Невалидный JSON от Gemini: {raw_response}"
        else:
            console.print("[red]Ответ Gemini не содержит ожидаемый JSON.[/red]")
            return f"Ошибка: Ответ Gemini не в формате JSON: {raw_response}"

        if not analysis_data:
            return "Ошибка: Не удалось получить структурированные данные от Gemini."

        # --- Логируем результат с новыми метаданными ---
        _log_atrade_summary(instrument_query, analysis_data)

        # ... (остальная часть функции: вывод в консоль, озвучка, отправка в Telegram - без изменений) ...
        
        text_analysis_uzbek_cyrillic = analysis_data.get("full_analysis_uzbek_cyrillic", "Таҳлил матни топилмади.")
        console.print(text_analysis_uzbek_cyrillic)
        # ... и так далее ...

        return "Анализ завершен и сохранен с метаданными."
    except Exception as e:
        error_msg = f"Произошла ошибка при анализе: {e}"
        console.print(f"[red]{error_msg}[/red]")
        return error_msg

# --- ОБРАБОТЧИК КОМАНД (без изменений) ---
def atrade_pro_command(args: str = None):
    """Интерактивная оболочка для запуска продвинутого анализа."""
    
    instrument_map = { "gold": "GC", "gc": "GC", "oil": "CL", "cl": "CL", "es": "ES", "nq": "NQ", "eurusd": "EURUSD" }
    
    instrument_query = None
    if args:
        instrument_query = shlex.split(args)[0].lower()
    
    if not instrument_query:
        instrument_query = console.input("[bold yellow]Инструмент для анализа (gold, oil, eurusd): [/bold yellow]").lower()

    if not instrument_query:
        console.print("[red]Инструмент не указан.[/red]"); return

    # --- ИНТЕРАКТИВНАЯ ПРОВЕРКА ВРЕМЕНИ РАБОТЫ РЫНКА ---
    market_status = _check_market_hours(instrument_query)
    
    if market_status == "CLOSED":
        console.print(Panel(f"[bold yellow]Бозор ёпиқ:[/bold yellow] '{instrument_query.capitalize()}' учун бозорлар ҳозирда ишламаяпти.", title="Jafar - Бозор Соати", style="yellow"))
        user_choice = console.input("Шунга қарамай таҳлилни давом эттирайми? (ҳа/йўқ): ").lower()
        if user_choice not in ["ҳа", "ха", "yes", "y", "1"]:
            console.print("[dim]Таҳлил бекор қилинди.[/dim]")
            return

    contract_id = instrument_map.get(instrument_query)
    if not contract_id:
        console.print(f"[red]Инструмент '{instrument_query}' не поддерживается.[/red]"); return

    console.print(f"[cyan]Анализ для: {instrument_query.capitalize()} (API Ticker: {contract_id})[/cyan]")
    console.print("[yellow]Режим интерактивного скриншота...[/yellow]")
    
    screenshot_files = []
    current_batch_dir = SCREENSHOT_DIR / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    current_batch_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        console.print(f"\n[cyan]Приготовьтесь к скриншоту #{i + 1}/3 (3 секунды)...[/cyan]")
        time.sleep(3)
        path = current_batch_dir / f"screenshot_{i + 1}.png"
        os.system(f'screencapture -w "{str(path)}"')
        if not path.exists() or path.stat().st_size == 0:
            console.print("[red]Скриншот отменен.[/red]"); return
        console.print(f"[green]Скриншот #{i + 1} сохранен.[/green]")
        screenshot_files.append(str(path))

    if len(screenshot_files) == 3:
        return run_atrade_analysis(instrument_query, contract_id, screenshot_files)
    else:
        msg = "Не удалось сделать 3 скриншота."
        console.print(f"[red]{msg}[/red]")
        return msg

# --- Вспомогательные функции (без изменений) ---
def _get_sentiment_from_data(data_type: str, data_content: str, instrument: str) -> str:
    """
    Получает мнение (сентимент) от Gemini по поводу новостей или данных календаря.
    """
    console.print(f"\n[blue]Анализ сентимента для '{data_type}' по инструменту '{instrument}'...[/blue]")
    if not data_content or data_content.strip() == "Свежих новостей не найдено.":
        # Если данных нет, явно сообщаем об этом Gemini, чтобы он мог учесть это в анализе
        data_content_for_gemini = f"Таҳлил учун аниқ {data_type.lower()} тақдим этилмаган."
    else:
        data_content_for_gemini = data_content
        
    try:
        prompt = f"""
        Проанализируй следующие данные для инструмента '{instrument}'.
        Тип данных: {data_type}
        Содержание данных:
        ---
        {data_content_for_gemini}
        ---
        Задача: Дай краткий анализ сентимента на русском языке (2-3 предложения).
        Какой общий сентимент: Бычий, Медвежий или Нейтральный?
        Назови 1-2 ключевых фактора, влияющих на этот сентимент.
        """
        # Используем ask_gemini_text_only, так как изображения здесь не нужны
        response = ask_gemini_text_only(prompt)
        
        # Извлекаем сообщение из возможного словарного ответа
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