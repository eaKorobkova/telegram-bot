import os
import sqlite3
import logging
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(
    TEXT, DUE_DATE, PRIORITY, CUSTOM_DATE, 
    EDIT_CHOICE, EDIT_TEXT, EDIT_DATE, EDIT_PRIORITY, EDIT_CUSTOM_DATE
) = range(9)

# Приоритеты
PRIORITIES = {
    "🔴 Высокий": 3,
    "🟡 Средний": 2, 
    "🔵 Низкий": 1
}

# Конфигурация NewsAPI
NEWS_API_KEY = os.getenv('NEWS_API_KEY', '7c90fc1f9c9f46c2898f4f21684b5c57')
NEWS_API_URL = f"https://newsapi.org/v2/top-headlines?country=us&category=business&apiKey={NEWS_API_KEY}"

class TaskManager:
    def __init__(self, db_path='/tmp/tasks.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных SQLite"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    due_date TEXT,
                    priority INTEGER DEFAULT 2,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("База данных инициализирована успешно")
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")
    
    def add_task(self, user_id, text, due_date=None, priority=2):
        """Добавление новой задачи в базу данных"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            created_at = datetime.now().isoformat()
            
            cursor.execute('''
                INSERT INTO tasks (user_id, text, due_date, priority, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, text, due_date, priority, created_at))
            
            task_id = cursor.lastrowid
            
            conn.commit()
            conn.close()
            logger.info(f"Задача #{task_id} создана для пользователя {user_id}")
            return task_id
        except Exception as e:
            logger.error(f"Ошибка добавления задачи: {e}")
            return None
    
    def get_user_tasks(self, user_id, status='active'):
        """Получение задач пользователя с сортировкой по приоритету и дате"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM tasks 
                WHERE user_id = ? AND status = ?
                ORDER BY priority DESC, due_date ASC
            ''', (user_id, status))
            
            tasks = cursor.fetchall()
            conn.close()
            return tasks
        except Exception as e:
            logger.error(f"Ошибка получения задач: {e}")
            return []
    
    def get_task(self, task_id, user_id):
        """Получение конкретной задачи по ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM tasks WHERE id = ? AND user_id = ?
            ''', (task_id, user_id))
            
            task = cursor.fetchone()
            conn.close()
            return task
        except Exception as e:
            logger.error(f"Ошибка получения задачи #{task_id}: {e}")
            return None
    
    def update_task(self, task_id, user_id, **kwargs):
        """Обновление задачи"""
        try:
            if not kwargs:
                return False
                
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            set_clause = ", ".join([f"{key} = ?" for key in kwargs.keys()])
            values = list(kwargs.values()) + [task_id, user_id]
            
            cursor.execute(f'''
                UPDATE tasks SET {set_clause} 
                WHERE id = ? AND user_id = ?
            ''', values)
            
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            
            if success:
                logger.info(f"Задача #{task_id} обновлена")
            return success
        except Exception as e:
            logger.error(f"Ошибка обновления задачи #{task_id}: {e}")
            return False
    
    def delete_task(self, task_id, user_id):
        """Удаление задачи"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM tasks WHERE id = ? AND user_id = ?
            ''', (task_id, user_id))
            
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            
            if success:
                logger.info(f"Задача #{task_id} удалена")
            return success
        except Exception as e:
            logger.error(f"Ошибка удаления задачи #{task_id}: {e}")
            return False

# Глобальный экземпляр менеджера задач
task_manager = TaskManager()

def get_main_menu():
    """Главное меню команд"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("📝 Добавить задачу"), KeyboardButton("📋 Список задач")],
        [KeyboardButton("✅ Выполненные"), KeyboardButton("⚙️ Управление задачами")],
        [KeyboardButton("📰 Бизнес-новости США"), KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)

def get_back_button():
    """Кнопка Назад для инлайн-клавиатур"""
    return [InlineKeyboardButton("⬅️ Назад", callback_data="back")]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start с меню"""
    try:
        welcome_text = """
