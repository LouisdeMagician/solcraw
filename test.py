from solders.pubkey import Pubkey
import asyncio
from solana.rpc.async_api import AsyncClient


async def get_token_info(token_mint_str: str, rpc_url: str = "https://api.mainnet-beta.solana.com") -> tuple[str, str]:
    """Fetch token metadata asynchronously."""
    client = AsyncClient(rpc_url)  # Use an async Solana client
    token_mint = Pubkey.from_string(token_mint_str)
    metadata_program_id = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
    
    metadata_pda = Pubkey.find_program_address(
        [b"metadata", bytes(metadata_program_id), bytes(token_mint)],
        metadata_program_id
    )[0]

    account_info = await client.get_account_info(metadata_pda)
    if account_info.value is None:
        raise Exception("No metadata found for token mint.")

    data = bytes(account_info.value.data)
    offset = 68
    name = data[offset:offset+32].rstrip(b'\x00').decode('utf-8')
    offset += 32
    symbol_length = int.from_bytes(data[offset:offset+4], byteorder='little')
    offset += 4
    symbol = data[offset:offset+10][:symbol_length].decode('utf-8')

    return name.replace('\x00', '').strip(), symbol.replace('\x00', '').strip()

'''
async def find_addr(desc: list[str], db: Database) -> Optional[str]:
    """Find wallet address in description asynchronously."""
    wallet_addresses = await db.get_all_wallet_addresses()  # Assume async DB method
    normalized_wallet_addresses = {addr.lower().strip('.,!?') for addr in wallet_addresses}
    
    for addr in desc:
        normalized_addr = addr.lower().strip('.,!?')
        if normalized_addr in normalized_wallet_addresses:
            return addr.strip('.,!?')
    return None
'''

async def main():
    mint = "FGeL6znivc1HHcVk9qthyVwuYxLv2EEQJwMoh5Cmpump"
    token_name, token_symbol = await get_token_info(mint)
    print(f"Token Name: {token_name}")
    print(f"Token Symbol: {token_symbol}")


# Example usage:
if __name__ == "__main__":
    asyncio.run(main())

'''


📢



🕚
🕦
🧮
💰
🪙
💴
💵
💶
💷
💸
💳
🧾
💹

if wallet := self.db.get_wallet(account.get('account', '')):
                self.db.record_wallet_activity(wallet['address'])

                
 # Build message with MarkdownV2 formatting
            text = (
                f"🔄 *Swap Executed in {escape_markdown(wallet['alias'], version=2)}*\n"
                f"⏱ `{escape_markdown(time_ago, version=2)}`\n\n"
                f"⬆️ *Sold:* `{swap_data['sold_amount']:.2f}` {escape_markdown(sold_symbol, version=2)}\n"
                f"⬇️ *Bought:* `{swap_data['bought_amount']:.2f}` {escape_markdown(bought_symbol, version=2)}\n"
                f"🏦 *DEX:* `{escape_markdown(swap_data['dex'], version=2)}`\n"
                f"🔗 [View on Explorer]({swap_data['tx_url']})"
            )

2025-02-08 21:19:18,150 - parse_data - INFO - Description words: ['DxPonqpBCiUWsUojki14ddwMKXtX24t9V145pPGZi8kJ', 'transferred', '11382', 'FXyR6qgdJjQ5grt4Mu1sXqZZwqQ9MFjbCZ8cLVQcpump', 'to', '8deJ9xeUvXSJwicYptA9mHsU2rN2pDx37KWzkDkEXhU6.']
2025-02-08 21:19:18,150 - parse_data - INFO - Checking word: dxponqpbciuwsuojki14ddwmkxtx24t9v145ppgzi8kj
2025-02-08 21:19:18,151 - parse_data - INFO - Checking word: transferred
2025-02-08 21:19:18,151 - parse_data - INFO - Checking word: 11382
2025-02-08 21:19:18,151 - parse_data - INFO - Checking word: fxyr6qgdjjq5grt4mu1sxqzzwqq9mfjbcz8clvqcpump
2025-02-08 21:19:18,151 - parse_data - INFO - Checking word: to
2025-02-08 21:19:18,152 - parse_data - INFO - Checking word: 8dej9xeuvxsjwicypta9mhsu2rn2pdx37kwzkdkexhu6

'''


next up, telegram_bot.py module. any necessary adjustments in accordance to the changes we've made so far?;

