import os
import getpass
import traceback
from datetime import datetime
import sys
import random
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.columns import Columns
from rich.table import Table
from rich.text import Text
from rich.markup import escape
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML

from jafar.cli.command_router import handle_command
from jafar.utils.market_utils import get_current_trading_session
from jafar.cli.telegram_handler import send_long_telegram_message

console = Console()
HISTORY_FILE = os.path.expanduser("~/.jafar_history.txt")
PID_FILE = Path("/Users/macbook/.gemini/tmp/super_agent.pid")

JAFAR_ASCII_ART = """
██╗ █████╗ ███████╗ █████╗ ██████╗ 
██║██╔══██╗██╔════╝██╔══██╗██╔══██╗
██║███████║█████╗  ███████║██████╔╝
██║██╔══██║██╔╝  ██╔══██║██╔══██╗
██║██║  ██║███████╗██║  ██║██║  ██║
╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝
"""

TRADING_QUOTES = [
    "Фонд бозори — сабрсизлардан сабрлиларга пул ўтказиш учун яратилган қурилмадир. - Уоррен Баффетт",
    "Тренд — бу сенинг дўстинг, то у эгилгунча. - Эд Сейкота",
    "Инвестициядаги энг хавфли тўрт сўз: 'Бу сафар бошқача бўлади.' - Сэр Жон Темплтон",
    "Муваффақиятли трейдернинг мақсади — энг яхши савдоларни амалга ошириш. Пул иккинчи даражали. - Александр Элдер"
]

def get_super_agent_status():
    """Checks if the Super Agent is running and returns a colored Text object."""
    if not PID_FILE.exists():
        return Text("🔴 Тўхтатилган", style="bold red")
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return Text(f"🟢 Ишламоқда (PID: {pid})", style="bold green")
    except (IOError, ValueError, OSError):
        return Text("🟡 Номаълум", style="bold yellow")

def display_welcome_banner():
    """Displays a stylized, colored 'Launch Dashboard'."""
    
    # Left Column: ASCII Art
    ascii_art = Text(JAFAR_ASCII_ART, style="bold magenta")

    # Right Column: Status Panel
    status_table = Table.grid(padding=(0, 2))
    status_table.add_column(style="dim cyan", justify="right")
    status_table.add_column(style="bold white")
    status_table.add_row("Вақт:", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    status_table.add_row("Савдо Сессияси:", get_current_trading_session())
    status_table.add_row("Фойдаланувчи:", getpass.getuser())
    status_table.add_row("Супер Агент:", get_super_agent_status())
    
    status_panel = Panel(status_table, title="СТАТУС", border_style="cyan", expand=False)

    # Main layout with two columns
    columns = Columns([ascii_art, status_panel], equal=True, expand=True)

    # Quote below the columns
    chosen_quote = random.choice(TRADING_QUOTES)
    quote_text = Text(f'\n"{chosen_quote}"', style="italic yellow", justify="center")

    # Send quote to Telegram
    send_long_telegram_message(f"**Кун Цитатаси:**\n\n_{chosen_quote}_")

    # Group everything together
    main_renderable = Group(columns, quote_text)

    # Print in a final Panel
    console.print(Panel(
        main_renderable,
        title="Jafar AI Савдо Ассистенти",
        border_style="bold green",
        padding=(1, 2)
    ))

def jafar_prompt():
    """Returns a simplified and clean prompt."""
    return HTML("<bold><ansiblue>(jafar)</ansiblue> <ansiwhite>❯</ansiwhite></bold> ")

def main():
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)

        if len(sys.argv) > 1:
            command = " ".join(sys.argv[1:])
            handle_command(command, interactive_session=False)
            return

        if not sys.stdout.isatty():
            return

        session = PromptSession(history=FileHistory(HISTORY_FILE))
        display_welcome_banner()

        while True:
            try:
                command = session.prompt(jafar_prompt()).strip()
                if not command:
                    continue
                handle_command(command, interactive_session=True)

            except (KeyboardInterrupt, EOFError):
                console.print("\n👋 Хайр!")
                break
            except Exception as e:
                console.print(f"[red]❌ Хатолик: {escape(str(e))}[/red]")
                traceback.print_exc()

    except Exception as e:
        console.print(f"[red]❌ Jafar'ни ишга туширишда хатолик: {escape(str(e))}[/red]")
        traceback.print_exc()

def run_jafar():
    main()