👋 Привет! Я бот-помощник для управления задачами.

Используйте меню ниже для управления задачами:
📝 Добавить задачу - создать новую задачу
📋 Список задач - показать активные задачи
✅ Выполненные - показать выполненные задачи
⚙️ Управление задачами - редактировать/удалить задачи
📰 Бизнес-новости США - свежие бизнес-новости
ℹ️ Помощь - показать справку

💡 Совет: Регулярно проверяйте список задач, чтобы ничего не забыть!
"""
        await update.message.reply_text(
            welcome_text, 
            reply_markup=get_main_menu()
        )
        logger.info(f"Пользователь {update.message.from_user.id} запустил бота")
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    try:
        help_text = """
📋 **Как пользоваться ботом:**

*Добавление задачи:*
1. Нажмите "📝 Добавить задачу"
2. Введите текст задачи
3. Выберите срок выполнения
4. Выберите приоритет

*Управление задачами:*
- "📋 Список задач" - активные задачи
- "✅ Выполненные" - выполненные задачи  
- "⚙️ Управление задачами" - редактирование и удаление

*Новости:*
- "📰 Бизнес-новости США" - свежие бизнес-новости из США

*Формат даты:*
Для кастомного ввода используйте формат:
`ГГГГ-ММ-ДД ЧЧ:ММ`
Пример: `2024-12-31 23:59`

💡 *Совет:* На каждом этапе есть кнопка "⬅️ Назад" для возврата к предыдущему шагу!
"""
        await update.message.reply_text(help_text)
    except Exception as e:
        logger.error(f"Ошибка в команде /help: {e}")

async def handle_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора из меню"""
    try:
        text = update.message.text
        
        if text == "📝 Добавить задачу":
            await add_task_start(update, context)
        elif text == "📋 Список задач":
            await list_tasks(update, context)
        elif text == "✅ Выполненные":
            await list_completed_tasks(update, context)
        elif text == "⚙️ Управление задачами":
            await show_task_management(update, context)
        elif text == "📰 Бизнес-новости США":
            await show_business_news(update, context)
        elif text == "ℹ️ Помощь":
            await help_command(update, context)
            
    except Exception as e:
        logger.error(f"Ошибка обработки меню: {e}")

