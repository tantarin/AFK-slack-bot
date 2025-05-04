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
    'minutes': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(\d+(?:[.,]\d+)?)\s*(?:m|min|мин|минут|минуты|минута|минуту)', re.IGNORECASE),
    'half_hour': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(?:полчаса|half\s*hour)', re.IGNORECASE),
    'hour_word': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(?:час|one\s*hour)', re.IGNORECASE),
    'mix_1': re.compile(r'(?:еще|ещё|still|more)\s+(\d+)\s*(?:мин|min|m|минут|минуты|минута|минуту)', re.IGNORECASE),
    'mix_2': re.compile(r'.*(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл).*?(\d+)[\s\-_]*(?:мин|min|m|минут|минуты|минута|минуту)', re.IGNORECASE),
    'until_time': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл).*(?:до|until|till)\s+(\d{1,2})[:\.]?(\d{0,2})', re.IGNORECASE),
    'simple_number': re.compile(r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(\d+(?:[.,]\d+)?)', re.IGNORECASE)
}

# Кэш для быстрого распознавания общих команд
COMMON_COMMANDS = {
    # Простые числовые форматы
    'afk 1': 60,  # 1 час = 60 минут
    'afk 2': 120,  # 2 часа = 120 минут
    'afk 3': 180,  # 3 часа = 180 минут
    'afk 4': 240,  # 4 часа = 240 минут
    'afk 5': 5,
    'afk 10': 10,
    'afk 15': 15,
    'afk 20': 20,
    'afk 30': 30,
    'afk 40': 40,
    'afk 45': 45,
    'afk 50': 50,
    'afk 60': 60,
    'афк 1': 60,  # 1 час = 60 минут
    'афк 2': 120,  # 2 часа = 120 минут
    'афк 3': 180,  # 3 часа = 180 минут
    'афк 4': 240,  # 4 часа = 240 минут
    'афк 5': 5,
    'афк 10': 10,
    'афк 15': 15,
    'афк 20': 20,
    'афк 30': 30,
    'афк 40': 40,
    'афк 45': 45, 
    'афк 50': 50,
    'афк 60': 60,
    'АФК 1': 60,  # 1 час = 60 минут
    'АФК 20': 20,
    'АФК 30': 30,
    'АФК 40': 40,
    'Афк 1': 60,  # 1 час = 60 минут
    'Афк 20': 20,
    'Афк 30': 30,
    'Афк 40': 40,
    
    # С указанием времени
    'афк час': 60,
    'афк полчаса': 30,
    'AFK час': 60,
    'AFK полчаса': 30,
    
    # С буквой m/м
    'afk 15m': 15,
    'afk 20m': 20,
    'afk 30m': 30,
    'afk 40m': 40,
    
    # С буквой h/ч
    'afk 1h': 60,
    'афк 1ч': 60,
    
    # С явным указанием минут
    'afk 10 мин': 10,
    'afk 15 мин': 15,
    'afk 20 мин': 20,
    'afk 30 мин': 30,
    'afk 40 мин': 40,
    'афк 10 мин': 10,
    'афк 15 мин': 15,
    'афк 20 мин': 20,
    'афк 30 мин': 30,
    'афк 40 мин': 40,
    'АФК 30 мин': 30,
    
    # С явным указанием часов
    'afk 1 час': 60,
    'афк 1 час': 60,
    'Afk 1 час': 60,
    
    # Диапазоны
    'afk 15-20': 20,
    'afk 1-1.5': 90,
    'афк 30-40': 40,
    'афк 30-60': 60,
    
    # Другие форматы
    'Еще 30 мин афк': 30
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
    
    # Дополнительный отладочный вывод для минут
    debugging_minutes = "мин" in message_text.lower() or "min" in message_text.lower()
    if debugging_minutes:
        print(f"DEBUG: Начинаем парсинг времени для '{message_text}'")
    
    # Проверяем наличие в кэше часто используемых команд (самый быстрый путь)
    message_lower = message_text.lower().strip()
    if message_lower in COMMON_COMMANDS:
        if debugging_minutes:
            print(f"DEBUG: Найдено в кэше команд: {COMMON_COMMANDS[message_lower]} минут")
        minutes = COMMON_COMMANDS[message_lower]
        return (min(minutes, 240), minutes)  # (capped, original)
    
    # Проверяем наличие AFK в сообщении
    if not AFK_PATTERN.search(message_text):
        # Если AFK не найден, проверяем на опечатки только если сообщение короткое
        words = message_lower.split()
        if len(message_text) <= 30:  
            # Для коротких сообщений проверяем каждое слово на сходство с AFK
            for word in words:
                if is_similar_to_afk(word):
                    # Заменяем слово на афк для дальнейшего анализа
                    message_text = message_text.replace(word, "афк")
                    break
        else:
            return None  # Для длинных сообщений без явного AFK просто пропускаем
    
    # Сначала проверяем явные указания на минуты, часы и т.д.
    
    # Минуты: "афк 30m" or "афк 1 мин"
    match = TIME_PATTERNS['minutes'].search(message_text)
    if match:
        minutes = float(match.group(1).replace(',', '.'))
        if debugging_minutes:
            print(f"DEBUG: Шаблон 'minutes' сработал: {minutes} минут")
        return (min(int(minutes), 240), minutes)  # Ограничение в 4 часа
    elif debugging_minutes:
        print(f"DEBUG: Шаблон 'minutes' НЕ сработал")
        
        # Ручная проверка регулярного выражения для отладки
        import re
        pattern = r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)\s+(\d+(?:[.,]\d+)?)\s*(?:m|min|мин|минут|минуты|минута|минуту)'
        manual_match = re.search(pattern, message_text, re.IGNORECASE)
        if manual_match:
            print(f"DEBUG: Ручная проверка шаблона успешна: {manual_match.group(1)}")
        else:
            print(f"DEBUG: Ручная проверка шаблона НЕ успешна")
            print(f"DEBUG: Проверяем части выражения:")
            
            # Проверка наличия AFK
            afk_pattern = r'(?:афк|afk|АФК|AFK|афл|afл|аfк|аfл)'
            if re.search(afk_pattern, message_text, re.IGNORECASE):
                print(f"DEBUG: AFK найден в сообщении")
            else:
                print(f"DEBUG: AFK НЕ найден в сообщении")
                
            # Проверка формата числа
            if re.search(r'\d+(?:[.,]\d+)?', message_text):
                print(f"DEBUG: Число найдено в сообщении")
            else:
                print(f"DEBUG: Число НЕ найдено в сообщении")
                
            # Проверка минут
            if re.search(r'(?:m|min|мин|минут|минуты|минута|минуту)', message_text, re.IGNORECASE):
                print(f"DEBUG: Обозначение минут найдено в сообщении")
            else:
                print(f"DEBUG: Обозначение минут НЕ найдено в сообщении")
    
    # Часы: "афк 1h"
    match = TIME_PATTERNS['hours'].search(message_text)
    if match:
        hours = float(match.group(1).replace(',', '.'))
        minutes = int(hours * 60)
        return (min(minutes, 240), minutes)  # Ограничение в 4 часа
    
    # Полчаса: "афк полчаса"
    if TIME_PATTERNS['half_hour'].search(message_text):
        return (30, 30)  # Не нужно ограничивать, меньше 4 часов
    
    # Час: "афк час"
    if TIME_PATTERNS['hour_word'].search(message_text):
        return (60, 60)  # Не нужно ограничивать, меньше 4 часов
    
    # Теперь проверяем более простые форматы
    
    # Проверяем простой формат "афк/afk число"
    words = message_lower.split()
    if len(words) >= 2:
        for i, word in enumerate(words):
            if word in AFK_WORDS and i + 1 < len(words) and words[i + 1].isdigit():
                num = float(words[i + 1])
                # Если число меньше 5, считаем часами
                if num < 5:
                    minutes = int(num * 60)
                else:
                    minutes = int(num)
                return (min(minutes, 240), minutes)  # Ограничение в 4 часа
    
    # Проверка остальных шаблонов
    
    # Диапазон: "афк 1-1.5" или "афк 15-20"
    match = TIME_PATTERNS['range'].search(message_text)
    if match:
        start, end = match.groups()
        end = float(end.replace(',', '.'))
        # Все числа в диапазоне считаем минутами
        minutes = int(end)
        # Ограничение: не более 4 часов (240 минут)
        if minutes > 240:
            minutes = 240
        return (minutes, minutes)
    
    # Смешанный формат 1: "Еще 30 мин афк"
    match = TIME_PATTERNS['mix_1'].search(message_text)
    if match:
        minutes = int(match.group(1))
        return (min(minutes, 240), minutes)  # Ограничение в 4 часа
    
    # Смешанный формат 2: "Плохо себя чувствую. АФК минут 40"
    match = TIME_PATTERNS['mix_2'].search(message_text)
    if match:
        minutes = int(match.group(1))
        return (min(minutes, 240), minutes)  # Ограничение в 4 часа
    
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
        minutes = int(diff.total_seconds() / 60)
        return (min(minutes, 240), minutes)  # Ограничение в 4 часа
    
    # Простое число: "афк 30"
    match = TIME_PATTERNS['simple_number'].search(message_text)
    if match:
        num = float(match.group(1).replace(',', '.'))
        # Если число меньше 5, считаем часами
        if num < 5:
            minutes = int(num * 60)
        else:
            minutes = int(num)
        # Иначе считаем минутами
        return (min(minutes, 240), minutes)  # Ограничение в 4 часа
    
    return None

