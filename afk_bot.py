import os
import re
import time
import datetime
import threading
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from fuzzywuzzy import fuzz

# Load environment variables
load_dotenv()

# Initialize the Slack app
app = App(token=os.environ.get("SLACK_USER_TOKEN"))  # Используем user token

# User status tracker
user_statuses = {}

# Предварительно скомпилированные регулярные выражения
AFK_PATTERN = re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)', re.IGNORECASE)
TIME_PATTERNS = {
    'range': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)', re.IGNORECASE),
    'hours': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(\d+(?:[.,]\d+)?)\s*(?:h|ч|час|часа|часов)', re.IGNORECASE),
    'minutes': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(\d+(?:[.,]\d+)?)\s*(?:m|min|мин|минут|минуты)', re.IGNORECASE),
    'half_hour': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(?:полчаса|half\s*hour)', re.IGNORECASE),
    'hour_word': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(?:час|one\s*hour)', re.IGNORECASE),
    'mix_1': re.compile(r'(?:еще|ещё|still|more)\s+(\d+)\s*(?:мин|min|m|минут|минуты)', re.IGNORECASE),
    'mix_2': re.compile(r'.*(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл).*(\d+)\s*(?:мин|min|m|минут|минуты)', re.IGNORECASE),
    'until_time': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл).*(?:до|until|till)\s+(\d{1,2})[:\.]?(\d{0,2})', re.IGNORECASE),
    'simple_number': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(\d+(?:[.,]\d+)?)', re.IGNORECASE)
}

# Кэш для быстрого распознавания общих команд
COMMON_COMMANDS = {
    'afk 30': 30,
    'afk 1': 60,
    'afk 2': 120,
    'afk 5': 300,
    'afk 10': 600,
    'afk 15': 900,
    'afk 20': 1200,
    'afk 60': 3600,
    'афк 30': 30,
    'афк 1': 60,
    'афк 2': 120,
    'афк 5': 300,
    'афк 10': 600,
    'афк 15': 900,
    'афк 20': 1200,
    'афк 60': 3600
}

# Общий список слов, похожих на afk для быстрой проверки
AFK_WORDS = {'afk', 'афк', 'аfk', 'afл', 'афл', 'аfл', 'аfк'}

def is_similar_to_afk(word):
    """Быстрая проверка на сходство с AFK"""
    word_lower = word.lower()
    # Сначала проверяем точное совпадение (быстрее)
    if word_lower in AFK_WORDS:
        return True
    # Потом используем более дорогую операцию нечеткого сравнения
    return fuzz.ratio(word_lower, "afk") > 75 or fuzz.ratio(word_lower, "афк") > 75

def parse_time_to_minutes(message_text):
    """Оптимизированный парсер времени из сообщения"""
    
    # Проверяем наличие в кэше часто используемых команд (самый быстрый путь)
    message_lower = message_text.lower().strip()
    if message_lower in COMMON_COMMANDS:
        return COMMON_COMMANDS[message_lower]
    
    # Проверяем простой формат "афк/afk число"
    words = message_lower.split()
    if len(words) >= 2:
        for i, word in enumerate(words):
            if word in AFK_WORDS and i + 1 < len(words) and words[i + 1].isdigit():
                num = float(words[i + 1])
                if num <= 24:  # Если число ≤ 24, считаем часами
                    return int(num * 60)
                return int(num)  # Иначе считаем минутами
    
    # Полный анализ с регулярными выражениями для сложных случаев
    # Проверяем наличие AFK в сообщении
    if not AFK_PATTERN.search(message_text):
        # Если AFK не найден, проверяем на опечатки только если сообщение короткое
        if len(message_text) <= 30:  
            # Для коротких сообщений проверяем каждое слово на сходство с AFK
            for word in words:
                if is_similar_to_afk(word):
                    # Заменяем слово на афк для дальнейшего анализа
                    message_text = message_text.replace(word, "афк")
                    break
        else:
            return None  # Для длинных сообщений без явного AFK просто пропускаем
    
    # Проверка шаблонов от наиболее специфичных к наиболее общим
    # Диапазон: "афк 1-1.5"
    match = TIME_PATTERNS['range'].search(message_text)
    if match:
        start, end = match.groups()
        end = float(end.replace(',', '.'))
        if end <= 24:
            return int(end * 60)
        return int(end)
    
    # Часы: "афк 1h"
    match = TIME_PATTERNS['hours'].search(message_text)
    if match:
        hours = float(match.group(1).replace(',', '.'))
        return int(hours * 60)
    
    # Минуты: "афк 30m"
    match = TIME_PATTERNS['minutes'].search(message_text)
    if match:
        minutes = float(match.group(1).replace(',', '.'))
        return int(minutes)
    
    # Полчаса: "афк полчаса"
    if TIME_PATTERNS['half_hour'].search(message_text):
        return 30
    
    # Час: "афк час"
    if TIME_PATTERNS['hour_word'].search(message_text):
        return 60
    
    # Смешанный формат 1: "Еще 30 мин афк"
    match = TIME_PATTERNS['mix_1'].search(message_text)
    if match:
        return int(match.group(1))
    
    # Смешанный формат 2: "Плохо себя чувствую. АФК минут 40"
    match = TIME_PATTERNS['mix_2'].search(message_text)
    if match:
        return int(match.group(1))
    
    # До времени: "АФК до 12"
    match = TIME_PATTERNS['until_time'].search(message_text)
    if match:
        hours = int(match.group(1))
        minutes = 0
        if match.group(2):
            minutes = int(match.group(2))
        
        now = datetime.datetime.now()
        target_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        
        if target_time < now:
            target_time += datetime.timedelta(days=1)
        
        diff = target_time - now
        return int(diff.total_seconds() / 60)
    
    # Простое число: "афк 30"
    match = TIME_PATTERNS['simple_number'].search(message_text)
    if match:
        num = float(match.group(1).replace(',', '.'))
        if num <= 24:
            return int(num * 60)
        return int(num)
    
    return None