# ФУНКЦИИ ДЛЯ НОВОСТЕЙ
async def show_business_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать бизнес-новости США"""
    try:
        await update.message.reply_text("📡 Загружаю последние бизнес-новости США...")
        
        news_data = await fetch_business_news()
        
        if news_data:
            await send_news_articles(update, news_data)
        else:
            await update.message.reply_text(
                "❌ Не удалось загрузить новости. Попробуйте позже."
            )
            
    except Exception as e:
        logger.error(f"Ошибка загрузки новостей: {e}")
        await update.message.reply_text("❌ Произошла ошибка при загрузке новостей.")

async def fetch_business_news():
    """Получение бизнес-новостей из США"""
    try:
        logger.info("Запрос бизнес-новостей США...")
        
        response = requests.get(NEWS_API_URL, timeout=15)
        logger.info(f"Статус ответа NewsAPI: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Статус NewsAPI: {data.get('status')}, всего новостей: {data.get('totalResults', 0)}")
            
            if data['status'] == 'ok' and data['totalResults'] > 0:
                articles = data['articles']
                logger.info(f"Успешно получено {len(articles)} бизнес-новостей")
                return articles
            else:
                logger.warning("Бизнес-новости не найдены")
                return None
        else:
            logger.error(f"Ошибка NewsAPI: {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка подключения к NewsAPI: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при получении новостей: {e}")
        return None

async def send_news_articles(update, articles):
    """Отправка новостей пользователю"""
    try:
        news_text = "📰 **🇺🇸 Бизнес-новости США**\n\n"
        
        for i, article in enumerate(articles[:8], 1):
            title = article.get('title', 'Без названия').strip()
            source = article.get('source', {}).get('name', 'Неизвестный источник')
            url = article.get('url', '#')
            description = article.get('description', '')
            published_at = article.get('publishedAt', '')
            
            # Форматируем дату
            if published_at:
                try:
                    pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                    date_str = pub_date.strftime("%d.%m.%Y %H:%M")
                except ValueError:
                    date_str = published_at[:10]
            else:
                date_str = "Дата неизвестна"
            
            news_text += f"**{i}. {title}**\n"
            if description and description != title and len(description) > 10:
                clean_description = description[:120] + "..." if len(description) > 120 else description
                news_text += f"_{clean_description}_\n"
            news_text += f"📰 *{source}* | 🕒 {date_str}\n"
            news_text += f"🔗 [Читать]({url})\n\n"
        
        # Добавляем кнопки с возможностью возврата
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить новости", callback_data="refresh_news")],
            get_back_button(),
            [InlineKeyboardButton("❌ Закрыть", callback_data="close_news")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if len(news_text) > 4000:
            news_text = news_text[:4000] + "\n\n... (новости сокращены)"
        
        await update.message.reply_text(
            news_text,
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Ошибка отправки новостей: {e}")
        await update.message.reply_text("❌ Произошла ошибка при отображении новостей.")

async def handle_news_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий с новостями"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "refresh_news":
            await query.edit_message_text("📡 Обновляю новости...")
            
            news_data = await fetch_business_news()
            if news_data:
                news_text = "📰 **🇺🇸 Бизнес-новости США**\n\n"
                
                for i, article in enumerate(news_data[:8], 1):
                    title = article.get('title', 'Без названия').strip()
                    source = article.get('source', {}).get('name', 'Неизвестный источник')
                    url = article.get('url', '#')
                    description = article.get('description', '')
                    published_at = article.get('publishedAt', '')
                    
                    if published_at:
                        try:
                            pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                            date_str = pub_date.strftime("%d.%m.%Y %H:%M")
                        except ValueError:
                            date_str = published_at[:10]
                    else:
                        date_str = "Дата неизвестна"
                    
                    news_text += f"**{i}. {title}**\n"
                    if description and description != title and len(description) > 10:
                        clean_description = description[:120] + "..." if len(description) > 120 else description
                        news_text += f"_{clean_description}_\n"
                    news_text += f"📰 *{source}* | 🕒 {date_str}\n"
                    news_text += f"🔗 [Читать]({url})\n\n"
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Обновить новости", callback_data="refresh_news")],
                    get_back_button(),
                    [InlineKeyboardButton("❌ Закрыть", callback_data="close_news")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if len(news_text) > 4000:
                    news_text = news_text[:4000] + "\n\n... (новости обновлены)"
                
                await query.edit_message_text(
                    news_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
            else:
                await query.edit_message_text("❌ Не удалось обновить новости. Попробуйте позже.")
                
        elif query.data == "close_news":
            await query.edit_message_text("📰 Просмотр новостей завершен")
        
        elif query.data == "back":
            # Возврат в главное меню
            await query.edit_message_text(
                "Возврат в главное меню",
                reply_markup=get_main_menu()
            )
            
    except Exception as e:
        logger.error(f"Ошибка обработки действий с новостей: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка.")

# ФУНКЦИИ ДЛЯ ЗАДАЧ
async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса добавления задачи"""
    try:
        context.user_data.clear()
        context.user_data['current_step'] = 'text'
        
        # ИСПРАВЛЕНО: используем "back" вместо "back_to_main"
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📝 Введите текст задачи:",
            reply_markup=reply_markup
        )
        return TEXT
    except Exception as e:
        logger.error(f"Ошибка начала добавления задачи: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте снова.")
        return ConversationHandler.END

