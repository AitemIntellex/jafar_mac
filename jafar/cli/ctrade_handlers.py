import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print_json
from PIL import Image
import io
import sys
import re
import json
import shlex
import subprocess
import concurrent.futures
from typing import Optional

from jafar.utils.gemini_api import ask_gemini_with_image
from jafar.utils.news_api import get_unified_news, get_news_from_newsapi
from jafar.utils.topstepx_api_client import TopstepXClient
from .telegram_handler import send_long_telegram_message
from .economic_calendar_fetcher import fetch_economic_calendar_data
from jafar.utils.market_utils import get_current_trading_session
from .muxlisa_voice_output_handler import speak_muxlisa_text, speak_in_chunks
from jafar.utils.text_utils import convert_numbers_to_words_in_text

console = Console()
SCREENSHOT_DIR = Path("screenshot")
KEY_LEVELS_FILE = Path("memory/key_levels.json")

KEY_LEVELS_FILE = Path("memory/key_levels.json")

def save_key_levels_to_memory(instrument: str, trade_data: dict):
    """Saves key levels from trade_data to memory/key_levels.json."""
    if not trade_data:
        return

    source_id = f"ctrade-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    new_levels = []
    
    action = trade_data.get("action", "UNKNOWN")

    if entry := trade_data.get("entry_price"):
        level_type = f"ENTRY_{action.upper()}"
        new_levels.append({"level": float(entry), "type": level_type, "source_id": source_id, "status": "active"})
    
    if sl := trade_data.get("stop_loss"):
        new_levels.append({"level": float(sl), "type": "STOP_LOSS", "source_id": source_id, "status": "active"})
        
    if tps := trade_data.get("take_profits"):
        for i, (tp_name, tp_level) in enumerate(tps.items()):
            new_levels.append({"level": float(tp_level), "type": f"TAKE_PROFIT_{i+1}", "source_id": source_id, "status": "active"})

    if not new_levels:
        console.print("[yellow]Saqlash uchun yangi darajalar topilmadi.[/yellow]")
        return

    try:
        if KEY_LEVELS_FILE.exists() and KEY_LEVELS_FILE.stat().st_size > 0:
            with open(KEY_LEVELS_FILE, 'r', encoding='utf-8') as f:
                memory_data = json.load(f)
        else:
            memory_data = {}

        if instrument not in memory_data:
            memory_data[instrument] = []

        # Avoid adding duplicate levels based on level value (simple check)
        existing_levels = {lvl['level'] for lvl in memory_data[instrument]}
        for new_level in new_levels:
            if new_level['level'] not in existing_levels:
                memory_data[instrument].append(new_level)
                existing_levels.add(new_level['level'])

        with open(KEY_LEVELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)
        
        console.print(f"[bold green]✅ {len(new_levels)} ta yangi daraja {instrument} uchun xotiraga saqlandi.[/bold green]")

    except (IOError, json.JSONDecodeError) as e:
        console.print(f"[red]Xotira fayliga darajalarni saqlashda xatolik: {e}[/red]")


# --- UTILITIES & CONSTANTS (from atrade) ---
MAX_CONTRACTS_MAP = {"MGC": 50, "GC": 5, "CL": 10, "ES": 10}

def calculate_trade_metrics(entry_price, stop_loss, take_profit, contract_multiplier, max_risk_for_trade, contract_symbol: str):
    risk_per_unit = abs(entry_price - stop_loss)
    if risk_per_unit == 0: return {"error": "Risk per unit is zero."}
    risk_per_contract = risk_per_unit * contract_multiplier
    if risk_per_contract == 0: return {"error": "Risk per contract is zero."}
    max_contracts_for_instrument = MAX_CONTRACTS_MAP.get(contract_symbol, 1)
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
    }

