import os
import re
from rich.console import Console
from rich.panel import Panel
from jafar.utils.assistant_api import ask_assistant
from jafar.utils.structured_logger import log_action
from jafar.utils.config_manager import load_config, save_config

console = Console()
MEMORY_PATH = "/Users/macbook/projects/jr/jafar_unified/memory/finance_terms.md"

def _read_knowledge_base():
    """Читает всю базу знаний из файла finance_terms.md."""
    if not os.path.exists(MEMORY_PATH):
        return ""
    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        return f.read()

def _write_knowledge_base(content):
    """Записывает контент в базу знаний finance_terms.md."""
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        f.write(content)

def define_command(term: str):
    """
    Определяет термин, используя локальную базу знаний или Gemini.
    Предлагает сохранить новое определение.
    """
    if not term:
        console.print(Panel("[red]Пожалуйста, укажите термин для определения.[/red]", title="Jafar Define", style="red"))
        return

    # 1. Поиск в локальной базе знаний
    knowledge_base_content = _read_knowledge_base()
    # Ищем термин, игнорируя регистр, и захватываем определение до следующего **Термин:** или конца файла
    match = re.search(rf"\*\*Термин:\*\* {re.escape(term)}\s*\n\n\*\*Определение:\*\*(.*?)(?=\*\*Термин:\*\*|\Z)", knowledge_base_content, re.DOTALL | re.IGNORECASE)

    if match:
        definition = match.group(1).strip()
        console.print(Panel(f"[bold green]Из базы знаний:[/bold green]\n{definition}", title=f"Jafar Define: {term}", style="green"))
        log_action(command=f"define {term}", status="success", message="Found in local knowledge base")
        return

    # 2. Если не найден, запрашиваем у Gemini
    console.print(Panel(f"Термин '{term}' не найден в локальной базе знаний. Запрашиваю у Gemini...", title="Jafar Define", style="yellow"))
    try:
        prompt = f"Дай краткое и точное определение термина '{term}' на русском языке, с ключевыми характеристиками и примером, если применимо. Форматируй ответ как:\n\n**Термин:** [Термин]\n\n**Определение:**\n[Определение]\n\n**Ключевые характеристики:**\n[Список характеристик]\n\n**Пример из практики:**\n[Пример]"
        ai_response = ask_assistant(prompt)

        if isinstance(ai_response, dict) and (ai_response.get("message") or ai_response.get("explanation")):
            gemini_definition = ai_response.get("message") or ai_response.get("explanation")
        else:
            gemini_definition = str(ai_response)

        console.print(Panel(f"[bold blue]От Gemini:[/bold blue]\n{gemini_definition}", title=f"Jafar Define: {term}", style="blue"))

        # 3. Предлагаем сохранить
        console.print("[yellow]Сохранить это определение в базу знаний? (y/n)[/yellow]")
        user_choice = input(">> ").strip().lower()

        if user_choice == "y":
            # Строку для замены нужно определить вне f-строки
            str_to_replace = f"**Термин:** {term}\n\n**Определение:**\n"
            clean_definition = gemini_definition.replace(str_to_replace, '', 1).strip()
            new_entry = f"\n\n**Термин:** {term}\n\n**Определение:**\n{clean_definition}"
            
            _write_knowledge_base(knowledge_base_content + new_entry)
            console.print(Panel(f"[green]Определение термина '{term}' успешно сохранено в базу знаний.[/green]", title="Jafar Define", style="green"))
            log_action(command=f"define {term}", status="success", message="Definition saved from Gemini")
        else:
            console.print(Panel("[dim]Определение не сохранено.[/dim]", title="Jafar Define", style="dim"))
            log_action(command=f"define {term}", status="success", message="Definition not saved from Gemini")

    except Exception as e:
        console.print(Panel(f"❌ Ошибка при запросе к Gemini: {e}", title="Jafar Define", style="red"))
        log_action(command=f"define {term}", status="failure", error_message=str(e))