async def add_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение текста задачи"""
    try:
        # Проверяем, не нажата ли кнопка назад через текст
        if update.message.text.lower() in ['назад', 'back', 'отмена', 'cancel']:
            await update.message.reply_text(
                "Возврат в главное меню",
                reply_markup=get_main_menu()
            )
            context.user_data.clear()
            return ConversationHandler.END
        
        context.user_data['task_text'] = update.message.text
        context.user_data['current_step'] = 'due_date'
        
        keyboard = [
            [InlineKeyboardButton("Сегодня", callback_data="today")],
            [InlineKeyboardButton("Завтра", callback_data="tomorrow")],
            [InlineKeyboardButton("Через 3 дня", callback_data="3days")],
            [InlineKeyboardButton("📅 Кастомный формат", callback_data="custom")],
            [InlineKeyboardButton("Без срока", callback_data="no_date")],
            get_back_button()
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "⏰ Укажите срок выполнения:",
            reply_markup=reply_markup
        )
        return DUE_DATE
        
    except Exception as e:
        logger.error(f"Ошибка получения текста задачи: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте снова.")
        return ConversationHandler.END

async def add_task_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора срока выполнения"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_choice = query.data
        
        if user_choice == "back":
            # Возврат к вводу текста
            context.user_data['current_step'] = 'text'
            # ИСПРАВЛЕНО: используем "back" вместо "back_to_main"
            keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "📝 Введите текст задачи:",
                reply_markup=reply_markup
            )
            return TEXT
        
        if user_choice == "custom":
            context.user_data['current_step'] = 'custom_date'
            keyboard = [get_back_button()]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "📅 Введите дату и время в формате:\n"
                "`ГГГГ-ММ-ДД ЧЧ:ММ`\n"
                "Пример: `2024-12-31 23:59`",
                reply_markup=reply_markup
            )
            return CUSTOM_DATE
        
        now = datetime.now()
        
        if user_choice == "today":
            due_date = now.replace(hour=23, minute=59, second=59)
        elif user_choice == "tomorrow":
            due_date = now + timedelta(days=1)
            due_date = due_date.replace(hour=23, minute=59, second=59)
        elif user_choice == "3days":
            due_date = now + timedelta(days=3)
            due_date = due_date.replace(hour=23, minute=59, second=59)
        else:  # no_date
            due_date = None
        
        context.user_data['due_date'] = due_date.isoformat() if due_date else None
        context.user_data['current_step'] = 'priority'
        
        keyboard = [
            [InlineKeyboardButton("🔴 Высокий", callback_data="3")],
            [InlineKeyboardButton("🟡 Средний", callback_data="2")],
            [InlineKeyboardButton("🔵 Низкий", callback_data="1")],
            get_back_button()
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎯 Выберите приоритет:",
            reply_markup=reply_markup
        )
        return PRIORITY
        
    except Exception as e:
        logger.error(f"Ошибка выбора срока: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка. Попробуйте снова.")
        return ConversationHandler.END

async def handle_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кастомного ввода даты"""
    try:
        custom_date = update.message.text.strip()
        
        if custom_date.lower() == 'назад':
            # Возврат к выбору даты
            context.user_data['current_step'] = 'due_date'
            
            keyboard = [
                [InlineKeyboardButton("Сегодня", callback_data="today")],
                [InlineKeyboardButton("Завтра", callback_data="tomorrow")],
                [InlineKeyboardButton("Через 3 дня", callback_data="3days")],
                [InlineKeyboardButton("📅 Кастомный формат", callback_data="custom")],
                [InlineKeyboardButton("Без срока", callback_data="no_date")],
                get_back_button()
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "⏰ Укажите срок выполнения:",
                reply_markup=reply_markup
            )
            return DUE_DATE
        
        try:
            due_date = datetime.strptime(custom_date, "%Y-%m-%d %H:%M")
            if due_date < datetime.now():
                await update.message.reply_text("❌ Дата должна быть в будущем! Попробуйте снова:")
                return CUSTOM_DATE
                
            context.user_data['due_date'] = due_date.isoformat()
            context.user_data['current_step'] = 'priority'
            
            keyboard = [
                [InlineKeyboardButton("🔴 Высокий", callback_data="3")],
                [InlineKeyboardButton("🟡 Средний", callback_data="2")],
                [InlineKeyboardButton("🔵 Низкий", callback_data="1")],
                get_back_button()
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "🎯 Выберите приоритет:",
                reply_markup=reply_markup
            )
            return PRIORITY
            
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат даты!\n"
                "Используйте: `ГГГГ-ММ-ДД ЧЧ:ММ`\n"
                "Пример: `2024-12-31 23:59`\n"
                "Попробуйте снова:"
            )
            return CUSTOM_DATE
            
    except Exception as e:
        logger.error(f"Ошибка обработки кастомной даты: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте снова.")
        return ConversationHandler.END

