
import logging
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
import os

# Configure logging
from jafar.utils.news_api import get_unified_news
from jafar.utils.gemini_api import ask_gemini_text_only
from jafar.cli.telegram_handler import send_long_telegram_message
from jafar.cli.muxlisa_voice_output_handler import speak_muxlisa_text

console = Console()

# Словарь с настройками для каждого типа анализа
ANALYSIS_CONFIG = {
    "1": {
        "name": "Анализ рынка золота",
        "type": "gold",
        "keywords": ["gold", "XAUUSD", "Fed", "inflation", "dollar"],
        "analysis_dir": Path(__file__).parent.parent.parent / "analyzes" / "gold",
        "prompt_file": Path(__file__).parent.parent / "analysis" / "prompts" / "gold_news_prompt.txt",
    },
    "2": {
        "name": "Анализ криптовалют",
        "type": "crypto",
        "keywords": ["bitcoin", "ethereum", "crypto", "SEC", "blockchain"],
        "analysis_dir": Path(__file__).parent.parent.parent / "analyzes" / "crypto",
        "prompt_file": Path(__file__).parent.parent / "analysis" / "prompts" / "crypto_prompt.txt",
    },
    "3": {
        "name": "Анализ валютного рынка",
        "type": "currency",
        "keywords": ["forex", "EURUSD", "GBPUSD", "USDJPY", "ECB", "central bank"],
        "analysis_dir": Path(__file__).parent.parent.parent / "analyzes" / "currency",
        "prompt_file": Path(__file__).parent.parent / "analysis" / "prompts" / "currency_news_prompt.txt",
    },
    "4": {
        "name": "Анализ фьючерсов",
        "type": "futures",
        "keywords": ["futures", "commodities", "oil", "CME"],
        "analysis_dir": Path(__file__).parent.parent.parent / "analyzes" / "futures",
        "prompt_file": Path(__file__).parent.parent / "analysis" / "prompts" / "futures_news_prompt.txt",
    },
    "5": {
        "name": "Общий анализ мировых новостей",
        "type": "world_news",
        "keywords": ["geopolitics", "world economy", "market sentiment"],
        "analysis_dir": Path(__file__).parent.parent.parent / "analyzes" / "world_news",
        "prompt_file": Path(__file__).parent.parent / "analysis" / "prompts" / "world_news_prompt.txt",
    },
}

def start_interactive_analysis(args: str = None):
    """Запускает интерактивный режим для выбора и выполнения анализа с автоматической загрузкой новостей."""
    try:
        topic = args.strip() if args else None
        if not topic:
            console.print(Panel("[bold cyan]Интерактивный Анализатор Jafar[/bold cyan]", title="🤖 Jafar"))
            console.print("Пожалуйста, выберите тип анализа:")
            for key, config in ANALYSIS_CONFIG.items():
                console.print(f"  [yellow]{key}[/yellow]. {config['name']}")
            
            choice = console.input("\n[bold]Введите номер: [/bold]")

            if choice not in ANALYSIS_CONFIG:
                console.print("[red]Неверный выбор. Пожалуйста, запустите команду 'analyze' снова.[/red]")
                return
            topic = ANALYSIS_CONFIG[choice]['type']

        console.print(f"\n[blue]Выбран анализ: {topic}[/blue]")

        # --- Запуск анализа ---
        console.print("[bold blue]Запускаю анализ...[/bold blue]")
        logging.info(f"Starting analysis for topic: {topic}")
        console.print(f"🔍 «{topic}» мавзусида энг сўнгги янгиликлар қидирилмоқда...")
        
        logging.info(f"Fetching news for topic '{topic}' using unified news API.")
        news_data = get_unified_news(instrument=topic, top_n=15)

        if "error" in news_data:
            logging.error(f"MarketAux API error: {news_data['error']}")
            console.print(f"[red]MarketAux API'дан янгиликларни олишда хатолик: {news_data['error']}[/red]")
            return

        search_results = news_data.get("results", [])
        if not search_results:
            logging.warning("MarketAux returned no news results for this topic.")
            console.print("[yellow]Ушбу мавзу бўйича янгиликлар топилмади.[/yellow]")
            return

        logging.info(f"Successfully fetched {len(search_results)} articles from MarketAux.")

        snippets = [f"{item.get('title', '')}: {item.get('snippet', '')}" for item in search_results]
        news_context = "\n\n".join(snippets)
        logging.debug(f"Context created from snippets:\n{news_context}")

        console.print("🤖 Янгиликлар Gemini'га таҳлил учун юборилмоқда...")
        
        prompt = f"""Analyze the following news snippets about {topic} and provide a comprehensive analysis in English. The analysis should include:
1.  A brief summary of the current situation.
2.  Key market drivers (positive and negative).
3.  The overall market sentiment (e.g., bullish, bearish, neutral).
4.  A short-term forecast.

News snippets:
{news_context}
"""
        logging.info("Sending prompt to Gemini for English analysis.")
        english_analysis = ask_gemini_text_only(prompt)

        if not english_analysis:
            logging.error("Gemini analysis returned no result.")
            console.print("[bold red]Таҳлил натижасини олишда хатолик.[/bold red]")
            return
        
        logging.info("Successfully received English analysis. Now translating to Uzbek.")
        
        # --- Translate to Uzbek ---
        translation_prompt = f"Translate the following English text to Uzbek (using Latin script). Be accurate and professional:\n\n{english_analysis}"
        uzbek_analysis = ask_gemini_text_only(translation_prompt)

        if not uzbek_analysis:
            logging.error("Gemini translation returned no result.")
            console.print("[bold red]Таржима қилишда хатолик юз берди.[/bold red]")
            return

        logging.info("Successfully translated analysis to Uzbek.")
        logging.debug(f"Uzbek analysis result:\n{uzbek_analysis}")

        # --- Отправка в Telegram и озвучка ---
        console.print("[bold blue]Натижалар тайёрланмоқда...[/bold blue]")
        
        # Формируем отчет для Telegram
        report_for_telegram = f"🔔 *Mavzu bo'yicha tahlil: {topic.upper()}*\n\n"
        report_for_telegram += uzbek_analysis
        
        # Отправляем в Telegram
        send_long_telegram_message(report_for_telegram)
        console.print("[green]✅ Тўлиқ таҳлил Telegram'га юборилди.[/green]")

        # Озвучиваем краткую сводку
        summary_prompt = f"Ushbu tahlil asosida, ovozli o'qish uchun o'zbek tilida (lotin yozuvida) qisqa va tushunarli xulosa ber. Eng muhimi, javobing 500 ta belgidan oshmasin: {uzbek_analysis}"
        summary_for_voice = ask_gemini_text_only(summary_prompt)
        
        if summary_for_voice:
            console.print("[bold blue]📢 Қисқача маълумот ўқилмоқда... (Ctrl+C для отмены)[/bold blue]")
            try:
                speak_muxlisa_text(summary_for_voice)
            except KeyboardInterrupt:
                console.print("\n[yellow]Озвучка прервана пользователем.[/yellow]")
        
        console.print(Panel(uzbek_analysis, title="🤖 Jafar - Tahlil Natijasi", style="green"))

    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Анализ прерван пользователем.[/yellow]")
    except Exception as e:
        console.print(f"[bold red]Произошла непредвиденная ошибка: {e}[/bold red]")
        import traceback
        traceback.print_exc()
