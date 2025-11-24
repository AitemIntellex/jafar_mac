import os
import time
import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import concurrent.futures
import speech_recognition as sr
import pyaudio

from rich.console import Console
from jafar.utils.topstepx_api_client import TopstepXClient
from jafar.cli.ctrade_handlers import run_ctrade_analysis # Reusing existing logic
from jafar.cli.muxlisa_voice_output_handler import speak_muxlisa_text
from jafar.utils.text_utils import convert_numbers_to_words_in_text
from jafar.cli.telegram_handler import send_long_telegram_message

console = Console()
KEY_LEVELS_FILE = Path("memory/key_levels.json")
TOPSTEPX_USERNAME = os.getenv("TOPSTEPX_USERNAME")
TOPSTEPX_API_KEY = os.getenv("TOPSTEPX_API_KEY")
MONITOR_INTERVAL_SECONDS = 90 # How often to check prices
PRICE_THRESHOLD_PERCENT = 0.05 # Price proximity to level, in percent

APPLE_SCRIPT_ACTIVATE_TOPSTEPX = Path(__file__).parent / "scripts" / "activate_topstepx.scpt"
APPLE_SCRIPT_CLICK_SNAPSHOT = Path(__file__).parent / "scripts" / "click_topstepx_snapshot.scpt"

