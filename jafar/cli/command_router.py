import os
import shlex
import time
import traceback
from datetime import datetime
import subprocess
import sys
import importlib

from rich.console import Console
from rich.panel import Panel

console = Console()

from jafar.utils.assistant_api import ask_assistant
from jafar.utils.structured_logger import log_action
from jafar.utils.evolution_engine import analyze_logs, load_stats
from .intent_router import route_by_intent
from .print_help import print_help
from .utils import multiline_input
from ..utils.config_manager import load_config as load_jafar_config, save_config as save_jafar_config

def _activate_safari_and_wait():
    pass

def handle_command(command: str, interactive_session: bool = True):
    if not command or not command.strip():
        return

    start_time = time.time()
    status = "failure"
    error_message = None

    try:
        parts = shlex.split(command)
        if not parts:
            return
        action = parts[0].lower().lstrip("/")
        args = " ".join(parts[1:])

        stats = load_stats()
        if action in stats and stats[action]["failure_rate"] > 30:
            rate = stats[action]["failure_rate"]
            console.print(
                Panel(
                    f"⚠️ [bold yellow]Внимание:[/bold yellow] Команда '{action}' имеет высокий процент ошибок ({rate}%) в прошлом. Будьте осторожны.",
                    title="Jafar EVO",
                    style="yellow",
                )
            )

        command_handlers = {
            "ai": "jafar.cli.ai_handlers.ai_command",
            "chat": "jafar.cli.chat_handlers.chat_command",
            "gamemode": "jafar.cli.game_handlers.game_mode_chat",
            "chatmode": "jafar.cli.command_router.chat_mode",
            "github": "jafar.cli.github_handlers.github_command",
            "code": "jafar.cli.code_handlers.code_command",
            "projects": "jafar.cli.project_handlers.projects_command",
            "file": "jafar.cli.file_handlers.file_command",
            "project": "jafar.cli.command_router.project_command",
            "pytest": "jafar.cli.pytest_handlers.pytest_command",
            "evolve": "jafar.utils.evolution_engine.analyze_logs",
            "help": "jafar.cli.print_help.print_help",
            "-h": "jafar.cli.print_help.print_help",
            "--help": "jafar.cli.print_help.print_help",
            "agent-mode": "jafar.cli.agent_handlers.agent_mode_command",
            "analyze_screenshot": "jafar.cli.image_analysis_handler.analyze_screenshot_command",
            "scrn": "jafar.cli.image_analysis_handler.analyze_screenshot_command",
            "addscrn": "jafar.cli.command_router.run_shell_command_for_screenshots",
            "set_default_screenshot_region": "jafar.cli.command_router.set_default_screenshot_region",
            "atrade": "jafar.cli.atrade_handlers.atrade_command",
            "atrade_xapi": "jafar.cli.xapi_handlers.atrade_xapi_command",
            "atrade_pro": "jafar.cli.atrade_pro_handlers.atrade_pro_command",
            "analyze": "jafar.cli.interactive_analyzer.start_interactive_analysis",
            "orders": "jafar.cli.order_handlers.list_orders_command",
            "order_cancel": "jafar.cli.order_handlers.cancel_order_command",
            "order_modify": "jafar.cli.order_handlers.modify_order_command",
            "test_order": "jafar.cli.order_handlers.place_test_order",
            "test_market": "jafar.cli.order_handlers.place_market_order_test",
            "test_contract": "jafar.cli.contract_handlers.test_contract_command",
            "define": "jafar.cli.define_handlers.define_command",
            "seo": "jafar.cli.seo_handlers.seo_command",
        }

        if action in command_handlers:
            module_path, func_name = command_handlers[action].rsplit('.', 1)
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
            func(args)
            status = "success"
        else:
            # Fallback logic for other commands
            if action == "run" and args:
                from .project_run_handler import run_project as project_run
                project_run(args)
                status = "success"
            elif action == "tool":
                from .tool_handlers import tool_command
                tool_command(args)
                status = "success"
            elif action == "push" and args:
                from .github_handlers import push_project
                push_project(args)
                status = "success"
            # ... (add other specific command handlers here)
            else:
                ai_response = ask_assistant(command)
                if isinstance(ai_response, dict):
                    message = (
                        ai_response.get("message")
                        or ai_response.get("explanation")
                        or ai_response.get("command")
                        or ai_response.get("note")
                        or repr(ai_response)
                    )
                else:
                    message = str(ai_response)
                console.print(Panel(message, title="🤖 Jafar", style="green"))
                status = "success"

    except (ValueError, ImportError, KeyError, AttributeError) as e:
        error_message = str(e)
        console.print(Panel(f"❌ Ошибка: {e}", title="Исключение", style="bold red"))
        traceback.print_exc()
    finally:
        duration = time.time() - start_time
        log_action(
            command=command,
            status=status,
            duration=duration,
            error_message=error_message,
        )


