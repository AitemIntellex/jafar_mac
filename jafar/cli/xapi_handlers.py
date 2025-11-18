from rich.console import Console
from rich import print_json
from jafar.utils.topstepx_api_client import TopstepXClient
import os
from datetime import datetime, timedelta

console = Console()

def _get_primary_account(client: TopstepXClient):
    """Вспомогательная функция для получения основного счета."""
    accounts_response = client.get_account_list()
    if not accounts_response or not accounts_response.get("accounts"):
        console.print("[red]Не удалось получить список счетов.[/red]")
        return None
    
    all_accounts = accounts_response["accounts"]
    preferred_account_name = os.environ.get("TOPSTEPX_ACCOUNT_NAME")
    
    if preferred_account_name:
        for acc in all_accounts:
            if acc.get("name") == preferred_account_name:
                return acc
    
    return all_accounts[0]

def atrade_xapi_command(args: str = None):
    """
    Запрашивает и выводит открытые позиции и активные ордера для отладки OCO.
    """
    console.print("[bold yellow]--- Диагностика Позиций и Ордеров ---[/bold yellow]")
    
    try:
        client = TopstepXClient()
        primary_account = _get_primary_account(client)
        if not primary_account:
            return

        account_id = primary_account["id"]
        console.print(f"[cyan]Запрос данных для счета {primary_account.get('name')} (ID: {account_id})...[/cyan]")

        # 1. Получаем открытые позиции
        open_positions = client.get_open_positions(account_id)
        
        console.print("\n[bold green]--- ОТКРЫТЫЕ ПОЗИЦИИ (/Position/searchOpen) ---[/bold green]")
        if open_positions and open_positions.get("positions"):
            print_json(data=open_positions)
        else:
            console.print("[yellow]Открытых позиций не найдено.[/yellow]")

        # 2. Получаем все ордера за последние 24 часа
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=24)
        orders_response = client.get_orders(account_id, start_time, end_time)
        
        console.print("\n[bold green]--- ВСЕ ОРДЕРА (/Order/search) ---[/bold green]")
        if orders_response and orders_response.get("orders"):
            print_json(data=orders_response)
        else:
            console.print("[yellow]Ордеров не найдено.[/yellow]")

    except Exception as e:
        console.print(f"[bold red]Произошла непредвиденная ошибка: {e}[/bold red]")
        import traceback
        traceback.print_exc()