from datetime import datetime
import io
import json
import logging
import asyncio
from typing import Any

from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, CallbackContext
from telegram.helpers import escape_markdown  # built-in MarkdownV2 escape

from database import Database
from config import settings
from helius_client import HeliusClient
from time_utils import format_time_ago

logger = logging.getLogger(__name__)

class PalmBot:
    def __init__(self, token: str, db: Database, helius_client: HeliusClient):
        """Initialize the Telegram bot"""
        self.application = Application.builder().token(token).build()
        self.db = db
        self.helius_client = helius_client
        self._register_handlers()
        self.updater = None  # Will hold the Updater instance if using polling
        logger.info("PalmBot initialized")

    @classmethod
    async def create(cls, token: str, db: Database, helius_client: HeliusClient):
        """Factory method for proper async initialization"""
        instance = cls(token, db, helius_client)
        await instance.setup()
        return instance

    async def setup(self):
        """Setup the bot (non-blocking)"""
        await self.application.initialize()
        # If using webhooks, set them up here instead of polling
        self.updater = self.application.updater
        logger.info("PalmBot setup completed")

    async def start(self):
        """Start the bot in polling mode"""
        if not self.application.running:
            await self.application.start()
            if self.updater:
                await self.updater.start_polling()
            logger.info("PalmBot started in polling mode")

    def _register_handlers(self):
        """Register all command handlers"""
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

    # ────────────── Helper Methods for Consistent Markdown Output ──────────────

    async def _reply_md(self, update: Update, message: str, **kwargs: Any) -> None:
        """
        Send a message with MarkdownV2 styling.
        This method centralizes the parse_mode and disable_web_page_preview settings.
        """
        try:
            await update.message.reply_text(
                message,
                parse_mode='MarkdownV2',
                disable_web_page_preview=True,
                **kwargs
            )
            logger.debug("Markdown message sent successfully")
        except Exception as e:
            logger.error(f"Error sending Markdown message: {str(e)}", exc_info=True)
            # Fallback to sending without Markdown formatting
            await update.message.reply_text(message, **kwargs)

    async def _reply_document_md(self, update: Update, document: InputFile, caption: str) -> None:
        """
        Send a document with MarkdownV2 styling in the caption.
        """
        try:
            await update.message.reply_document(
                document=document,
                caption=caption,
                parse_mode='MarkdownV2'
            )
            logger.debug("Markdown document sent successfully")
        except Exception as e:
            logger.error(f"Error sending Markdown document: {str(e)}", exc_info=True)
            await update.message.reply_document(document=document)

    # ────────────── Command Handlers Using the New Helper Methods ──────────────

    async def menu_command(self, update: Update, context: CallbackContext):
        """Show command menu using the design style."""
        # The header now uses 🌴 on each side.
        # Command names and parameters are in plain text. Reserved characters such as '>' are escaped.
        # Descriptions are shown in bold (using *bold text* in MarkdownV2).
        menu_text = (
            "🌴 *Private Palm Bot* 🌴\n\n"
            "/addwallet <address\\> <alias\\> \\- *Add wallet*\n"
            "/removewallet <alias\\|address\\> \\- *Remove wallet*\n"
            "/listwallets \\- *Show monitored wallets*\n"
            "/walletstatus <alias\\|address\\> \\- *Check status*\n"
            "/portfolio <alias\\|address\\> \\- *Show portfolio*\n"
            "/menu \\- *Show command menu*"
        )
        await self._reply_md(update, menu_text)

    async def add_wallet_command(self, update: Update, context: CallbackContext):
        """Handle /addwallet command using consistent formatting."""
        try:
            args = context.args
            if len(args) < 2:
                await self._reply_md(update, "`Usage: /addwallet <address> <alias>`")
                return

            address, alias = args[0].strip(), args[1].strip().lower()
            self.db.save_wallet(address, alias)
            response = (
                "✅ *Wallet added:*\n"
                f"Address: `{address}`\n"
                f"Alias: *{escape_markdown(alias, version=2)}*"
            )
            await self._reply_md(update, response)
            logger.info(f"Added new wallet: {alias} ({address})")
        except Exception as e:
            logger.error(f"Error in add_wallet_command: {str(e)}", exc_info=True)
            await self._reply_md(update, "⚠️ Error adding wallet")

    async def remove_wallet_command(self, update: Update, context: CallbackContext):
        """Handle /removewallet command using consistent formatting."""
        try:
            if not context.args:
                await self._reply_md(update, "`Usage: /removewallet <alias\\|address>`")
                return

            identifier = context.args[0].strip()
            wallet = self.db.get_wallet(identifier)

            if not wallet:
                await self._reply_md(update, "ℹ️ Wallet not found")
                return

            self.db.remove_wallet(wallet['address'])
            await self._reply_md(update, f"✅ Removed wallet: *{escape_markdown(wallet['alias'], version=2)}*")
            logger.info(f"Removed wallet: {wallet['alias']} ({wallet['address']})")
        except Exception as e:
            logger.error(f"Error in remove_wallet_command: {str(e)}", exc_info=True)
            await self._reply_md(update, "⚠️ Error removing wallet")

    async def list_wallets_command(self, update: Update, context: CallbackContext):
        """Handle /listwallets command with consistent design."""
        try:
            wallets = self.db.load_all_wallets()
            if wallets:
                # Escape literal parentheses around the wallet address.
                wallet_lines = "\n".join(
                    f"• *{escape_markdown(w['alias'], version=2)}* \\(`{w['address']}`\\)" for w in wallets
                )
                response = f"📋 *Monitored Wallets:*\n{wallet_lines}"
            else:
                response = "No wallets being monitored"
            await self._reply_md(update, response)
            logger.debug("Listed all wallets")
        except Exception as e:
            logger.error(f"Error in list_wallets_command: {str(e)}", exc_info=True)
            await self._reply_md(update, "⚠️ Error listing wallets")

    async def wallet_status_command(self, update: Update, context: CallbackContext):
        """Handle /walletstatus command with activity data"""
        try:
            if not context.args:
                await self._reply_md(update, "`Usage: /walletstatus <alias\\|address>`")
                return

            wallet = self.db.get_wallet(context.args[0].strip())
            if not wallet:
                await self._reply_md(update, "ℹ️ Wallet not found")
                return

            # Format timestamps
            last_activity = format_time_ago(wallet.get('last_activity_at'))
            last_asset_check = format_time_ago(wallet.get('last_asset_check'))

            response = (
                f"📊 *Wallet Status: {escape_markdown(wallet['alias'], version=2)}*\n"
                f"Address: `{wallet['address']}`\n"
                f"Last Activity: `{last_activity}`\n"
                f"Last Port Refresh: `{format_time_ago(wallet.get('last_asset_check'))}`\n"
                f"Transactions: `{wallet.get('tx_count', 0)}`"
            )

            await self._reply_md(update, response)
            logger.debug(f"Showed status for wallet: {wallet['alias']}")
        except Exception as e:
            logger.error(f"Error in wallet_status_command: {str(e)}", exc_info=True)
            await self._reply_md(update, "⚠️ Error showing wallet status")

    async def portfolio_command(self, update: Update, context: CallbackContext):
        """Handle /portfolio command with consistent design and detailed logging."""
        try:
            if not context.args:
                await self._reply_md(update, "`Usage: /portfolio <alias\\|address>`")
                return

            identifier = " ".join(context.args).strip().lower()
            wallet = self.db.get_wallet(identifier)
            if not wallet:
                await self._reply_md(update, "ℹ️ Wallet not found")
                return

            logger.debug(f"Portfolio command received for wallet: {identifier}")

            # Cache validation logic
            current_time = datetime.now().timestamp()
            cache_ttl = settings.CACHE_TTL
            cache_valid = (
                (current_time - wallet.get('last_asset_check', 0)) < cache_ttl and
                wallet.get('last_activity_at', 0) < wallet.get('last_asset_check', 0)
            )

            if not cache_valid:
                try:
                    sol_balance, tokens = await self.helius_client.get_portfolio(wallet['address'])
                    self.db.update_portfolio(wallet['address'], sol_balance, tokens)
                    cache_status = " (live)"
                    logger.debug("Fetched live portfolio data from Helius API")
                except Exception as e:
                    logger.error(f"API fetch failed: {str(e)}", exc_info=True)
                    cache_status = " (cached, update failed)"
            else:
                cache_status = " (cached)"
                logger.debug("Using cached portfolio data")

            # Retrieve latest data
            wallet = self.db.get_wallet(identifier)
            last_updated = format_time_ago(wallet.get('last_asset_check'))

            # Process tokens
            tokens = []
            if wallet.get('tokens'):
                try:
                    raw_tokens = json.loads(wallet['tokens'])
                    tokens = [t for t in raw_tokens if isinstance(t, dict)]
                    tokens.sort(
                        key=lambda x: x.get('amount', 0) / (10 ** x.get('decimals', 9)),
                        reverse=True
                    )
                    logger.debug(f"Processed {len(tokens)} tokens from portfolio")
                except Exception as e:
                    logger.error(f"Token processing error: {str(e)}", exc_info=True)

            # Escape dynamic content
            safe_alias = escape_markdown(wallet['alias'], version=2)
            safe_updated = escape_markdown(last_updated, version=2)
            safe_sol_balance = escape_markdown(f"{wallet.get('sol_balance', 0):12.4f} SOL", version=2)
            safe_cache_status = escape_markdown(cache_status, version=2)

            # Build token lines (we escape the period after the index)
            token_lines = []
            for idx, t in enumerate(tokens[:20], 1):
                try:
                    name = escape_markdown(t.get('name', 'Unknown'), version=2)
                    symbol = escape_markdown(t.get('symbol', 'UNK'), version=2)
                    amount = t.get('amount', 0) / (10 ** t.get('decimals', 9))
                    formatted_amount = f"{amount:15,.4f}"
                    line = (
                        f"{idx:>2}\\. *{name}* \\({symbol}\\)\n"
                        f"   `{formatted_amount}`"
                    )
                    token_lines.append(line)
                except Exception as e:
                    logger.error(f"Token format error: {str(e)}", exc_info=True)
                    continue

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

            formatted_message = message_template.format(
                alias=safe_alias,
                cache_status=safe_cache_status,
                updated=safe_updated,
                sol_balance=safe_sol_balance,
                total=len(tokens),
                assets="\n".join(token_lines) if token_lines else "*🫙 No token holdings found*"
            )

            logger.debug("Final formatted portfolio message prepared:")
            logger.debug(formatted_message)

            # Optionally generate a file attachment if needed
            bio = None
            if len(tokens) > 20 or len(formatted_message) > 3800:
                full_content = (
                    f"{' Portfolio Summary ':=^40}\n"
                    f"Wallet: {safe_alias}\n"
                    f"Updated: {safe_updated}\n"
                    f"SOL Balance: {safe_sol_balance}\n\n"
                    f"{' Assets ':-^40}\n" +
                    "\n".join(
                        f"{idx:>3}. {escape_markdown(t.get('name', 'Unknown'), version=2)} "
                        f"({escape_markdown(t.get('symbol', 'UNK'), version=2)}): "
                        f"{t.get('amount', 0) / (10 ** t.get('decimals', 9)):12,.4f}"
                        for idx, t in enumerate(tokens, 1)
                    )
                )
                bio = io.BytesIO(full_content.encode('utf-8'))
                bio.name = f"portfolio_{wallet['alias']}.txt"
                logger.debug("Generated file attachment for full portfolio summary")

            # Send the portfolio message (and attachment if available)
            try:
                logger.debug("Attempting to send MarkdownV2 formatted portfolio message")
                await self._reply_md(update, formatted_message)
                if bio:
                    await self._reply_document_md(
                        update,
                        document=InputFile(bio),
                        caption=f"Full portfolio for {safe_alias}"
                    )
            except Exception as e:
                logger.error(f"Message sending failed: {str(e)}", exc_info=True)
                fallback_text = (
                    f"{wallet['alias']} Portfolio Summary\n"
                    f"Updated: {last_updated}\n"
                    f"SOL Balance: {wallet.get('sol_balance', 0):.4f}\n\n" +
                    "\n".join([
                        f"{idx}. {t.get('name', 'Unknown')} ({t.get('symbol', 'UNK')}): "
                        f"{t.get('amount', 0) / (10 ** t.get('decimals', 9)):.4f}"
                        for idx, t in enumerate(tokens[:20], 1)
                    ])
                )
                logger.debug("Sending fallback plain text portfolio summary")
                await update.message.reply_text(fallback_text[:4096])
                if bio:
                    await update.message.reply_document(InputFile(bio))
        except Exception as e:
            logger.error(f"Error in portfolio_command: {str(e)}", exc_info=True)
            await self._reply_md(update, "⚠️ Error showing portfolio")

    async def stop(self):
        """Gracefully stop the bot"""
        if self.updater and self.updater.running:
            await self.updater.stop()
        if self.application.running:
            await self.application.stop()
            await self.application.shutdown()
        logger.info("PalmBot stopped successfully")