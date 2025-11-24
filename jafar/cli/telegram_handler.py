import os
import requests
from rich.console import Console
from dotenv import load_dotenv
import re
import json

console = Console()

def escape_markdown_v2(text: str) -> str:
    """
    Экранирует специальные символы MarkdownV2 в тексте.
    """
    # Экранируем обратный слэш первым, чтобы избежать проблем
    text = text.replace('\\', '\\\\')

    # Список остальных специальных символов в MarkdownV2, которые нужно экранировать
    # https://core.telegram.org/bots/api#markdownv2-style
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    for char in special_chars:
        text = text.replace(char, '\\' + char)
    return text




def send_telegram_message(message: str, parse_mode: str = "MarkdownV2"):
    """
    Отправляет текстовое сообщение в Telegram канал.

    Args:
        message (str): Текст сообщения для отправки.
        parse_mode (str): Режим парсинга сообщения (MarkdownV2, HTML или None).
    """
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    if not bot_token or not channel_id:
        console.print("[bold red]❌ Ошибка: TELEGRAM_BOT_TOKEN и TELEGRAM_CHANNEL_ID должны быть установлены в .env файле.[/bold red]")
        return



    # Экранируем сообщение, если используется MarkdownV2
    if parse_mode == "MarkdownV2":
        message = escape_markdown_v2(message)

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": channel_id,
        "text": message,
    }
    if parse_mode:
        data["parse_mode"] = parse_mode

    try:
        response = requests.post(url, data=data, timeout=10) # Added timeout
        response.raise_for_status()
        response_json = response.json()

        if response_json.get("ok"):
            # Don't print success message to avoid cluttering the CLI
            pass
        else:
            error_description = response_json.get("description")
            console.print(f"[bold red]❌ Telegram API хатоси: {error_description}[/bold red]")

    except requests.exceptions.SSLError as e:
        console.print(f"[bold yellow]⚠️ Telegram'га юборишда SSL хатоси (тармоқ блокланган бўлиши мумкин): {e}[/bold yellow]")
    except requests.exceptions.RequestException as e:
        console.print(f"[bold yellow]⚠️ Telegram'га юборишда тармоқ хатоси: {e}[/bold yellow]")
    except Exception as e:
        console.print(f"[bold red]❌ Telegram'га юборишда кутилмаган хатолик: {e}[/bold red]")

def send_telegram_photo(photo_path: str, caption: str = None, parse_mode: str = "MarkdownV2"):
    """
    Отправляет фотографию в Telegram канал с подписью.

    Args:
        photo_path (str): Путь к файлу фотографии для отправки.
        caption (str): Подпись к фотографии.
        parse_mode (str): Режим парсинга подписи (MarkdownV2, HTML или None).
    """
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    if not bot_token or not channel_id:
        console.print("[bold red]❌ Ошибка: TELEGRAM_BOT_TOKEN и TELEGRAM_CHANNEL_ID должны быть установлены в .env файле.[/bold red]")
        return

    if not os.path.exists(photo_path):
        console.print(f"[bold red]❌ Ошибка: Файл фотографии не найден по пути: {photo_path}[/bold red]")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    try:
        with open(photo_path, 'rb') as photo_file:


            console.print(f"[bold blue]Отправка фотографии {os.path.basename(photo_path)} в Telegram...[/bold blue]")
            response = requests.post(url, files=files, data=data)
            response_json = response.json() # Получаем ответ от API
            console.print(f"[bold yellow]Ответ от Telegram API: {response_json}[/bold yellow]") # Выводим ответ
            response.raise_for_status()

        if response_json.get("ok"):
            console.print("[bold green]✅ Фотография успешно отправлена в Telegram![/bold green]")
        else:
            error_description = response_json.get("description")
            console.print(f"[bold red]❌ Ошибка от Telegram API: {error_description}[/bold red]")

    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]❌ Ошибка сети при отправке фотографии: {e}[/bold red]")
    except Exception as e:
        console.print(f"[bold red]❌ Произошла непредвиденная ошибка: {e}[/bold red]")
    finally:
        for f in files.values():
            f.close()

