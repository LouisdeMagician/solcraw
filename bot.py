import asyncio
import logging
from contextlib import asynccontextmanager
from config import settings
from database import Database
from webhook_server import WebhookServer
from telegram_bot import PalmBot
from logger import configure_logging
from helius_client import HeliusClient
from resource_monitor import ResourceMonitor
from connection_pool import HTTPSessionManager

# Configure logging
logger = logging.getLogger(__name__)
configure_logging()
session_manager = HTTPSessionManager()

@asynccontextmanager
async def lifespan():
    """Manage application lifecycle with proper resource cleanup"""
    db = Database(settings.database_url)
    try:
        await db.connect()  # Explicit connection
        logger.info("Database connection established")
        async with HeliusClient(settings.helius_api_key, session_manager) as helius:
            yield db, helius  # Yield both db and helius
    finally:
        await db.close()
        logger.info("Database connection closed")

async def main():
    """Main application entry point with proper error handling"""
    # Initialize
    resource_monitor = ResourceMonitor(interval=300)  # Log every 5 minutes
    await resource_monitor.start()
    async with lifespan() as (db, helius):
        bot = None
        webhook_server = None
        
        try:
            # Initialize components
            logger.info("Initializing application components")
            bot = await PalmBot.create(settings.telegram_bot_token, db, helius)
            webhook_server = WebhookServer(bot.application, db)
            
            # Start components
            logger.info("Starting webhook server")
            await webhook_server.start()
            
            logger.info("Starting Telegram bot")
            await bot.start()
            
            # Keep application running
            logger.info("Application startup complete")
            while True:
                await asyncio.sleep(3600)  # Replace with actual work loop

        except asyncio.CancelledError:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error(f"Application error: {str(e)}", exc_info=True)
            raise
        finally:
            """Enhanced shutdown sequence"""
            logger.info("Starting application shutdown")
            
            # 1. Stop webhook server first
            if webhook_server:
                await webhook_server.stop()
            
            # 2. Stop Telegram bot
            if bot:
                await bot.stop()
            
            # 3. Close database
            if db:
                await db.close()
            
            # 4. Close all HTTP connections
            if hasattr(webhook_server, 'session_manager'):
                await webhook_server.session_manager.stop()
            
            # 5. Cancel remaining tasks
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # 6. Close event loop
            loop = asyncio.get_event_loop()
            await loop.shutdown_asyncgens()
            loop.close()
            
            logger.info("Application shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}", exc_info=True)
        raise