async def add_task_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора приоритета и сохранение задачи"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            # Возврат к выбору даты
            context.user_data['current_step'] = 'due_date'
            
            keyboard = [
                [InlineKeyboardButton("Сегодня", callback_data="today")],
                [InlineKeyboardButton("Завтра", callback_data="tomorrow")],
                [InlineKeyboardButton("Через 3 дня", callback_data="3days")],
                [InlineKeyboardButton("📅 Кастомный формат", callback_data="custom")],
                [InlineKeyboardButton("Без срока", callback_data="no_date")],
                get_back_button()
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "⏰ Укажите срок выполнения:",
                reply_markup=reply_markup
            )
            return DUE_DATE
        
        priority = int(query.data)
        user_id = query.from_user.id
        task_text = context.user_data['task_text']
        due_date = context.user_data.get('due_date')
        
        task_id = task_manager.add_task(user_id, task_text, due_date, priority)
        
        if not task_id:
            await query.edit_message_text("❌ Ошибка при создании задачи!")
            return ConversationHandler.END
        
        priority_text = {3: "🔴 Высокий", 2: "🟡 Средний", 1: "🔵 Низкий"}[priority]
        
        if due_date:
            due_date_str = datetime.fromisoformat(due_date).strftime("%d.%m.%Y %H:%M")
        else:
            due_date_str = "Не указан"
        
        confirmation_text = f"""
✅ Задача создана!

"{task_text}"
📅 Срок: {due_date_str}
🎯 Приоритет: {priority_text}
ID: #{task_id}

💡 Не забывайте проверять список задач!
"""
        await query.edit_message_text(confirmation_text)
        
        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Ошибка сохранения задачи: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка при сохранении задачи.")
        return ConversationHandler.END

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список активных задач"""
    try:
        user_id = update.message.from_user.id
        tasks = task_manager.get_user_tasks(user_id)
        
        if not tasks:
            await update.message.reply_text("📭 У вас нет активных задач!")
            return
        
        response = format_tasks_list(tasks, "📋 Ваши активные задачи")
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Ошибка показа списка задач: {e}")
        await update.message.reply_text("❌ Произошла ошибка при получении списка задач.")

async def list_completed_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список выполненных задач"""
    try:
        user_id = update.message.from_user.id
        tasks = task_manager.get_user_tasks(user_id, 'completed')
        
        if not tasks:
            await update.message.reply_text("📭 У вас нет выполненных задач!")
            return
        
        response = format_tasks_list(tasks, "✅ Выполненные задачи")
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Ошибка показа выполненных задач: {e}")
        await update.message.reply_text("❌ Произошла ошибка при получении списка задач.")

