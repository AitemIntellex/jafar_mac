import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

# --- Setup ---
load_dotenv()
console = None
try:
    from rich.console import Console
    console = Console()
except ImportError:
    pass

def _print(message: str):
    if console:
        console.print(message)
    else:
        print(message)

# --- API Key ---
MARKETAUX_API_KEY = os.environ.get("MARKETAUX_API_KEY")

# --- Main Unified Function ---

def get_unified_news(instrument: str, hours_ago: int = 48, top_n: int = 10) -> str:
    """
    Fetches news from Marketaux API, filters, and returns a formatted string.
    """
    if not MARKETAUX_API_KEY or "YOUR_MARKETAUX_API_KEY" in MARKETAUX_API_KEY:
        _print("[dim red]Marketaux API key is not configured in .env file.[/dim red]")
        return "Marketaux API key не настроен."

    _print(f"[cyan]Marketaux'дан '{instrument}' учун янгиликлар юкланмоқда...[/cyan]")
    
    # Используем параметр 'search' для поиска по ключевым словам
    url = 'https://api.marketaux.com/v1/news/all'
    params = {
        'api_token': MARKETAUX_API_KEY,
        'search': instrument,
        'language': 'en',
        'limit': 3, # Ограничение по плану Marketaux
    }

    _print(f"[dim]Marketaux request URL: {requests.Request('GET', url, params=params).prepare().url}[/dim]")

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json().get('data', [])
        
        if not data:
            return f"'{instrument}' учун Marketaux'дан янгиликлар топилмади."

        # --- Format for Prompt ---
        formatted_strings = []
        for item in data:
            # Marketaux возвращает дату в формате '2023-11-18T12:30:00.000000Z'
            published_at_str = item.get('published_at')
            if not published_at_str: continue

            try:
                published_at = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
                # Проверяем, что новость свежая
                if published_at < datetime.now(timezone.utc) - timedelta(hours=hours_ago):
                    continue

                formatted_strings.append(
                    f"- (Marketaux) {item.get('title')}: {item.get('snippet') or 'N/A'}"
                )
            except (ValueError, TypeError):
                continue
        
        if not formatted_strings:
            return f"Охирги {hours_ago} соат ичида '{instrument}' учун янгиликлар топилмади."

        _print(f"[green]{len(formatted_strings)} та долзарб янгилик топилди ва форматланди.[/green]")
        return "\n".join(formatted_strings)

    except requests.RequestException as e:
        _print(f"[dim red]Marketaux Error: {e}[/dim red]")
        if e.response:
            _print(f"[dim red]Response: {e.response.text}[/dim red]")
        return f"Marketaux API'дан янгиликлар олишда хатолик: {e}"