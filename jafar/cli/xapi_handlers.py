from rich.console import Console
from rich import print_json
from rich.table import Table # Добавлен импорт Table
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
    preferred_account_name = os.environ.get("TOPSTEPX_ACCOUNT_NAME2") # Use TOPSTEPX_ACCOUNT_NAME2 for consistency
    
    if preferred_account_name:
        for acc in all_accounts:
            if acc.get("name") == preferred_account_name:
                return acc
    
    return all_accounts[0]

def atrade_xapi_command(args: str = None):
    """
    Запрашивает и выводит открытые позиции и активные ордера для отладки OCO.
    """
    console.print("[bold yellow]--- Диагностика Счета TopstepX ---[/bold yellow]")
    
    try:
        client = TopstepXClient()
        primary_account = _get_primary_account(client)
        if not primary_account:
            return

        account_id = primary_account["id"]
        account_name = primary_account.get("name", "N/A")
        balance = primary_account.get("balance", 0.0)
        equity = primary_account.get("equity", 0.0)
        margin = primary_account.get("initialMargin", 0.0)

        # Account Summary Table
        account_table = Table(title=f"Счет: {account_name} (ID: {account_id})", show_header=True, header_style="bold magenta")
        account_table.add_column("Метрика", style="cyan", no_wrap=True)
        account_table.add_column("Значение", style="green")
        account_table.add_row("Баланс", f"${balance:,.2f}")
        account_table.add_row("Эквити", f"${equity:,.2f}")
        account_table.add_row("Использованная маржа", f"${margin:,.2f}")
        console.print(account_table)

        # 1. Получаем открытые позиции
        open_positions = client.get_open_positions(account_id)
        
        console.print("\n[bold green]--- ОТКРЫТЫЕ ПОЗИЦИИ ---[/bold green]")
        if open_positions and open_positions.get("positions"):
            positions_table = Table(title="Открытые Позиции", show_header=True, header_style="bold cyan")
            positions_table.add_column("Контракт", style="cyan")
            positions_table.add_column("Сторона", style="magenta")
            positions_table.add_column("Размер", style="green")
            positions_table.add_column("Цена открытия", style="yellow")
            positions_table.add_column("PNL", style="blue")
            
            for pos in open_positions["positions"]:
                contract_id = pos.get("contractId", "N/A")
                side = "Покупка" if pos.get("side") == 0 else "Продажа"
                size = pos.get("size", 0)
                price = pos.get("price", 0.0)
                pnl = pos.get("unrealizedPnl", 0.0) # Unrealized PnL
                
                positions_table.add_row(
                    contract_id,
                    side,
                    str(size),
                    f"{price:,.2f}",
                    f"${pnl:,.2f}"
                )
            console.print(positions_table)
        else:
            console.print("[yellow]Открытых позиций не найдено.[/yellow]")

        # 2. Получаем все ордера за последние 24 часа
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=24)
        orders_response = client.get_orders(account_id, start_time, end_time)
        
        console.print("\n[bold green]--- АКТИВНЫЕ ОРДЕРА (за 24 часа) ---[/bold green]")
        if orders_response and orders_response.get("orders"):
            orders_table = Table(title="Активные Ордера", show_header=True, header_style="bold yellow")
            orders_table.add_column("ID Ордера", style="cyan")
            orders_table.add_column("Контракт", style="magenta")
            orders_table.add_column("Тип", style="green")
            orders_table.add_column("Сторона", style="green")
            orders_table.add_column("Размер", style="yellow")
            orders_table.add_column("Цена", style="blue")
            orders_table.add_column("Статус", style="red")

            for order in orders_response["orders"]:
                # Filter only active/pending orders for better clarity in this table
                if order.get("status") in [0, 1]: # 0: Pending, 1: Open
                    order_id = order.get("orderId", "N/A")
                    contract_id = order.get("contractId", "N/A")
                    order_type = order.get("orderType", "N/A") # 1=Limit, 4=Stop, 2=Market
                    side = "Покупка" if order.get("side") == 0 else "Продажа"
                    size = order.get("size", 0)
                    
                    price = "N/A"
                    if order_type == 1: price = str(order.get("limitPrice", "N/A"))
                    elif order_type == 4: price = str(order.get("stopPrice", "N/A"))

                    status = "Ожидает" if order.get("status") == 0 else "Активен"

                    orders_table.add_row(
                        str(order_id),
                        contract_id,
                        {
                            0: "Market", 1: "Limit", 2: "Market", 3: "Stop Limit", 4: "Stop",
                            5: "Trailing Stop", 6: "Bracket", 7: "OCO", 8: "MIT", 9: "MOO", 10: "LOC"
                        }.get(order.get("orderType"), "Unknown"),
                        side,
                        str(size),
                        price,
                        status
                    )
            if orders_table.rows:
                console.print(orders_table)
            else:
                console.print("[yellow]Активных ордеров не найдено (за 24 часа).[/yellow]")
        else:
            console.print("[yellow]Ордеров не найдено (за 24 часа).[/yellow]")

    except Exception as e:
        console.print(f"[bold red]Произошла непредвиденная ошибка: {e}[/bold red]")
        import traceback
        traceback.print_exc()