def format_tasks_list(tasks, title):
    """Форматирование списка задач"""
    tasks_by_priority = {3: [], 2: [], 1: []}
    
    for task in tasks:
        task_id, _, text, due_date, priority, status, created_at = task
        tasks_by_priority[priority].append((task_id, text, due_date))
    
    response = f"{title}:\n\n"
    
    for priority in [3, 2, 1]:
        priority_tasks = tasks_by_priority[priority]
        if not priority_tasks:
            continue
            
        priority_text = {3: "🔴 Высокий", 2: "🟡 Средний", 1: "🔵 Низкий"}[priority]
        response += f"{priority_text} приоритет:\n"
        
        for task_id, text, due_date in priority_tasks:
            if due_date:
                due_date_str = datetime.fromisoformat(due_date).strftime("%d.%m.%Y %H:%M")
                response += f"  #{task_id} - {text} (до {due_date_str})\n"
            else:
                response += f"  #{task_id} - {text}\n"
        
        response += "\n"
    
    return response

async def show_task_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать меню управления задачами"""
    try:
        user_id = update.message.from_user.id
        tasks = task_manager.get_user_tasks(user_id)
        
        if not tasks:
            await update.message.reply_text("📭 Нет активных задач для управления!")
            return
        
        keyboard = []
        for task in tasks:
            task_id, _, text, due_date, priority, status, created_at = task
            priority_emoji = {3: "🔴", 2: "🟡", 1: "🔵"}[priority]
            button_text = f"{priority_emoji} #{task_id}: {text[:20]}..."
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"manage_{task_id}")])
        
        keyboard.append(get_back_button())
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_manage")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "⚙️ Выберите задачу для управления:",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка показа управления задачами: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")

async def handle_task_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора задачи для управления"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "cancel_manage":
            await query.edit_message_text("❌ Управление задачами отменен")
            return
        
        if query.data == "back":
            # Возврат в главное меню
            await query.edit_message_text(
                "Возврат в главное меню",
                reply_markup=get_main_menu()
            )
            return
        
        task_id = int(query.data.split("_")[1])
        user_id = query.from_user.id
        
        task = task_manager.get_task(task_id, user_id)
        if not task:
            await query.edit_message_text("❌ Задача не найдена!")
            return
        
        context.user_data['manage_task_id'] = task_id
        
        keyboard = [
            [InlineKeyboardButton("✅ Выполнить", callback_data=f"complete_{task_id}")],
            [InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_{task_id}")],
            get_back_button()
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        task_text = task[2]
        priority = task[4]
        due_date = task[3]
        
        priority_text = {3: "🔴 Высокий", 2: "🟡 Средний", 1: "🔵 Низкий"}[priority]
        
        if due_date:
            due_date_str = datetime.fromisoformat(due_date).strftime("%d.%m.%Y %H:%M")
            task_info = f"до {due_date_str}"
        else:
            task_info = "без срока"
        
        await query.edit_message_text(
            f"📋 Задача: {task_text}\n"
            f"🎯 Приоритет: {priority_text}\n"
            f"📅 Срок: {task_info}\n\n"
            f"Выберите действие:",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка управления задачей: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка.")

async def handle_management_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий управления задачами"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "back_to_list":
            await show_task_management_from_query(query)
            return
        
        if query.data == "back":
            # Возврат к списку задач
            await show_task_management_from_query(query)
            return
        
        action, task_id = query.data.split("_")
        task_id = int(task_id)
        user_id = query.from_user.id
        
        if action == "complete":
            success = task_manager.update_task(task_id, user_id, status='completed')
            if success:
                await query.edit_message_text("✅ Задача отмечена как выполненная! 🎉")
            else:
                await query.edit_message_text("❌ Ошибка при обновлении задачи!")
                
        elif action == "delete":
            task = task_manager.get_task(task_id, user_id)
            if task:
                keyboard = [
                    [InlineKeyboardButton("✅ Да", callback_data=f"confirm_delete_{task_id}")],
                    get_back_button(),
                    [InlineKeyboardButton("❌ Нет", callback_data="cancel_delete")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"❓ Вы уверены, что хотите удалить задачу '{task[2]}'?",
                    reply_markup=reply_markup
                )
        
    except Exception as e:
        logger.error(f"Ошибка обработки действия: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка.")

async def show_task_management_from_query(query):
    """Показать управление задачами из callback query"""
    user_id = query.from_user.id
    tasks = task_manager.get_user_tasks(user_id)
    
    keyboard = []
    for task in tasks:
        task_id, _, text, due_date, priority, status, created_at = task
        priority_emoji = {3: "🔴", 2: "🟡", 1: "🔵"}[priority]
        button_text = f"{priority_emoji} #{task_id}: {text[:20]}..."
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"manage_{task_id}")])
    
    keyboard.append(get_back_button())
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_manage")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "⚙️ Выберите задачу для управления:",
        reply_markup=reply_markup
    )

async def handle_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения удаления"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "cancel_delete":
            await query.edit_message_text("❌ Удаление отменено")
            return
        
        if query.data == "back":
            # Возврат к управлению задачей
            task_id = context.user_data.get('manage_task_id')
            if task_id:
                user_id = query.from_user.id
                task = task_manager.get_task(task_id, user_id)
                if task:
                    keyboard = [
                        [InlineKeyboardButton("✅ Выполнить", callback_data=f"complete_{task_id}")],
                        [InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_{task_id}")],
                        get_back_button()
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    task_text = task[2]
                    priority = task[4]
                    due_date = task[3]
                    
                    priority_text = {3: "🔴 Высокий", 2: "🟡 Средний", 1: "🔵 Низкий"}[priority]
                    
                    if due_date:
                        due_date_str = datetime.fromisoformat(due_date).strftime("%d.%m.%Y %H:%M")
                        task_info = f"до {due_date_str}"
                    else:
                        task_info = "без срока"
                    
                    await query.edit_message_text(
                        f"📋 Задача: {task_text}\n"
                        f"🎯 Приоритет: {priority_text}\n"
                        f"📅 Срок: {task_info}\n\n"
                        f"Выберите действие:",
                        reply_markup=reply_markup
                    )
            return
        
        if query.data.startswith("confirm_delete_"):
            task_id = int(query.data.split("_")[2])
            user_id = query.from_user.id
            
            success = task_manager.delete_task(task_id, user_id)
            if success:
                await query.edit_message_text("✅ Задача успешно удалена!")
            else:
                await query.edit_message_text("❌ Ошибка при удалении задачи!")
    except Exception as e:
        logger.error(f"Ошибка подтверждения удаления: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка.")

# ИСПРАВЛЕННЫЙ обработчик кнопки Назад
async def handle_back_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки Назад в различных состояниях"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Общая обработка кнопки Назад
        current_step = context.user_data.get('current_step', '')
        
        if current_step == 'text':
            await query.edit_message_text(
                "Возврат в главное меню",
                reply_markup=get_main_menu()
            )
            context.user_data.clear()
            return ConversationHandler.END
            
        elif current_step == 'due_date':
            # Возврат к вводу текста
            context.user_data['current_step'] = 'text'
            keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "📝 Введите текст задачи:",
                reply_markup=reply_markup
            )
            return TEXT
            
        elif current_step == 'priority':
            # Возврат к выбору даты
            context.user_data['current_step'] = 'due_date'
            keyboard = [
                [InlineKeyboardButton("Сегодня", callback_data="today")],
                [InlineKeyboardButton("Завтра", callback_data="tomorrow")],
                [InlineKeyboardButton("Через 3 дня", callback_data="3days")],
                [InlineKeyboardButton("📅 Кастомный формат", callback_data="custom")],
                [InlineKeyboardButton("Без срока", callback_data="no_date")],
                get_back_button()
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "⏰ Укажите срок выполнения:",
                reply_markup=reply_markup
            )
            return DUE_DATE
        
        else:
            # Если неизвестное состояние, возвращаем в главное меню
            await query.edit_message_text(
                "Возврат в главное меню",
                reply_markup=get_main_menu()
            )
            context.user_data.clear()
            return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Ошибка обработки кнопки Назад: {e}")

# Добавляем обработчик текстовых команд
async def handle_text_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых команд типа 'назад'"""
    try:
        text = update.message.text.lower()
        
        if text in ['назад', 'back', 'отмена', 'cancel', 'меню']:
            await update.message.reply_text(
                "Возврат в главное меню",
                reply_markup=get_main_menu()
            )
            context.user_data.clear()
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Ошибка обработки текстовой команды: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущей операции"""
    try:
        await update.message.reply_text(
            "❌ Операция отменена", 
            reply_markup=get_main_menu()
        )
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка отмены операции: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Exception while handling an update: {context.error}")

def main():
    """Основная функция запуска бота"""
    try:
        BOT_TOKEN = os.getenv('BOT_TOKEN')
        if not BOT_TOKEN:
            raise ValueError("Не задан BOT_TOKEN в переменных окружения")
        
        print(f"✅ BOT_TOKEN: {'Найден' if BOT_TOKEN else 'Отсутствует'}")
        print(f"✅ NEWS_API_KEY: {'Найден' if NEWS_API_KEY else 'Отсутствует'}")
        print("🚀 Запуск бота...")
        
        application = Application.builder().token(BOT_TOKEN).build()
        
        # ИСПРАВЛЕННЫЙ ConversationHandler
        add_conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('add', add_task_start),
                MessageHandler(filters.Text("📝 Добавить задачу"), add_task_start)
            ],
            states={
                TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_text),
                    CallbackQueryHandler(handle_back_button, pattern="^back$")
                ],
                DUE_DATE: [
                    CallbackQueryHandler(add_task_due_date, pattern="^(today|tomorrow|3days|no_date|custom|back)$")
                ],
                CUSTOM_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_date),
                    CallbackQueryHandler(handle_back_button, pattern="^back$")
                ],
                PRIORITY: [
                    CallbackQueryHandler(add_task_priority, pattern="^(1|2|3|back)$")
                ],
            },
            fallbacks=[
                CommandHandler('cancel', cancel),
                MessageHandler(filters.Text("❌ Отмена"), cancel),
                CallbackQueryHandler(handle_back_button, pattern="^back$"),
                MessageHandler(filters.Text(["назад", "back", "отмена", "cancel"]), cancel)
            ]
        )
        
        # Добавление обработчиков
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('list', list_tasks))
        
        application.add_handler(add_conv_handler)
        
        # Обработчики меню
        application.add_handler(MessageHandler(
            filters.Text([
                "📝 Добавить задачу", "📋 Список задач", 
                "✅ Выполненные", "⚙️ Управление задачами",
                "📰 Бизнес-новости США", "ℹ️ Помощь"
            ]), 
            handle_menu_selection
        ))
        
        # Обработчики callback запросов для задач
        application.add_handler(CallbackQueryHandler(handle_task_management, pattern="^manage_"))
        application.add_handler(CallbackQueryHandler(handle_management_action, pattern="^(complete_|delete_|back_to_list|back)$"))
        application.add_handler(CallbackQueryHandler(handle_delete_confirmation, pattern="^(confirm_delete_|cancel_delete|back)$"))
        
        # Обработчики callback запросов для новостей
        application.add_handler(CallbackQueryHandler(handle_news_actions, pattern="^(refresh_news|close_news|back)$"))
        
        # Обработчик кнопки Назад
        application.add_handler(CallbackQueryHandler(handle_back_button, pattern="^back$"))
        
        # Обработчик текстовых команд (назад, отмена)
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            handle_text_commands
        ))
        
        # Добавление обработчика ошибок
        application.add_error_handler(error_handler)
        
        print("✅ Бот запущен успешно!")
        print("📰 Функция новостей: АКТИВНА (бизнес-новости США)")
        print("🔄 Функция возврата назад: АКТИВНА на всех этапах")
        
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")

if __name__ == '__main__':
    main()