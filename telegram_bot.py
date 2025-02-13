from datetime import datetime
import io
import json
import logging
import asyncio
from typing import Any
import asyncio

from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, CallbackContext
from telegram.helpers import escape_markdown
from telegram.error import RetryAfter

from database import Database
from config import settings
from helius_client import HeliusClient
from time_utils import format_time_ago

logger = logging.getLogger(__name__)

class PalmBot:
    def __init__(self, token: str, db: Database, helius_client: HeliusClient):
        self.application = Application.builder().token(token).build()
        self.db = db
        self.helius_client = helius_client
        self._register_handlers()
        self.updater = None
        logger.info("PalmBot initialized")

    @classmethod
    async def create(cls, token: str, db: Database, helius_client: HeliusClient):
        instance = cls(token, db, helius_client)
        await instance.setup()
        return instance

    async def setup(self):
        await self.application.initialize()
        self.updater = self.application.updater
        logger.info("PalmBot setup completed")

    async def start(self):
        if not self.application.running:
            await self.application.start()
            if self.updater:
                await self.updater.start_polling()
            logger.info("PalmBot started in polling mode")

    def _register_handlers(self):
        handlers = [
            CommandHandler("menu", self.menu_command),
            CommandHandler("addwallet", self.add_wallet_command),
            CommandHandler("removewallet", self.remove_wallet_command),
            CommandHandler("listwallets", self.list_wallets_command),
            CommandHandler("walletstatus", self.wallet_status_command),
            CommandHandler("portfolio", self.portfolio_command),
        ]
        for handler in handlers:
            self.application.add_handler(handler)
        logger.debug("Command handlers registered")

    async def _safe_reply(self, update: Update, message: str, attempt=1):
        """Send message with retry logic"""
        try:
            await update.message.reply_text(
                message,
                parse_mode='MarkdownV2',
                disable_web_page_preview=True
            )
        except RetryAfter as e:
            if attempt > 3:
                raise
            wait_time = e.retry_after + 2
            logger.warning(f"Rate limited. Waiting {wait_time}s (attempt {attempt}/3)")
            await asyncio.sleep(wait_time)
            return await self._safe_reply(update, message, attempt + 1)
        except Exception as e:
            logger.error(f"Message error: {str(e)}")
            await update.message.reply_text(self._escape(message))

    def _escape(self, text: str) -> str:
        return escape_markdown(str(text), version=2)

    async def menu_command(self, update: Update, context: CallbackContext):
        menu_text = (
            "🌴 *Private Palm Bot* 🌴\n\n"
            f"/addwallet <address\\> <alias\\> \\- *{self._escape('Add wallet')}*\n"
            f"/removewallet <alias\\|address\\> \\- *{self._escape('Remove wallet')}*\n"
            f"/listwallets \\- *{self._escape('Show monitored wallets')}*\n"
            f"/walletstatus <alias\\|address\\> \\- *{self._escape('Check status')}*\n"
            f"/portfolio <alias\\|address\\> \\- *{self._escape('Show portfolio')}*\n"
            f"/menu \\- *{self._escape('Show command menu')}*"
        )
        await self._safe_reply(update, menu_text)

    async def add_wallet_command(self, update: Update, context: CallbackContext):
        try:
            args = context.args
            if len(args) < 2:
                await self._safe_reply(update, "`Usage: /addwallet <address> <alias>`")
                return

            address, alias = args[0].strip(), args[1].strip().lower()
            await self.db.save_wallet(address, alias)
            response = (
                "✅ *Wallet added:*\n"
                f"Address: `{self._escape(address)}`\n"
                f"Alias: *{self._escape(alias)}*"
            )
            await self._safe_reply(update, response)
            logger.info(f"Added new wallet: {alias} ({address})")
        except Exception as e:
            logger.error(f"Error in add_wallet_command: {str(e)}")
            await self._safe_reply(update, "⚠️ Error adding wallet")

    async def remove_wallet_command(self, update: Update, context: CallbackContext):
        try:
            if not context.args:
                await self._safe_reply(update, "`Usage: /removewallet <alias|address>`")
                return

            identifier = context.args[0].strip()
            wallet = await self.db.get_wallet(identifier)

            if not wallet:
                await self._safe_reply(update, "ℹ️ Wallet not found")
                return

            await self.db.remove_wallet(wallet['address'])
            await self._safe_reply(update, f"✅ Removed wallet: *{self._escape(wallet['alias'])}*")
            logger.info(f"Removed wallet: {wallet['alias']} ({wallet['address']})")
        except Exception as e:
            logger.error(f"Error in remove_wallet_command: {str(e)}")
            await self._safe_reply(update, "⚠️ Error removing wallet")

    async def list_wallets_command(self, update: Update, context: CallbackContext):
        try:
            wallets = await self.db.load_all_wallets()
            if wallets:
                # Escape literal parentheses around the wallet address.
                wallet_lines = "\n".join(
                    f"• *{escape_markdown(w['alias'], version=2)}* \\(`{w['address']}`\\)" for w in wallets
                )
                response = f"📋 *Monitored Wallets:*\n{wallet_lines}"
            else:
                response = "No wallets being monitored"
            await self._safe_reply(update, response)
        except Exception as e:
            logger.error(f"Error in list_wallets_command: {str(e)}")
            await self._safe_reply(update, "⚠️ Error listing wallets")

    async def wallet_status_command(self, update: Update, context: CallbackContext):
        try:
            if not context.args:
                await self._safe_reply(update, "`Usage: /walletstatus <alias|address>`")
                return

            wallet = await self.db.get_wallet(context.args[0].strip())
            if not wallet:
                await self._safe_reply(update, "ℹ️ Wallet not found")
                return

            last_activity = format_time_ago(wallet.get('last_activity_at'))
            response = (
                f"📊 *Wallet Status: {self._escape(wallet['alias'])}*\n"
                f"Address: `{self._escape(wallet['address'])}`\n"
                f"Last Activity: `{self._escape(last_activity)}`\n"
                f"Transactions: `{self._escape(wallet.get('tx_count', 0))}`"
            )
            await self._safe_reply(update, response)
        except Exception as e:
            logger.error(f"Error in wallet_status_command: {str(e)}")
            await self._safe_reply(update, "⚠️ Error showing wallet status")

    async def portfolio_command(self, update: Update, context: CallbackContext):
        """Handle /portfolio command with original formatting"""
        try:
            if not context.args:
                await self._reply_md(update, "`Usage: /portfolio <alias\\|address>`")
                return

            identifier = " ".join(context.args).strip().lower()
            wallet = await self.db.get_wallet(identifier)  # Changed to await
            if not wallet:
                await self._reply_md(update, "ℹ️ Wallet not found")
                return

            # Cache validation logic - KEEP ORIGINAL STRUCTURE
            current_time = datetime.now().timestamp()
            cache_ttl = settings.CACHE_TTL
            cache_valid = (
                (current_time - wallet.get('last_asset_check', 0)) < cache_ttl and
                wallet.get('last_activity_at', 0) < wallet.get('last_asset_check', 0)
            )

            if not cache_valid:
                try:
                    # Changed to await both lines
                    sol_balance, tokens = await self.helius_client.get_portfolio(wallet['address'])
                    await self.db.update_portfolio(wallet['address'], sol_balance, tokens)
                    cache_status = " (live)"
                except Exception as e:
                    logger.error(f"API fetch failed: {str(e)}", exc_info=True)
                    cache_status = " (cached, update failed)"
            else:
                cache_status = " (cached)"

            # Retrieve latest data - KEEP ORIGINAL STRUCTURE
            wallet = await self.db.get_wallet(identifier)  # Changed to await
            last_updated = format_time_ago(wallet.get('last_asset_check'))

            # Process tokens - ORIGINAL CODE
            tokens = []
            if wallet.get('tokens'):
                try:
                    raw_tokens = json.loads(wallet['tokens'])
                    tokens = [t for t in raw_tokens if isinstance(t, dict)]
                    tokens.sort(
                        key=lambda x: x.get('amount', 0) / (10 ** x.get('decimals', 9)),
                        reverse=True
                    )
                except Exception as e:
                    logger.error(f"Token processing error: {str(e)}", exc_info=True)

            # ORIGINAL MESSAGE TEMPLATE - DO NOT MODIFY
            message_template = (
                "✨ *{alias} Portfolio{cache_status}* ✨\n"
                "_Last updated: {updated}_\n"
                "`―――――――――――――――――――――――`\n"
                "*🟣 SOL Balance:*\n"
                "`{sol_balance}`\n\n"
                "*🪙 Top Assets \\({total} total\\):*\n"
                "{assets}\n"
                "`―――――――――――――――――――――――`\n"
                "_Full portfolio attached_ \\📎"
            )

            # ORIGINAL FORMATTING - DO NOT MODIFY
            formatted_message = message_template.format(
                alias=escape_markdown(wallet['alias'], version=2),
                cache_status=escape_markdown(cache_status, version=2),
                updated=escape_markdown(last_updated, version=2),
                sol_balance=escape_markdown(f"{wallet.get('sol_balance', 0):12.4f} SOL", version=2),
                total=len(tokens),
                assets="\n".join([
                    f"{idx:>2}\\. *{escape_markdown(t.get('name', 'Unknown'), version=2)}* "
                    f"\\({escape_markdown(t.get('symbol', 'UNK'), version=2)}\\)\n"
                    f"   `{t.get('amount', 0)/10**t.get('decimals',9):15,.4f}`"
                    for idx, t in enumerate(tokens[:20], 1)
                ]) if tokens else "*🫙 No token holdings found*"
            )

            # ORIGINAL FILE ATTACHMENT LOGIC - DO NOT MODIFY
            bio = None
            if len(tokens) > 20 or len(formatted_message) > 3800:
                full_content = (
                    f"{' Portfolio Summary ':=^40}\n"
                    f"Wallet: {escape_markdown(wallet['alias'], version=2)}\n"
                    f"Updated: {escape_markdown(last_updated, version=2)}\n"
                    f"SOL Balance: {wallet.get('sol_balance', 0):.4f}\n\n"
                    f"{' Assets ':-^40}\n" +
                    "\n".join(
                        f"{idx:>3}. {escape_markdown(t.get('name', 'Unknown'), version=2)} "
                        f"({escape_markdown(t.get('symbol', 'UNK'), version=2)}): "
                        f"{t.get('amount', 0)/10**t.get('decimals',9):12,.4f}"
                        for idx, t in enumerate(tokens, 1)
                    )
                )
                bio = io.BytesIO(full_content.encode('utf-8'))
                bio.name = f"portfolio_{wallet['alias']}.txt"

            # ORIGINAL SENDING LOGIC - DO NOT MODIFY
            try:
                await self._reply_md(update, formatted_message)
                if bio:
                    await self._reply_document_md(
                        update,
                        document=InputFile(bio),
                        caption=f"Full portfolio for {escape_markdown(wallet['alias'], version=2)}"
                    )
            except Exception as e:
                logger.error(f"Message sending failed: {str(e)}", exc_info=True)
                # ORIGINAL FALLBACK
                fallback_text = (
                    f"{wallet['alias']} Portfolio Summary\n"
                    f"Updated: {last_updated}\n"
                    f"SOL Balance: {wallet.get('sol_balance', 0):.4f}\n\n" +
                    "\n".join([
                        f"{idx}. {t.get('name', 'Unknown')} ({t.get('symbol', 'UNK')}): "
                        f"{t.get('amount', 0)/10**t.get('decimals',9):.4f}"
                        for idx, t in enumerate(tokens[:20], 1)
                    ])
                )
                await update.message.reply_text(fallback_text[:4096])
                if bio:
                    await update.message.reply_document(InputFile(bio))

        except Exception as e:
            logger.error(f"Error in portfolio_command: {str(e)}", exc_info=True)
            await self._reply_md(update, "⚠️ Error showing portfolio")
            
    async def stop(self):
        try:
            if self.updater and self.updater.running:
                await self.updater.stop()
            if self.application.running:
                await self.application.stop()
                await self.application.shutdown()
            logger.info("PalmBot stopped successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}")

    async def _reply_md(self, update: Update, message: str, **kwargs: Any) -> None:
        """With original rate limiting handling"""
        try:
            await update.message.reply_text(
                message,
                parse_mode='MarkdownV2',
                disable_web_page_preview=True,
                **kwargs
            )
        except RetryAfter as e:
            logger.warning(f"Rate limited, retrying in {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            await self._reply_md(update, message, **kwargs)
        except Exception as e:
            logger.error(f"Markdown error: {str(e)}")
            await update.message.reply_text(escape_markdown(message, version=2), **kwargs)

    async def _reply_document_md(self, update: Update, document: InputFile, caption: str) -> None:
        try:
            await update.message.reply_document(
                document=document,
                caption=caption,
                parse_mode='MarkdownV2'
            )
        except Exception as e:
            logger.error(f"Document error: {str(e)}")
            await update.message.reply_document(document=document)