def set_user_status(client, user_id, minutes):
    """Set user's status to AFK for the specified number of minutes"""
    
    # Проверяем текущий статус пользователя в Slack
    try:
        current_profile = client.users_profile_get(user=user_id)
        current_status_text = current_profile["profile"]["status_text"]
        current_status_emoji = current_profile["profile"]["status_emoji"]
        
        # Если статус в Slack пустой, но бот считает что статус активен,
        # сбрасываем отслеживание этого статуса
        if not current_status_text and not current_status_emoji and user_id in user_statuses:
            del user_statuses[user_id]
    except Exception as e:
        print(f"Error checking current status: {e}")
    
    # Проверяем, не установлен ли уже статус через бота
    if user_id in user_statuses and user_statuses[user_id]["expiry"] > time.time():
        # Status already set and not expired, don't update
        return
    
    # Calculate expiry time
    expiry = time.time() + (minutes * 60)
    
    # Format minutes for display
    if minutes >= 60:
        hours = minutes // 60
        remaining_mins = minutes % 60
        if remaining_mins == 0:
            status_text = f"AFK на {hours} {'час' if hours == 1 else 'часа' if 2 <= hours <= 4 else 'часов'}"
        else:
            status_text = f"AFK на {hours}:{remaining_mins:02d}"
    else:
        status_text = f"AFK на {minutes} {'минуту' if minutes == 1 else 'минуты' if 2 <= minutes % 10 <= 4 and (minutes < 10 or minutes > 20) else 'минут'}"
    
    # Пробуем использовать разные эмодзи по очереди, пока один не сработает
    emoji_options = [":afk:", ":zzz:", ":sleeping:", ":clock3:", ":coffee:"]
    
    success = False
    error_message = ""
    
    for emoji in emoji_options:
        try:
            client.users_profile_set(
                user=user_id,
                profile={
                    "status_text": status_text,
                    "status_emoji": emoji,
                    "status_expiration": int(expiry)
                }
            )
            
            print(f"Установлен статус AFK для пользователя {user_id} на {minutes} минут с эмодзи {emoji}")
            success = True
            
            # Store status information
            user_statuses[user_id] = {
                "expiry": expiry,
                "minutes": minutes
            }
            
            # Schedule status cleanup
            threading.Timer(minutes * 60, clear_status, args=[client, user_id, expiry]).start()
            
            # Успешно установили статус, выходим из цикла
            break
            
        except Exception as e:
            error_message = str(e)
            print(f"Ошибка при установке статуса с эмодзи {emoji}: {e}")
            continue  # Пробуем следующий эмодзи
    
    if not success:
        print(f"Не удалось установить статус AFK: {error_message}")

def clear_status(client, user_id, expected_expiry):
    """Clear the user's status if it hasn't been changed"""
    if user_id in user_statuses and user_statuses[user_id]["expiry"] == expected_expiry:
        # Status hasn't been updated, clear it
        try:
            client.users_profile_set(
                user=user_id,
                profile={
                    "status_text": "",
                    "status_emoji": "",
                    "status_expiration": 0
                }
            )
            # Remove from tracking
            del user_statuses[user_id]
            print(f"Статус AFK для пользователя {user_id} удален по истечению времени")
        except Exception as e:
            print(f"Error clearing status: {e}")

@app.event("message")
def handle_message_events(body, client):
    # Process only new messages (not updates or deletions)
    event = body["event"]
    
    # Skip thread replies, edited messages, bot messages
    if (event.get("thread_ts") or 
        event.get("subtype") == "message_changed" or 
        event.get("subtype") == "message_deleted" or
        event.get("bot_id")):
        return
    
    user_id = event.get("user")
    message_text = event.get("text", "")
    
    print(f"Сообщение: '{message_text}'")
    
    # Оптимизация: сначала быстрая проверка на наличие AFK в сообщении
    if not any(word in message_text.lower() for word in AFK_WORDS) and not "afk" in message_text.lower() and not "афк" in message_text.lower():
        # Быстрая проверка не нашла упоминания AFK, пропускаем дальнейший анализ
        return
    
    # Parse time from message
    minutes = parse_time_to_minutes(message_text)
    
    if minutes:
        print(f"Время: {minutes} минут")
        set_user_status(client, user_id, minutes)

if __name__ == "__main__":
    print(f"SLACK_USER_TOKEN: {os.environ.get('SLACK_USER_TOKEN') is not None}")
    print(f"SLACK_APP_TOKEN: {os.environ.get('SLACK_APP_TOKEN') is not None}")
    
    handler = SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    print("⚡️ AFK бот запущен!")
    
    try:
        handler.start()
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
        import traceback
        traceback.print_exc() 