def set_user_status(client, user_id, minutes, original_minutes=None):
    """Set user's status to AFK for the specified number of minutes"""
    
    # Если запрошенное время больше 4 часов, выводим сообщение о ограничении
    if original_minutes is not None and original_minutes > minutes:
        try:
            client.chat_postMessage(
                channel=user_id,
                text=f"⚠️ Ваше запрошенное время AFK ({original_minutes} минут) было ограничено до 4 часов (240 минут)."
            )
        except Exception as e:
            print(f"Не удалось отправить уведомление о лимите: {e}")
    
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
    has_existing_afk = False
    if user_id in user_statuses and user_statuses[user_id]["expiry"] > time.time():
        # Status already set and not expired
        has_existing_afk = True
        previous_minutes = user_statuses[user_id]["minutes"]
        print(f"Пользователь {user_id} уже имеет статус AFK на {previous_minutes} минут. Заменяем на {minutes} минут.")
    
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
            
            if has_existing_afk:
                print(f"Обновлен статус AFK для пользователя {user_id} на {minutes} минут с эмодзи {emoji}")
            else:
                print(f"Установлен статус AFK для пользователя {user_id} на {minutes} минут с эмодзи {emoji}")
            
            success = True
            
            # Store status information
            user_statuses[user_id] = {
                "expiry": expiry,
                "minutes": minutes
            }
            
            # If there was an existing timer, we need to cancel it
            # Since we can't easily cancel the timer, we'll just let it run and have it
            # check the expected_expiry when it tries to clear
            
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
    
    # Отладочный вывод для проверки распознавания минут
    if "мин" in message_text.lower() or "min" in message_text.lower():
        print(f"Обнаружено указание на минуты в сообщении: '{message_text}'")
        # Проверяем работу шаблона minutes
        match = TIME_PATTERNS['minutes'].search(message_text)
        if match:
            print(f"Шаблон 'minutes' сработал: найдено {match.group(1)} минут")
        else:
            print(f"Шаблон 'minutes' НЕ сработал для текста '{message_text}'")
    
    # Parse time from message
    result = parse_time_to_minutes(message_text)
    
    if result:
        capped_minutes, original_minutes = result
        if capped_minutes < original_minutes:
            print(f"Время ограничено: запрошено {original_minutes} мин, установлено {capped_minutes} мин")
        else:
            print(f"Время: {capped_minutes} минут")
        set_user_status(client, user_id, capped_minutes, original_minutes)

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