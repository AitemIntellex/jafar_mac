from rich.console import Console
from rich.panel import Panel

console = Console()

def seo_command(args: str):
    """
    Главный обработчик для всех SEO-команд.
    Маршрутизирует на основе первого аргумента.
    """
    subcommand = args.split(" ")[0] if args else ""

    if subcommand == "hello":
        console.print(Panel("[bold green]Hello, SEO World![/bold green]", title="Jafar SEO", style="green"))
    else:
        console.print(
            Panel(
                "[bold]Доступные SEO-команды:[/bold]\n"
                "- [cyan]seo hello[/cyan] — Проверить, работает ли SEO-модуль.",
                title="Jafar SEO Help",
                style="yellow",
            )
        )
