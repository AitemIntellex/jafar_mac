from rich.console import Console
from rich import print_json
from jafar.utils.topstepx_api_client import TopstepXClient

console = Console()

def test_contract_command(args: str = None):
    """
    Ищет контракт по имени (например, GC) и выводит полную информацию о нем,
    включая правильный contractId и tickSize.
    """
    console.print("[bold yellow]--- Поиск информации о контракте ---[/bold yellow]")
    if not args:
        console.print("[red]Ошибка: Укажите имя контракта для поиска, например: 'test_contract GC'[/red]")
        return

    contract_name = args.strip().upper()

    try:
        client = TopstepXClient()
        contract_info = client.search_contract(name=contract_name)

        console.print(f"\n[bold green]--- ПОЛНЫЙ JSON-ОТВЕТ ДЛЯ '{contract_name}' ---[/bold green]")
        if contract_info and contract_info.get("contracts"):
            print_json(data=contract_info)
            # Дополнительно выводим ключевые параметры
            console.print("\n[bold cyan]--- Ключевые параметры ---[/bold cyan]")
            for contract in contract_info["contracts"]:
                console.print(f"  - Имя: {contract.get('name')}")
                console.print(f"    [bold]contractId:[/bold] {contract.get('id')}")
                console.print(f"    [bold]tickSize:[/bold] {contract.get('tickSize')}")
                console.print("-" * 20)

        elif contract_info:
             print_json(data=contract_info)
        else:
            console.print(f"[yellow]Не удалось найти информацию по контракту '{contract_name}'.[/yellow]")

    except Exception as e:
        console.print(f"[bold red]Произошла непредвиденная ошибка: {e}[/bold red]")
        import traceback
        traceback.print_exc()
