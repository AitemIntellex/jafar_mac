import os
import shlex
import subprocess
import time
import requests
from dotenv import load_dotenv
from pathlib import Path

def load_jafar_dotenv():
    """
    Ищет .env файл в корне проекта и в родительской директории,
    загружает первый найденный.
    """
    # Определяем корень проекта относительно текущего файла
    project_root = Path(__file__).parent.parent.parent.parent
    
    # Список возможных путей к .env файлу
    possible_paths = [
        project_root / ".env",          # /Users/macbook/projects/jafar/.env
        project_root.parent / ".env"    # /Users/macbook/projects/.env
    ]

    for path in possible_paths:
        if path.exists():
            print(f"DEBUG: Загрузка .env файла из: {path}")
            load_dotenv(dotenv_path=path)
            return True # Успешно загружен

    print("DEBUG: .env файл не найден в стандартных расположениях.")
    return False # Файл не найден

# --- .env faylini yuklash ---
load_jafar_dotenv()
MUXLISA_API_KEY = os.environ.get("MUXLISA_API_KEY")

# --- Константы ---
TEMP_AUDIO_FILE = "/Users/macbook/projects/jafar/temp/muxlisa_output.wav"

def speak_muxlisa_text(text: str):
    """
    Озвучивает текст, используя API от Muxlisa AI.
    """
    if not text.strip():
        return

    if not MUXLISA_API_KEY:
        print("Ошибка: API ключ для Muxlisa не найден в .env файле.")
        return

    url = 'https://service.muxlisa.uz/api/v2/tts'
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': MUXLISA_API_KEY
    }
    payload = {
        "text": text,
        "speaker": 1  # 1 - Мужской голос
    }

    process = None
    try:
        # 1. Отправляем запрос в Muxlisa AI
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            # 2. Сохраняем аудио-ответ во временный файл
            os.makedirs(os.path.dirname(TEMP_AUDIO_FILE), exist_ok=True)
            with open(TEMP_AUDIO_FILE, 'wb') as f:
                f.write(response.content)

            # 3. Воспроизводим аудиофайл с помощью afplay
            command = f"afplay {shlex.quote(TEMP_AUDIO_FILE)}"
            process = subprocess.Popen(command, shell=True)
            
            # Ждем завершения воспроизведения
            process.wait()
        else:
            print(f"Ошибка от Muxlisa API: {response.status_code} - {response.text}")

    except requests.exceptions.RequestException as e:
        print(f"Сетевая ошибка при обращении к Muxlisa API: {e}")
    except Exception as e:
        print(f"Ошибка синтеза речи: {e}")
    finally:
        # 4. Удаляем временный файл
        if os.path.exists(TEMP_AUDIO_FILE):
            os.remove(TEMP_AUDIO_FILE)

import re
import nltk

# Убедимся, что необходимый пакет для NLTK загружен
try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    print("Загрузка недостающих пакетов ('punkt', 'punkt_tab') для NLTK...")
    nltk.download('punkt')
    nltk.download('punkt_tab')

def speak_in_chunks(text: str, chunk_size: int = 250):
    """
    Разбивает текст на предложения и озвучивает их по очереди.
    """
    if not text.strip():
        return

    # Заменяем распространенные сокращения, чтобы NLTK не спотыкался
    text = re.sub(r'долл\.', 'долларов', text, flags=re.IGNORECASE)
    text = re.sub(r'млрд\.', 'миллиардов', text, flags=re.IGNORECASE)
    text = re.sub(r'млн\.', 'миллионов', text, flags=re.IGNORECASE)

    # Разбиваем текст на предложения
    sentences = nltk.sent_tokenize(text)

    # Озвучиваем каждое предложение
    for sentence in sentences:
        if sentence.strip():
            print(f"Озвучиваю: {sentence}")
            speak_muxlisa_text(sentence)
            time.sleep(0.3) # Небольшая пауза между предложениями