def chat_mode(start_with=None):
    console.print(
        Panel(
            "🌐 [bold cyan]Jafar Chat Mode[/bold cyan]\nПиши, чтобы болтать с ассистентом. Введите [yellow]exit[/yellow] для выхода.",
            title="AI Chat",
            style="blue",
        )
    )
    while True:
        try:
            user_input = start_with if start_with else input("[ты] > ").strip()
            start_with = None  # чтобы не повторилось

            if user_input.lower() in ("exit", "выход", "quit"):
                console.print(Panel("👋 Выход из AI-чата", style="dim"))
                break

            if not user_input:
                continue

            response = ask_assistant(user_input)
            message = (
                response.get("message")
                or response.get("explanation")
                or response.get("command")
                or response.get("note")
                or repr(response)
            )
            console.print(Panel(message, title="🤖 Jafar", style="green"))

        except (KeyboardInterrupt, EOFError):
            console.print(Panel("💤 Выход из AI-чата", style="dim"))
            break


def project_command(args):
    config = load_config()
    if not config:
        console.print("[red]Конфигурация пуста.[/red]")
        return

    if args == "list":
        project_list()
        return

    if args == "update":
        project_update()
        return

    if args.startswith("run "):
        name = args.split(" ", 1)[1]
        project_run(name)
        return

    if args == "status":
        project_status()
        return

    if args.startswith("makefile "):
        name = args.split(" ", 1)[1]
        explain_makefile(name)
        return

    if args.startswith("readme "):
        name = args.split(" ", 1)[1]
        explain_readme(name)
        return

    if args.startswith("analyze"):
        parts = shlex.split(args)
        if len(parts) < 2:
            raise ValueError("Укажи имя проекта для анализа.")
        name = parts[1]
        flags = parts[2:] if len(parts) > 2 else []

        if name not in config:
            console.print(
                Panel(
                    f"Проект {name} не найден в конфиге.", title="⚠️ Ошибка", style="red"
                )
            )
            console.print("[yellow]Перейти в AI-режим для уточнения? (y/n)[/yellow]")
            if input(">> ").strip().lower() == "y":
                return chat_mode()
            else:
                return

        path = config[name]["path"]
        force = "--force" in flags
        reset = "--reset" in flags
        analyze_project(name, path, force=force, reset=reset)
        return

    if args.startswith("summary "):
        name = args.split(" ", 1)[1]
        from .project_handlers import project_summary_command

        project_summary_command(name)
        return

    if args and args in config:
        from .project_handlers import project_summary_command

        project_summary_command(args)
        return

    if args == "help":
        console.print(
            Panel(
                "[bold]Доступные команды:[/bold]\n"
                "- [cyan]project list[/cyan] — список проектов\n"
                "- [cyan]project update[/cyan] — обновление всех веток\n"
                "- [cyan]project run <имя>[/cyan] — запуск make run\n"
                "- [cyan]project status[/cyan] — статус файлов проекта\n"
                "- [cyan]project makefile <имя>[/cyan] — объяснение Makefile\n"
                "- [cyan]project readme <имя>[/cyan] — объяснение README.md\n"
                "- [cyan]project analyze <имя> [--force] [--reset][/cyan] — анализ проекта с AI\n"
                "- [cyan]project summary <имя>[/cyan] — сводка по проекту (git + GitHub)",
                title="📦 Project CLI",
                style="cyan",
            )
        )
        return

    # если ничего не подошло — выводим справку
    console.print(
        Panel(
            "[bold]Доступные команды:[/bold]\n"
            "- [cyan]project list[/cyan] — список проектов\n"
            "- [cyan]project update[/cyan] — обновление всех веток\n"
            "- [cyan]project run <имя>[/cyan] — запуск make run\n"
            "- [cyan]project status[/cyan] — статус файлов проекта\n"
            "- [cyan]project makefile <имя>[/cyan] — объяснение Makefile\n"
            "- [cyan]project readme <имя>[/cyan] — объяснение README.md\n"
            "- [cyan]project analyze <имя> [--force] [--reset][/cyan] — анализ проекта с AI\n"
            "- [cyan]project summary <имя>[/cyan] — сводка по проекту (git + GitHub)",
            title="📦 Project CLI",
            style="cyan",
        )
    )
