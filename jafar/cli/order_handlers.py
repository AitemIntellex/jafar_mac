import os
from rich.console import Console
from rich.table import Table
from jafar.utils.topstepx_api_client import TopstepXClient

console = Console()

def get_primary_account_id(client: TopstepXClient) -> str | None:
    """Gets the primary account ID based on .env or the first available account."""
    accounts_response = client.get_account_list()
    if not accounts_response or not accounts_response.get("accounts"):
        console.print("[red]TopstepX'дан ҳисоблар рўйхатини олиб бўлмади.[/red]")
        return None
    
    accounts = accounts_response["accounts"]
    preferred_account_name = os.environ.get("TOPSTEPX_ACCOUNT_NAME")
    
    if preferred_account_name:
        for acc in accounts:
            if acc.get("name") == preferred_account_name:
                return acc.get("id")
    
    # Fallback to the first account if preferred is not found or not set
    if accounts:
        return accounts[0].get("id")
        
    return None

def list_orders_command(args: str):
    """Fetches and displays active orders for the primary account."""
    console.print("[blue]Актив ордерлар юкланмоқда...[/blue]")
    try:
        client = TopstepXClient()
        account_id = get_primary_account_id(client)
        
        if not account_id:
            return

        orders_response = client.get_orders(account_id)
        
        if not orders_response or not orders_response.get("orders"):
            console.print("[yellow]Актив ордерлар топилмади.[/yellow]")
            return

        active_orders = [o for o in orders_response["orders"] if o.get("status") == 0] # 0 = Working

        if not active_orders:
            console.print("[green]Ҳозирда актив ордерлар йўқ.[/green]")
            return

        table = Table(title="Актив Ордерлар", style="cyan", show_header=True, header_style="bold magenta")
        table.add_column("Order ID", style="dim", width=30)
        table.add_column("Инструмент")
        table.add_column("Йўналиш")
        table.add_column("Тип")
        table.add_column("Ҳажм")
        table.add_column("Нарх")
        table.add_column("Жойлашган Вақти")

        for order in active_orders:
            side = "[bold green]BUY[/bold green]" if order.get('side', 0) == 0 else "[bold red]SELL[/bold red]"
            order_type_map = {0: "Limit", 1: "Stop", 2: "Market"}
            order_type = order_type_map.get(order.get('type', 0), "N/A")
            price = order.get('limitPrice') or order.get('stopPrice') or "N/A"
            
            table.add_row(
                order.get("orderId"),
                order.get("contractId"),
                side,
                order_type,
                str(order.get("size")),
                str(price),
                order.get("timestamp")
            )
        
        console.print(table)

    except Exception as e:
        console.print(f"[red]Ордерларни олишда хатолик: {e}[/red]")

# --- Placeholder for future functions ---
def cancel_order_command(args: str):
    console.print(f"[yellow]WIP: Ордерни бекор қилиш: {args}[/yellow]")

def modify_order_command(args: str):
    console.print(f"[yellow]WIP: Ордерни ўзгартириш: {args}[/yellow]")

def place_test_order(args: str):
    """Places a hardcoded test order to debug the API client."""
    console.print("[bold yellow]--- API ОРДЕР ТЕСТИ ---[/bold yellow]")
    try:
        client = TopstepXClient()
        account_id = get_primary_account_id(client)
        if not account_id:
            return

        console.print(f"Тест учун ҳисоб ID: {account_id}")
        console.print("Параметрлар: SELL 1 GC @ 4000.0 (Limit, GTC)")

        order_result = client.place_order(
            contract_id="GC",
            account_id=account_id,
            side=1,  # 1 = Sell
            order_type=0,  # 0 = Limit
            size=1,
            limit_price=4000.0
        )

        if order_result and order_result.get("success"):
            console.print("[bold green]✅ Тест ордери муваффақиятли жойлаштирилди![/bold green]")
            from rich import print_json
            print_json(data=order_result)
        else:
            console.print("[bold red]❌ Тест ордерини жойлаштиришда хатолик юз берди.[/bold red]")
            if order_result:
                from rich import print_json
                print_json(data=order_result)
            else:
                console.print("[red]API'дан жавоб олинмади.[/red]")

    except Exception as e:
        console.print(f"[red]Тест ордерини жойлаштиришда кутилмаган хатолик: {e}[/red]")
        import traceback
        traceback.print_exc()

def place_market_order_test(args: str):
    """Places a hardcoded MARKET order to isolate errorCode: 8."""
    console.print("[bold magenta]--- API МАРКЕТ ОРДЕР ТЕСТИ ---[/bold magenta]")
    try:
        client = TopstepXClient()
        account_id = get_primary_account_id(client)
        if not account_id:
            return

        console.print(f"Тест учун ҳисоб ID: {account_id}")
        console.print("Параметрлар: SELL 1 GC (Market)")

        # Market order учун order_type=2 (API учун ҳам 2)
        order_result = client.place_order(
            contract_id="GC",
            account_id=account_id,
            side=1,  # 1 = Sell
            order_type=2,  # 2 = Market
            size=1
        )

        if order_result and order_result.get("success"):
            console.print("[bold green]✅ Тест МАРКЕТ ордери муваффақиятли жойлаштирилди![/bold green]")
            from rich import print_json
            print_json(data=order_result)
        else:
            console.print("[bold red]❌ Тест МАРКЕТ ордерини жойлаштиришда хатолик юз берди.[/bold red]")
            if order_result:
                from rich import print_json
                print_json(data=order_result)
            else:
                console.print("[red]API'дан жавоб олинмади.[/red]")

    except Exception as e:
        console.print(f"[red]Тест МАРКЕТ ордерини жойлаштиришда кутилмаган хатолик: {e}[/red]")
        import traceback
        traceback.print_exc()