def load_key_levels():
    if not KEY_LEVELS_FILE.exists():
        console.print(f"[red]Xatolik: Asosiy darajalar fayli topilmadi: {KEY_LEVELS_FILE}[/red]")
        return {}
    with open(KEY_LEVELS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_topstepx_client():
    client = TopstepXClient(TOPSTEPX_USERNAME, TOPSTEPX_API_KEY)
    if not client.is_authenticated:
        console.print("[bold red]Xatolik: TopstepX APIga ulanishda xatolik. Iltimos, .env faylidagi ma'lumotlarni tekshiring.[/bold red]")
        return None
    return client

def get_current_prices(client: TopstepXClient, instruments: list[str]) -> dict:
    prices = {}
    for instrument in instruments:
        try:
            contract_info = client.search_contract(name=instrument)
            if contract_info and contract_info.get("contracts"):
                active_contract = next((c for c in contract_info["contracts"] if c.get("activeContract")), None)
                if active_contract:
                    # Fetching last bar's close price as current price
                    bars = client.get_historical_bars(active_contract["id"], datetime.utcnow() - timedelta(minutes=5), datetime.utcnow(), unit=1, unit_number=1, limit=1)
                    if bars and bars.get("bars"):
                        prices[instrument] = bars["bars"][0]["c"]
                    else:
                        console.print(f"[yellow]Warning: Could not get recent bar for {instrument}.[/yellow]")
        except Exception as e:
            console.print(f"[red]Error fetching price for {instrument}: {e}[/red]")
    return prices

def make_topstepx_screenshot(output_path: Path) -> Optional[str]:
    """
    Activates TopstepX and uses screencapture to take a screenshot of the selected window.
    Instructs the user to focus on the TopstepX window.
    """
    console.print("[bold yellow]Iltimos, TopstepX oynasiga e'tibor bering. Skrinshot 3 soniyadan so'ng olinadi.[/bold yellow]")
    speak_muxlisa_text("TopstepX oynasiga e'tibor bering. Skrinshot uch soniyadan so'ng olinadi.")
    
    # Try to activate TopstepX window using AppleScript
    try:
        subprocess.run(["osascript", str(APPLE_SCRIPT_ACTIVATE_TOPSTEPX)], check=True, capture_output=True)
        time.sleep(1) # Give it a moment to activate
    except subprocess.CalledProcessError as e:
        console.print(f"[red]TopstepXni faollashtirishda xatolik: {e.stderr.decode()}[/red]")
    except FileNotFoundError:
        console.print("[red]Xatolik: osascript buyrug'i topilmadi. macOS tizimida ishonch hosil qiling.[/red]")

    time.sleep(3)
    try:
        # -w flag allows interactive window selection, user needs to click on TopstepX window
        subprocess.run(["screencapture", "-w", str(output_path)], check=True)
        if output_path.exists() and output_path.stat().st_size > 0:
            console.print(f"[green]Skrinshot saqlandi: {output_path}[/green]")
            return str(output_path)
        else:
            console.print("[red]Skrinshot olinmadi. Foydalanuvchi oynani tanlamagan bo'lishi mumkin.[/red]")
            return None
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Skrinshot olishda xatolik yuz berdi: {e.stderr.decode()}[/red]")
        return None

def listen_for_confirmation(timeout: int = 15) -> bool:
    """
    Listens for a voice confirmation from the user for a given timeout.
    Recognizes 'ha', 'yes', 'da', 'okay', 'poехали'.
    """
    r = sr.Recognizer()
    with sr.Microphone() as source:
        console.print(f"[bold magenta]Tasdiqlash kutilmoqda ({timeout} soniya)...[/bold magenta]")
        speak_muxlisa_text(f"Tasdiqlash kutilmoqda. {timeout} soniya.")
        try:
            audio = r.listen(source, timeout=timeout, phrase_time_limit=timeout)
            text = r.recognize_google(audio, language="uz-UZ") # Attempt Uzbek recognition first
            console.print(f"[dim]Siz aytdingiz: '{text}'[/dim]")
            if any(keyword in text.lower() for keyword in ["ha", "yes", "da", "okay", "поехали", "qani"]):
                console.print("[bold green]Tasdiqlandi![/bold green]")
                return True
        except sr.WaitTimeoutError:
            console.print("[yellow]Tasdiqlash vaqti tugadi.[/yellow]")
        except sr.UnknownValueError:
            console.print("[yellow]Ovoz aniqlanmadi.[/yellow]")
        except sr.RequestError as e:
            console.print(f"[red]Google Speech Recognition xizmatiga ulanishda xatolik: {e}[/red]")
    console.print("[bold red]Tasdiqlanmadi.[/bold red]")
    return False

def super_agent_loop():
    console.print("[bold green]Jafar Super Agent ishga tushirildi! Bozor kuzatilmoqda...[/bold green]")
    speak_muxlisa_text("Jafar Super Agent ishga tushirildi. Bozor kuzatilmoqda.")

    client = get_topstepx_client()
    if not client:
        return # Exit if client not authenticated

    while True:
        try:
            key_levels_data = load_key_levels()
            monitored_instruments = list(key_levels_data.keys())
            
            # --- Prioritet #1: Ochiq pozitsiyalarni boshqarish ("Position Shepherd") ---
            # Placeholder: This part will be fully implemented later
            # For now, we prioritize Level Guardian if no specific position management logic is here.

            # --- Prioritet #2: Yangi savdo imkoniyatlarini izlash ("Level Guardian") ---
            console.print(f"[{datetime.now().strftime('%H:%M:%S')}] [dim]Супер Агент: Нарх даражаларини текшириш... ({', '.join(monitored_instruments)})[/dim]")
            current_prices = get_current_prices(client, monitored_instruments)
            # console.print(f"[dim]Joriy narxlar: {current_prices}[/dim]")

            for instrument, levels in key_levels_data.items():
                current_price = current_prices.get(instrument)
                if current_price is None: continue

                for level_data in levels:
                    if level_data.get("status") == "active":
                        level = level_data["level"]
                        level_type = level_data["type"]
                        
                        price_diff = abs(current_price - level)
                        threshold_value = level * (PRICE_THRESHOLD_PERCENT / 100)

                        if price_diff <= threshold_value:
                            console.print(f"\n[bold green]Diqqat! {instrument} uchun narx {current_price} asosiy {level} ({level_type}) darajasiga yaqinlashmoqda![/bold green]")
                            latin_summary = f"Diqqat! {convert_numbers_to_words_in_text(str(current_price))} narx {convert_numbers_to_words_in_text(str(level))} darajasiga yaqinlashmoqda. Tahlil uchun skrinshotlar tayyorlashga tayyormisiz?"
                            speak_muxlisa_text(latin_summary)
                            send_long_telegram_message(f"[Jafar Super Agent] Diqqat! {instrument} uchun narx {current_price} asosiy {level} ({level_type}) darajasiga yaqinlashmoqda. Tahlil uchun skrinshotlar kerak!")

                            if listen_for_confirmation():
                                current_screenshot_dir = Path("screenshot") / f"superagent_{instrument}_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}"
                                current_screenshot_dir.mkdir(parents=True, exist_ok=True)
                                
                                temp_screenshot_files = []
                                for i in range(3):
                                    screenshot_path = current_screenshot_dir / f"screenshot_{i+1}.png"
                                    if shot_path := make_topstepx_screenshot(screenshot_path):
                                        temp_screenshot_files.append(shot_path)
                                    else:
                                        console.print("[red]Skrinshot olinmadi. Tahlil bekor qilindi.[/red]"); break

                                if len(temp_screenshot_files) == 3:
                                    console.print("[bold blue]Skrinshotlar olindi. Gemini orqali tahlil boshlanmoqda...[/bold blue]")
                                    analysis_result = run_ctrade_analysis(instrument, instrument, temp_screenshot_files)
                                    
                                    if analysis_result.get("status") == "Успех":
                                        full_analysis_uz = analysis_result.get("full_analysis", "Noma'lum tahlil.")
                                        voice_summary_uz_latin = analysis_result.get("voice_summary", "Ovozli xulosa mavjud emas.")
                                        
                                        console.print(f"\n[bold green]--- To'liq Tahlil (Kirillcha) ---[/bold green]\n{full_analysis_uz}")
                                        if voice_summary_uz_latin:
                                            processed_summary = convert_numbers_to_words_in_text(voice_summary_uz_latin)
                                            speak_muxlisa_text(processed_summary)

                                        # Execute trade based on analysis_result (assuming ctrade_handlers does this)
                                        # For now, ctrade_handlers handles the execution internally, we just trigger it.
                                        
                                    else:
                                        console.print(f"[bold red]--- Tahlilda Xatolik ---[/bold red]\n{analysis_result.get('full_analysis', 'Noma`lum xatolik.')}")

                                # Mark level as inactive or temporarily ignore to avoid re-triggering immediately
                                level_data["status"] = "triggered" # Or add a 'last_triggered' timestamp
                                # In a real scenario, we might want to update key_levels.json here to save the state
                                speak_muxlisa_text(f"{instrument} bo'yicha tahlil yakunlandi.")
                            else:
                                speak_muxlisa_text("Skrinshot olish bekor qilindi.")

            time.sleep(MONITOR_INTERVAL_SECONDS) # Wait before next check

        except Exception as e:
            console.print(f"[bold red]Super Agentda kutilmagan xatolik: {e}[/bold red]")
            speak_muxlisa_text(f"Super Agentda kutilmagan xatolik yuz berdi. {e}")
            time.sleep(MONITOR_INTERVAL_SECONDS * 2) # Longer wait on error


def start_super_agent():
    console.print("[bold blue]Super Agent fon rejimida ishga tushirilmoqda...[/bold blue]")
    super_agent_loop()