def get_formatted_topstepx_data(instrument_query: str, contract_id: str) -> tuple[str, dict, dict]:
    try:
        client = TopstepXClient()
        accounts_response = client.get_account_list()
        if not accounts_response or not accounts_response.get("accounts"):
            return "  - Error: Could not get account list from TopstepX.", None, None
        
        all_accounts = accounts_response["accounts"]
        primary_account = next((acc for acc in all_accounts if acc.get("name") == os.environ.get("TOPSTEPX_ACCOUNT_NAME2")), all_accounts[0])
        account_id = primary_account["id"]
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=8)
            future_real_positions = executor.submit(client.get_open_positions, account_id)
            future_trades = executor.submit(client.get_trades, account_id, start_time, end_time)
            
            real_positions_response = future_real_positions.result()
            trades = future_trades.result()

        status_lines = [f"**ACCOUNT STATUS ({primary_account.get('name')}):**", f"- **Balance:** ${primary_account.get('balance', 0.0):,.2f}"]
        
        open_positions_with_side = {}
        real_open_positions = real_positions_response.get("positions", [])
        if real_open_positions:
            if trades and trades.get("trades"):
                sorted_trades = sorted(trades["trades"], key=lambda x: x.get("creationTimestamp", ""))
                temp_positions = {}
                for trade in sorted_trades:
                    contract = trade.get("contractId")
                    size = trade.get("size", 0)
                    side = trade.get("side", 0) # 0 = Buy, 1 = Sell
                    position_change = size if side == 0 else -size
                    temp_positions[contract] = temp_positions.get(contract, 0) + position_change
                
                for real_pos in real_open_positions:
                    contract = real_pos.get("contractId")
                    if temp_positions.get(contract) is not None:
                         open_positions_with_side[contract] = temp_positions[contract]

            for contract, size in open_positions_with_side.items():
                side_str = "Long" if size > 0 else "Short"
                status_lines.append(f"  - {contract}: {side_str} {abs(size)}")
        else:
            status_lines.append("- **Open Positions:** None")
        
        return "\n".join(status_lines), primary_account, open_positions_with_side

    except Exception as e:
        return f"  - Error: {e}", None, None

def start_escort_agent(order_id: int, account_id: int, contract_id: str, expected_side: str):
    """Запускает trade_escort_agent.py в фоновом режиме."""
    console.print(f"\n[bold magenta]🚀 Order #{order_id} uchun fon agentini ishga tushirish...[/bold magenta]")
    
    agent_script_path = Path(__file__).parent.parent / "monitors" / "trade_escort_agent.py"
    python_executable = sys.executable
    
    command = [
        python_executable, str(agent_script_path),
        "--order-id", str(order_id),
        "--account-id", str(account_id),
        "--contract-id", contract_id,
        "--expected-side", expected_side,
    ]

    try:
        subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        console.print(f"[green]✅ Order #{order_id} uchun agent muvaffaqiyatli ishga tushirildi.[/green]")
        speak_muxlisa_text("Agent 001 ishga tushirildi.")
    except Exception as e:
        console.print(f"[red]❌ Fon agentini ishga tushirib bo'lmadi: {e}[/red]")
        send_long_telegram_message(f"🚨 **CRITICAL: Agent Start Failed**\nOrder ID: #{order_id}\nError: {e}")


def handle_order_result(order_result, account_id, contract_id, expected_side, order_type: int):
    """Обрабатывает результат размещения ордера и запускает агент, если нужно."""
    if order_result and order_result.get("success"):
        console.print("[bold green]✅ Buyurtma muvaffaqiyatli joylashtirildi![/bold green]")
    else:
        console.print("[bold red]❌ Buyurtma joylashtirishda xatolik.[/bold red]")
        
    if order_result:
        print_json(data=order_result)
        order_id = order_result.get("orderId")
        # Запускаем агент только для Limit и Stop ордеров, которые требуют ожидания
        if order_id and order_type in [1, 4]: # 1=Limit, 4=Stop
            start_escort_agent(order_id, account_id, contract_id, expected_side)

def _extract_and_parse_json(raw_text: str) -> dict:
    """Finds and parses a JSON block from a raw string, with improved robustness."""
    # 1. Try to find a ```json block
    json_code_block_match = re.search(r'```json\n({.*?})\n```', raw_text, re.DOTALL)
    if json_code_block_match:
        try:
            return json.loads(json_code_block_match.group(1))
        except json.JSONDecodeError as e:
            console.print(f"[dim yellow]JSON в кодовом блоке невалиден: {e}[/dim yellow]")

    # 2. Try to find the outermost JSON object
    outer_json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if outer_json_match:
        try:
            return json.loads(outer_json_match.group(0))
        except json.JSONDecodeError as e:
            console.print(f"[dim yellow]Внешний JSON-объект невалиден: {e}[/dim yellow]")

    # 3. Fallback: try parsing the whole raw_text as JSON
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Не удалось распарсить JSON из ответа: {e}") from e

