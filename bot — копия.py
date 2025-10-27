import os
import sqlite3
import logging
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
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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

class TaskManager:
    def __init__(self, db_path='tasks.db'):
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
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    reminder_time TEXT NOT NULL,
                    sent BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (task_id) REFERENCES tasks (id)
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
            
            # Создание напоминания за 1 минуту до дедлайна
            if due_date:
                try:
                    due_datetime = datetime.fromisoformat(due_date)
                    reminder_time = due_datetime - timedelta(minutes=1)
                    
                    if reminder_time > datetime.now():
                        cursor.execute('''
                            INSERT INTO reminders (task_id, user_id, reminder_time)
                            VALUES (?, ?, ?)
                        ''', (task_id, user_id, reminder_time.isoformat()))
                except ValueError as e:
                    logger.warning(f"Ошибка создания напоминания: {e}")
            
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
            
            cursor.execute('''
                DELETE FROM reminders WHERE task_id = ?
            ''', (task_id,))
            
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            
            if success:
                logger.info(f"Задача #{task_id} удалена")
            return success
        except Exception as e:
            logger.error(f"Ошибка удаления задачи #{task_id}: {e}")
            return False
    
    def get_pending_reminders(self):
        """Получение ожидающих напоминаний"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            now = datetime.now().isoformat()
            
            cursor.execute('''
                SELECT r.*, t.text 
                FROM reminders r
                JOIN tasks t ON r.task_id = t.id
                WHERE r.reminder_time <= ? AND r.sent = FALSE
            ''', (now,))
            
            reminders = cursor.fetchall()
            conn.close()
            return reminders
        except Exception as e:
            logger.error(f"Ошибка получения напоминаний: {e}")
            return []
    
    def mark_reminder_sent(self, reminder_id):
        """Отметка напоминания как отправленного"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE reminders SET sent = TRUE WHERE id = ?
            ''', (reminder_id,))
            
            conn.commit()
            conn.close()
            logger.info(f"Напоминание #{reminder_id} отправлено")
        except Exception as e:
            logger.error(f"Ошибка отметки напоминания #{reminder_id}: {e}")

# Глобальный экземпляр менеджера задач
task_manager = TaskManager()

def get_main_menu():
    """Главное меню команд"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("📝 Добавить задачу"), KeyboardButton("📋 Список задач")],
        [KeyboardButton("✅ Выполненные"), KeyboardButton("⚙️ Управление задачами")],
        [KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)

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
ℹ️ Помощь - показать справку
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

*Формат даты:*
Для кастомного ввода используйте формат:
`ГГГГ-ММ-ДД ЧЧ:ММ`
Пример: `2024-12-31 23:59`
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
        elif text == "ℹ️ Помощь":
            await help_command(update, context)
            
    except Exception as e:
        logger.error(f"Ошибка обработки меню: {e}")

async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса добавления задачи - Шаг 1"""
    try:
        # Очищаем предыдущие данные
        context.user_data.clear()
        await update.message.reply_text("📝 Введите текст задачи:")
        return TEXT
    except Exception as e:
        logger.error(f"Ошибка начала добавления задачи: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте снова.")
        return ConversationHandler.END

async def add_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение текста задачи - Шаг 2"""
    try:
        # Сохраняем текст задачи
        context.user_data['task_text'] = update.message.text
        
        # Создаем клавиатуру для выбора срока
        keyboard = [
            [InlineKeyboardButton("Сегодня", callback_data="today")],
            [InlineKeyboardButton("Завтра", callback_data="tomorrow")],
            [InlineKeyboardButton("Через 3 дня", callback_data="3days")],
            [InlineKeyboardButton("📅 Кастомный формат", callback_data="custom")],
            [InlineKeyboardButton("Без срока", callback_data="no_date")]
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
    """Обработка выбора срока выполнения - Шаг 3"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_choice = query.data
        
        if user_choice == "custom":
            await query.edit_message_text(
                "📅 Введите дату и время в формате:\n"
                "`ГГГГ-ММ-ДД ЧЧ:ММ`\n"
                "Пример: `2024-12-31 23:59`"
            )
            return CUSTOM_DATE
        
        # Обрабатываем выбор из кнопок
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
        
        # Переходим к выбору приоритета
        keyboard = [
            [InlineKeyboardButton("🔴 Высокий", callback_data="3")],
            [InlineKeyboardButton("🟡 Средний", callback_data="2")],
            [InlineKeyboardButton("🔵 Низкий", callback_data="1")]
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
        
        # Проверка формата даты
        try:
            due_date = datetime.strptime(custom_date, "%Y-%m-%d %H:%M")
            if due_date < datetime.now():
                await update.message.reply_text("❌ Дата должна быть в будущем! Попробуйте снова:")
                return CUSTOM_DATE
                
            context.user_data['due_date'] = due_date.isoformat()
            
            # Переходим к выбору приоритета
            keyboard = [
                [InlineKeyboardButton("🔴 Высокий", callback_data="3")],
                [InlineKeyboardButton("🟡 Средний", callback_data="2")],
                [InlineKeyboardButton("🔵 Низкий", callback_data="1")]
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
    """Обработка выбора приоритета и сохранение задачи - Шаг 4"""
    try:
        query = update.callback_query
        await query.answer()
        
        priority = int(query.data)
        user_id = query.from_user.id
        task_text = context.user_data['task_text']
        due_date = context.user_data.get('due_date')
        
        # Сохраняем задачу в базу
        task_id = task_manager.add_task(user_id, task_text, due_date, priority)
        
        if not task_id:
            await query.edit_message_text("❌ Ошибка при создании задачи!")
            return ConversationHandler.END
        
        # Форматируем ответ
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
"""
        await query.edit_message_text(confirmation_text)
        
        # Очищаем временные данные
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
        
        # Создаем клавиатуру с задачами
        keyboard = []
        for task in tasks:
            task_id, _, text, due_date, priority, status, created_at = task
            priority_emoji = {3: "🔴", 2: "🟡", 1: "🔵"}[priority]
            button_text = f"{priority_emoji} #{task_id}: {text[:20]}..."
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"manage_{task_id}")])
        
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
            await query.edit_message_text("❌ Управление задачами отменено")
            return
        
        task_id = int(query.data.split("_")[1])
        user_id = query.from_user.id
        
        task = task_manager.get_task(task_id, user_id)
        if not task:
            await query.edit_message_text("❌ Задача не найдена!")
            return
        
        context.user_data['manage_task_id'] = task_id
        
        # Меню действий с задачей
        keyboard = [
            [InlineKeyboardButton("✅ Выполнить", callback_data=f"complete_{task_id}")],
            [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{task_id}")],
            [InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_{task_id}")],
            [InlineKeyboardButton("↩️ Назад", callback_data="back_to_list")]
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
        
        action, task_id = query.data.split("_")
        task_id = int(task_id)
        user_id = query.from_user.id
        
        if action == "complete":
            success = task_manager.update_task(task_id, user_id, status='completed')
            if success:
                await query.edit_message_text("✅ Задача отмечена как выполненная! 🎉")
            else:
                await query.edit_message_text("❌ Ошибка при обновлении задачи!")
                
        elif action == "edit":
            context.user_data['edit_task_id'] = task_id
            await show_edit_options(query)
            return EDIT_CHOICE
            
        elif action == "delete":
            task = task_manager.get_task(task_id, user_id)
            if task:
                keyboard = [
                    [InlineKeyboardButton("✅ Да", callback_data=f"confirm_delete_{task_id}")],
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
    
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_manage")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "⚙️ Выберите задачу для управления:",
        reply_markup=reply_markup
    )

async def show_edit_options(query):
    """Показать опции редактирования"""
    keyboard = [
        [InlineKeyboardButton("📝 Текст", callback_data="edit_text")],
        [InlineKeyboardButton("⏰ Дата", callback_data="edit_date")],
        [InlineKeyboardButton("🎯 Приоритет", callback_data="edit_priority")],
        [InlineKeyboardButton("↩️ Назад", callback_data="back_to_manage")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "Что вы хотите изменить?",
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

async def edit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора что редактировать"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "back_to_manage":
            await show_task_management_from_query(query)
            return ConversationHandler.END
            
        choice = query.data
        context.user_data['edit_choice'] = choice
        
        if choice == "edit_text":
            await query.edit_message_text("📝 Введите новый текст задачи:")
            return EDIT_TEXT
        elif choice == "edit_date":
            keyboard = [
                [InlineKeyboardButton("Сегодня", callback_data="today")],
                [InlineKeyboardButton("Завтра", callback_data="tomorrow")],
                [InlineKeyboardButton("Через 3 дня", callback_data="3days")],
                [InlineKeyboardButton("📅 Кастомный формат", callback_data="custom")],
                [InlineKeyboardButton("Без срока", callback_data="no_date")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("⏰ Выберите новый срок:", reply_markup=reply_markup)
            return EDIT_DATE
        elif choice == "edit_priority":
            keyboard = [
                [InlineKeyboardButton("🔴 Высокий", callback_data="3")],
                [InlineKeyboardButton("🟡 Средний", callback_data="2")],
                [InlineKeyboardButton("🔵 Низкий", callback_data="1")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("🎯 Выберите новый приоритет:", reply_markup=reply_markup)
            return EDIT_PRIORITY
    except Exception as e:
        logger.error(f"Ошибка выбора редактирования: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка.")
        return ConversationHandler.END

async def edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование текста задачи"""
    try:
        new_text = update.message.text
        task_id = context.user_data['edit_task_id']
        user_id = update.message.from_user.id
        
        success = task_manager.update_task(task_id, user_id, text=new_text)
        
        if success:
            await update.message.reply_text("✅ Текст задачи успешно обновлен!")
        else:
            await update.message.reply_text("❌ Ошибка при обновлении задачи!")
        
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка редактирования текста: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")
        return ConversationHandler.END

async def edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование даты задачи"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "custom":
            await query.edit_message_text(
                "📅 Введите новую дату и время в формате:\n"
                "`ГГГГ-ММ-ДД ЧЧ:ММ`\n"
                "Пример: `2024-12-31 23:59`"
            )
            return EDIT_CUSTOM_DATE
            
        user_choice = query.data
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
        
        task_id = context.user_data['edit_task_id']
        user_id = query.from_user.id
        
        success = task_manager.update_task(
            task_id, user_id, 
            due_date=due_date.isoformat() if due_date else None
        )
        
        if success:
            await query.edit_message_text("✅ Дата задачи успешно обновлена!")
        else:
            await query.edit_message_text("❌ Ошибка при обновлении задачи!")
        
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка редактирования даты: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка.")
        return ConversationHandler.END

async def edit_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кастомного ввода даты при редактировании"""
    try:
        custom_date = update.message.text.strip()
        task_id = context.user_data['edit_task_id']
        user_id = update.message.from_user.id
        
        # Проверка формата даты
        try:
            due_date = datetime.strptime(custom_date, "%Y-%m-%d %H:%M")
            if due_date < datetime.now():
                await update.message.reply_text("❌ Дата должна быть в будущем! Попробуйте снова:")
                return EDIT_CUSTOM_DATE
                
            success = task_manager.update_task(
                task_id, user_id, 
                due_date=due_date.isoformat()
            )
            
            if success:
                await update.message.reply_text("✅ Дата задачи успешно обновлена!")
            else:
                await update.message.reply_text("❌ Ошибка при обновлении задачи!")
            
            context.user_data.clear()
            return ConversationHandler.END
            
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат даты!\n"
                "Используйте: `ГГГГ-ММ-ДД ЧЧ:ММ`\n"
                "Пример: `2024-12-31 23:59`\n"
                "Попробуйте снова:"
            )
            return EDIT_CUSTOM_DATE
            
    except Exception as e:
        logger.error(f"Ошибка обработки кастомной даты: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")
        return ConversationHandler.END

async def edit_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование приоритета задачи"""
    try:
        query = update.callback_query
        await query.answer()
        
        priority = int(query.data)
        task_id = context.user_data['edit_task_id']
        user_id = query.from_user.id
        
        success = task_manager.update_task(task_id, user_id, priority=priority)
        
        if success:
            await query.edit_message_text("✅ Приоритет задачи успешно обновлен!")
        else:
            await query.edit_message_text("❌ Ошибка при обновлении задачи!")
        
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка редактирования приоритета: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка.")
        return ConversationHandler.END

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

async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Отправка напоминаний за 1 минуту до дедлайна"""
    try:
        reminders = task_manager.get_pending_reminders()
        
        for reminder in reminders:
            reminder_id, task_id, user_id, reminder_time, sent, task_text = reminder
            
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"⏰ Напоминание: через минуту у вас запланировано '{task_text}'"
                )
                task_manager.mark_reminder_sent(reminder_id)
                logger.info(f"Напоминание отправлено пользователю {user_id} для задачи '{task_text}'")
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания пользователю {user_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка в функции отправки напоминаний: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Exception while handling an update: {context.error}")

def main():
    """Основная функция запуска бота"""
    try:
        BOT_TOKEN = os.getenv('BOT_TOKEN')
        if not BOT_TOKEN:
            raise ValueError("Не задан BOT_TOKEN в переменных окружения")
        
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Обработчик для добавления задач
        add_conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('add', add_task_start),
                MessageHandler(filters.Text("📝 Добавить задачу"), add_task_start)
            ],
            states={
                TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_text)
                ],
                DUE_DATE: [
                    CallbackQueryHandler(add_task_due_date, pattern="^(today|tomorrow|3days|no_date|custom)$")
                ],
                CUSTOM_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_date)
                ],
                PRIORITY: [
                    CallbackQueryHandler(add_task_priority, pattern="^(1|2|3)$")
                ],
            },
            fallbacks=[
                CommandHandler('cancel', cancel),
                MessageHandler(filters.Text("❌ Отмена"), cancel)
            ]
        )
        
        # Обработчик для редактирования задач
        edit_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(edit_choice, pattern="^edit_")],
            states={
                EDIT_CHOICE: [CallbackQueryHandler(edit_choice, pattern="^(edit_text|edit_date|edit_priority|back_to_manage)")],
                EDIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_text)],
                EDIT_DATE: [CallbackQueryHandler(edit_date, pattern="^(today|tomorrow|3days|no_date|custom)$")],
                EDIT_CUSTOM_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_custom_date)],
                EDIT_PRIORITY: [CallbackQueryHandler(edit_priority, pattern="^(1|2|3)$")],
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        # Добавление обработчиков
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('list', list_tasks))
        
        application.add_handler(add_conv_handler)
        application.add_handler(edit_conv_handler)
        
        # Обработчики меню
        application.add_handler(MessageHandler(
            filters.Text([
                "📝 Добавить задачу", "📋 Список задач", 
                "✅ Выполненные", "⚙️ Управление задачами", "ℹ️ Помощь"
            ]), 
            handle_menu_selection
        ))
        
        # Обработчики callback запросов
        application.add_handler(CallbackQueryHandler(handle_task_management, pattern="^manage_"))
        application.add_handler(CallbackQueryHandler(handle_management_action, pattern="^(complete_|edit_|delete_|back_)"))
        application.add_handler(CallbackQueryHandler(handle_delete_confirmation, pattern="^(confirm_delete_|cancel_delete)"))
        
        # Добавление обработчика ошибок
        application.add_error_handler(error_handler)
        
        # Настройка планировщика для напоминаний
        scheduler = AsyncIOScheduler()
        scheduler.add_job(send_reminders, 'interval', minutes=1, args=[application])
        scheduler.start()
        
        print("Бот запущен...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")

if __name__ == '__main__':
    main()