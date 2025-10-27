cat > bot.py << 'EOF'
import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📰 Новости"), KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот. Нажмите кнопку '📰 Новости'",
        reply_markup=get_main_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Просто нажмите /start")

async def show_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📰 Вот ваши новости! Бот работает!")

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📰 Новости":
        await show_news(update, context)
    elif text == "ℹ️ Помощь":
        await help_command(update, context)

def main():
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден")
        return
    
    logger.info("✅ BOT_TOKEN найден")
    
    try:
        # Создаем приложение
        application = Application.builder().token(BOT_TOKEN).build()
        logger.info("✅ Application создано")
        
        # Добавляем обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
        
        logger.info("🚀 Запускаем бота...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        raise

if __name__ == '__main__':
    main()
EOF