def run_ctrade_analysis(instrument_query: str, contract_symbol: str, screenshot_files: list[str]) -> dict:
    client = TopstepXClient()
    try:
        contract_info = client.search_contract(name=contract_symbol)
        active_contract = next((c for c in contract_info["contracts"] if c.get("activeContract")), None)
        if not active_contract: return {"status": "Ошибка", "full_analysis": f"Xatolik: '{contract_symbol}' uchun faol kontrakt topilmadi."}
        full_contract_id = active_contract.get("id")
        tick_size = active_contract.get("tickSize")
    except Exception as e:
        return {"status": "Ошибка", "full_analysis": f"Kontrakt qidirishda xatolik: {e}"}

    topstepx_data, primary_account, open_calculated_positions = get_formatted_topstepx_data(instrument_query, full_contract_id)
    if not primary_account:
        return {"status": "Ошибка", "full_analysis": "Xatolik: Riskni hisoblash uchun hisob ma'lumotlarini olib bo'lmadi."}

    current_position_size = open_calculated_positions.get(full_contract_id, 0)
    image_objects = [Image.open(p) for p in screenshot_files]
    current_session = get_current_trading_session()
    
    news_results, economic_calendar_data = "", ""
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_news = executor.submit(get_unified_news)
        future_calendar = executor.submit(fetch_economic_calendar_data)
        news_results = future_news.result()
        economic_calendar_data = future_calendar.result()

    if current_position_size != 0:
        position_side = "Long" if current_position_size > 0 else "Short"
        prompt = f"**MODE: OPEN POSITION MANAGEMENT**..." # Simplified for brevity
    else:
        prompt = f'''
        **TOIFA:** Savdo tahlili va reja tuzish.
        **MAQSAD:** Taqdim etilgan barcha ma'lumotlar (skrinshotlar, hisob holati, yangiliklar, kalendar) asosida `{instrument_query}` uchun savdo rejasini ishlab chiqish.

        **KIRISH MA'LUMOTLARI:**
        - **Instrument:** {instrument_query}
        - **Joriy sessiya:** {current_session}
        - **Hisob holati:** ```{topstepx_data}```
        - **Yangiliklar lentasi:** ```{news_results}```
        - **Iqtisodiy kalendar:** ```{economic_calendar_data}```

        **TOPSHIRIQ:**
        Barcha ma'lumotlarni kompleks tahlil qilib, quyidagi formatda YAGONA va TO'LIQ JSON obyektini qaytar.

        **CHIQISH FORMATI (FAQAT JSON):**
        ```json
        {{
          "full_analysis_uzbek_cyrillic": "Bu yerda to'liq, batafsil va chiroyli formatlangan tahlil matni bo'lishi kerak. Trend, sentiment, asosiy narx darajalari va prognozning ishonchliligi (A, B, C) kabi barcha jihatlarni o'z ichiga olsin.",
          "trade_data": {{
            "action": "BUY",
            "forecast_strength": "B",
            "risk_percent": 5.0,
            "order_type": "LIMIT",
            "entry_price": 2350.5,
            "stop_loss": 2335.0,
            "take_profits": {{
              "tp1": 2365.0,
              "tp2": 2380.0
            }}
          }},
          "voice_summary_uzbek_latin": "Bu yerda ovozli yordamchi uchun qisqa, aniq va tabiiy eshitiladigan o'zbek (lotin) tilidagi xulosa bo'lishi kerak."
        }}
        ```
        **ДИҚҚАТ:** Жавоб ФАҚАТ ва ФАҚАТ JSON форматида бўлиши шарт. Ҳеч қандай изоҳларсиз.
        '''

    raw_response = ask_gemini_with_image(prompt, image_objects)
    
    analysis_data = None
    error_message = ""

    # Attempt 1: Parse the initial response
    try:
        analysis_data = _extract_and_parse_json(raw_response)
    except (json.JSONDecodeError, ValueError) as e:
        error_message = f"Биринчи уринишда хато: {e}. Жавоб: {raw_response}"
        console.print(f"[yellow]⚠️ Gemini жавобида JSON формати аниқланмади. Қайта сўров юборилмоқда...[/yellow]")
        console.print(Panel(
            raw_response, 
            title="[dim red]Сырой ответ Gemini (попытка 1)[/dim red]", 
            border_style="dim red", 
            expand=True
        ))
        with open(TEMP_RAW_RESPONSE_FILE, "w", encoding="utf-8") as f:
            f.write(raw_response)
        console.print(f"[dim]Сырой ответ сохранен в {TEMP_RAW_RESPONSE_FILE}[/dim]")
        if isinstance(e, json.JSONDecodeError):
            console.print(f"[dim red]JSONDecodeError: {e.msg} at doc pos {e.pos}[/dim red]")
        speak_muxlisa_text("Жеймини жавоби тушунарсиз. Қайта сўров юборилмоқда.")

        # Attempt 2: Self-correction prompt
        correction_prompt = f"""
        Менга юборган жавобингни қайта кўриб чиқ. Унда яроқли JSON формати мавжуд эмас. 
        Менга фақат ва фақат яроқли JSON жавобини қайтар, ҳеч қандай изоҳларсиз. 
        Мана олдинги жавобинг:
        ```
        {raw_response}
        ```
        Фақат JSON жавобини қайтар:
        """
        
        # Send correction prompt (without images, just text)
        correction_response = ask_gemini_with_image(correction_prompt, []) # Pass empty list for images
        
        try:
            analysis_data = _extract_and_parse_json(correction_response)
        except (json.JSONDecodeError, ValueError) as e:
            error_message = f"Иккинчи уринишда хато: {e}. Жавоб: {correction_response}"
            console.print(f"[red]❌ Gemini жавобини икки марта тузатишга уриниш муваффақиятсиз якунланди.[/red]")
            console.print(Panel(
                correction_response, 
                title="[dim red]Сырой ответ Gemini (попытка 2)[/dim red]", 
                border_style="dim red", 
                expand=True
            ))
            with open(TEMP_RAW_RESPONSE_FILE, "a", encoding="utf-8") as f: # Append to file
                f.write("\n\n--- Попытка 2 ---\n\n")
                f.write(correction_response)
            console.print(f"[dim]Сырой ответ (попытка 2) добавлен в {TEMP_RAW_RESPONSE_FILE}[/dim]")
            if isinstance(e, json.JSONDecodeError):
                console.print(f"[dim red]JSONDecodeError: {e.msg} at doc pos {e.pos}[/dim red]")
            speak_muxlisa_text("Жеймини жавоби икки марта тузатилмади. Хатолик.")
            return {"status": "Ошибка", "full_analysis": f"Xatolik: Gemini жавоби яроқли JSON форматида эмас (икки марта): {error_message}"}

    if not analysis_data:
         return {"status": "Ошибка", "full_analysis": f"Xatolik: Gemini жавобидан таҳлил маълумотларини олиб бўлмади: {error_message}"}

    if trade_data := analysis_data.get("trade_data"):
        # Save the discovered levels to memory for the Super Agent
        save_key_levels_to_memory(contract_symbol, trade_data)
        
        action = trade_data.get("action", "").upper()
        order_type_str = trade_data.get("order_type", "LIMIT").upper()
        entry_price = trade_data.get("entry_price")

        if action in ["BUY", "SELL"] and entry_price:
            risk_percent = float(trade_data.get("risk_percent", 3.0))
            risk_percent = max(2.0, min(20.0, risk_percent))
            
            stop_loss = float(trade_data["stop_loss"])
            take_profit = float(trade_data["take_profits"]["tp1"])
            balance = primary_account.get("balance", 0.0)
            max_risk_for_trade = balance * (risk_percent / 100.0)
            contract_multiplier = active_contract.get("tickValue") / active_contract.get("tickSize")
            metrics = calculate_trade_metrics(entry_price, stop_loss, take_profit, contract_multiplier, max_risk_for_trade, contract_symbol)
            
            position_size = metrics.get("position_size", 1)
            if "error" in metrics:
                position_size = 1

            position_size = int(round(position_size))
            if position_size == 0:
                position_size = 1

            order_params = {
                "contract_id": full_contract_id, "account_id": primary_account["id"],
                "side": 0 if action == "BUY" else 1, "size": int(position_size),
                "stop_loss": stop_loss, "take_profit": take_profit, "tick_size": tick_size
            }
            if order_type_str == "LIMIT":
                order_params["order_type"] = 1
                order_params["limit_price"] = entry_price
            elif order_type_str == "STOP":
                order_params["order_type"] = 4
                order_params["stop_price"] = entry_price
            else: # Fallback to Market
                order_params["order_type"] = 2

            order_result = client.place_order(**order_params)
            handle_order_result(order_result, primary_account["id"], full_contract_id, action, order_params.get("order_type"))

    send_long_telegram_message(f"BTRADE TAHLILI ({instrument_query}):\n\n{analysis_data.get('full_analysis_uzbek_cyrillic', 'N/A')}")
    
    # Also return trade_data so ctrade_command can display it in a table
    trade_data = analysis_data.get("trade_data")

    return {
        "status": "Успех",
        "full_analysis": analysis_data.get("full_analysis_uzbek_cyrillic", "Tahlil taqdim etilmagan."),
        "voice_summary": analysis_data.get("voice_summary_uzbek_latin"),
        "trade_data": trade_data
    }