def send_telegram_media_group(photo_paths: list, caption: str = None, parse_mode: str = "MarkdownV2"):
    """
    Отправляет группу фотографий в Telegram канал с одной подписью.

    Args:
        photo_paths (list): Список путей к файлам фотографий для отправки.
        caption (str): Подпись к группе фотографий.
        parse_mode (str): Режим парсинга подписи (MarkdownV2, HTML или None).
    """
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    if not bot_token or not channel_id:
        console.print("[bold red]❌ Ошибка: TELEGRAM_BOT_TOKEN и TELEGRAM_CHANNEL_ID должны быть установлены в .env файле.[/bold red]")
        return

    if not photo_paths:
        console.print("[bold red]❌ Ошибка: Список путей к фотографиям пуст.[/bold red]")
        return

    media = []
    files = {}
    for i, photo_path in enumerate(photo_paths):
        if not os.path.exists(photo_path):
            console.print(f"[bold red]❌ Ошибка: Файл фотографии не найден по пути: {photo_path}[/bold red]")
            return
        
        file_name = f"photo_{i}.png"
        files[file_name] = open(photo_path, 'rb')
        
        media_item = {
            "type": "photo",
            "media": f"attach://{file_name}"
        }
        if i == 0 and caption:
            if parse_mode == "MarkdownV2":
                caption = escape_markdown_v2(caption)
            media_item["caption"] = caption
            if parse_mode:
                media_item["parse_mode"] = parse_mode
        media.append(media_item)

    url = f"https://api.telegram.org/bot{bot_token}/sendMediaGroup"
    data = {
        "chat_id": channel_id,
        "media": json.dumps(media)
    }

    try:
        console.print(f"[bold blue]Отправка группы фотографий в Telegram...[/bold blue]")
        response = requests.post(url, files=files, data=data)
        response_json = response.json() # Получаем ответ от API
        console.print(f"[bold yellow]Ответ от Telegram API: {response_json}[/bold yellow]") # Выводим ответ
        response.raise_for_status()

        if response_json.get("ok"):
            console.print("[bold green]✅ Группа фотографий успешно отправлена в Telegram![/bold green]")
        else:
            error_description = response_json.get("description")
            console.print(f"[bold red]❌ Ошибка от Telegram API: {error_description}[/bold red]")

    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]❌ Ошибка сети при отправке группы фотографий: {e}[/bold red]")
    except Exception as e:
        console.print(f"[bold red]❌ Произошла непредвиденная ошибка: {e}[/bold red]")
    finally:
        for f in files.values():
            f.close()

def send_telegram_document(document_path: str, caption: str = None, parse_mode: str = "MarkdownV2"):
    """
    Отправляет документ в Telegram канал с подписью.

    Args:
        document_path (str): Путь к файлу документа для отправки.
        caption (str): Подпись к документу.
        parse_mode (str): Режим парсинга подписи (MarkdownV2, HTML или None).
    """
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    if not bot_token or not channel_id:
        console.print("[bold red]❌ Ошибка: TELEGRAM_BOT_TOKEN и TELEGRAM_CHANNEL_ID должны быть установлены в .env файле.[/bold red]")
        return

    if not os.path.exists(document_path):
        console.print(f"[bold red]❌ Ошибка: Файл документа не найден по пути: {document_path}[/bold red]")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"

    try:
        with open(document_path, 'rb') as document_file:
            files = {'document': document_file}
            data = {'chat_id': channel_id}
            if caption:
                if parse_mode == "MarkdownV2":
                    caption = escape_markdown_v2(caption)
                data['caption'] = caption
                if parse_mode:
                    data['parse_mode'] = parse_mode

            console.print(f"[bold blue]Отправка документа {os.path.basename(document_path)} в Telegram...[/bold blue]")
            response = requests.post(url, files=files, data=data)
            response_json = response.json() # Получаем ответ от API
            console.print(f"[bold yellow]Ответ от Telegram API: {response_json}[/bold yellow]") # Выводим ответ
            response.raise_for_status()

        if response_json.get("ok"):
            console.print("[bold green]✅ Документ успешно отправлен в Telegram![/bold green]")
        else:
            error_description = response_json.get("description")
            console.print(f"[bold red]❌ Ошибка от Telegram API: {error_description}[/bold red]")

    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]❌ Ошибка сети при отправке документа: {e}[/bold red]")
    except Exception as e:
        console.print(f"[bold red]❌ Произошла непредвиденная ошибка: {e}[/bold red]")
    finally:
        for f in files.values():
            f.close()

def send_long_telegram_message(message: str, parse_mode: str = "MarkdownV2"):
    """Отправляет длинное текстовое сообщение, разбивая его на части."""
    MAX_LENGTH = 4096
    if len(message) <= MAX_LENGTH:
        send_telegram_message(message, parse_mode)
        return

    parts = []
    current_part = ""
    for line in message.split('\n'):
        if len(current_part) + len(line) + 1 > MAX_LENGTH:
            parts.append(current_part)
            current_part = line
        else:
            current_part += "\n" + line
    parts.append(current_part)

    for part in parts:
        if part.strip():
            send_telegram_message(part, parse_mode)