def ctrade_command(args: str = None):
    instrument_map = {"gold": "MGC", "mgc": "MGC", "oltin": "MGC", "zoloto": "MGC", "gc": "GC", "oil": "CL", "cl": "CL", "neft": "CL", "s&p": "ES", "es": "ES"}
    instrument_query = None
    if args:
        instrument_query = shlex.split(args)[0].lower()
    if not instrument_query:
        instrument_query = console.input("[bold yellow]Инструмент (масалан, oltin): [/bold yellow]").lower()
    if not (contract_symbol := instrument_map.get(instrument_query)):
        console.print(f"[red]'{instrument_query}' учун тикер топилмади.[/red]"); return

    console.print(f"[cyan]Таҳлил қилинмоқда: {instrument_query.capitalize()} ({contract_symbol})[/cyan]")
    
    screenshot_files = []
    current_batch_dir = SCREENSHOT_DIR / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    current_batch_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        time.sleep(3)
        path = current_batch_dir / f"screenshot_{i + 1}.png"
        # Using -i for interactive mode to avoid window selection issues in some cases
        os.system(f'screencapture -w "{str(path)}"')
        if path.exists() and path.stat().st_size > 0:
            screenshot_files.append(str(path))
        else:
            console.print(f"[red]Скриншот #{i+1} олинмади. Таҳлил бекор қилинди.[/red]")
            return
            
    if len(screenshot_files) < 3:
        console.print("[red]Барча скриншотлар олинмади. Таҳлил тўхтатилди.[/red]")
        return

    analysis_result = run_ctrade_analysis(instrument_query, contract_symbol, screenshot_files)
    
    if analysis_result.get("status") == "Успех":
        # Separate full analysis from the rest of the data
        full_analysis_text = analysis_result.get('full_analysis', 'Мавжуд эмас.')
        
        # Display full analysis in a Panel for proper wrapping
        console.print(Panel(
            full_analysis_text,
            title="[bold green]Тўлиқ Таҳлил (Кириллча)[/bold green]",
            border_style="green",
            expand=True
        ))
        
        # Display key trade data in a structured table if available
        if trade_data := analysis_result.get("trade_data"):
            trade_table = Table(title="[bold blue]Савдо Режаси[/bold blue]", show_header=True, header_style="bold blue")
            trade_table.add_column("Параметр", style="cyan")
            trade_table.add_column("Қиймат", style="white")

            color = "green" if trade_data.get('action') == 'BUY' else "red"
            action_text = trade_data.get('action', 'N/A')
            trade_table.add_row("Ҳаракат", f"[{color}]{action_text}[/{color}]")

            trade_table.add_row("Кириш Нархи", str(trade_data.get('entry_price', 'N/A')))
            trade_table.add_row("Стоп Лосс", str(trade_data.get('stop_loss', 'N/A')))
            
            tps = trade_data.get('take_profits', {})
            if tps:
                for i, (tp_name, tp_level) in enumerate(tps.items()):
                    trade_table.add_row(f"Тейк Профит {i+1}", str(tp_level))
            
            console.print(trade_table)

        # Handle voice summary
        if voice_summary := analysis_result.get("voice_summary"):
            processed_summary = convert_numbers_to_words_in_text(voice_summary)
            speak_in_chunks(processed_summary)
            
    else:
        console.print(Panel(
            analysis_result.get('full_analysis', 'Номаълум хатолик.'),
            title="[bold red]Таҳлилда Хатолик[/bold red]",
            border_style="red"
        ))
