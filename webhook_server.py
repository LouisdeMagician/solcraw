import aiohttp
from aiohttp import web, ClientTimeout
from aiohttp_retry import RetryClient, ExponentialRetry
from database import Database
from config import settings
from datetime import datetime, timezone
from time_utils import format_time_ago
from telegram.helpers import escape_markdown
from telegram.error import RetryAfter
from parse_data import parse_swap, parse_transfer, get_token_info, parse_transactions, find_addr
from connection_pool import HTTPSessionManager
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
import asyncio

logger = logging.getLogger(__name__)


class WebhookServer:
    def __init__(self, tg_application, db: Database):
        self.session_manager = HTTPSessionManager(pool_size=15) 
        self.app = web.Application()
        self.tg_app = tg_application
        self.db = db
        self.runner = None
        self.site = None
        self._setup_routes()
        
        # Add cleanup handlers
        self.app.on_shutdown.append(self._on_shutdown)
        self.app.on_cleanup.append(self._on_cleanup)

    async def _on_shutdown(self, app):
        """Handle shutdown"""
        logger.debug("Webhook server shutting down")

    async def _on_cleanup(self, app):
        """Clean up resources"""
        logger.debug("Webhook server cleaning up")
        # Close any remaining connections
        await asyncio.sleep(0.1)  # Allow pending tasks to complete

    def _setup_routes(self):
        """Set up webhook routes"""
        self.app.router.add_post("/webhook", self.handle_webhook)

    async def handle_webhook(self, request):
        """Handle incoming webhook requests"""
        # Validate webhook secret
        if request.headers.get('Authorization') != settings.webhook_secret:
            logger.warning("Unauthorized webhook attempt")
            return web.Response(status=403)

        try:
            data = await request.json()
            transactions = data if isinstance(data, list) else [data]
            logger.info(f"Processing {len(transactions)} transactions")

            # Process transactions concurrently
            results = await asyncio.gather(
                *[self.process_transaction(tx) for tx in transactions],
                return_exceptions=True
            )

            # Log any errors
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Transaction failed: {str(result)}")

            return web.Response(status=200)
        except Exception as e:
            logger.error(f"Webhook error: {str(e)}", exc_info=True)
            return web.Response(status=500)

    async def process_transaction(self, tx_data):
        """Process a single transaction"""
        try:
            logger.info(f"Processing transaction: {tx_data.get('signature')}")
            tx_info = await parse_transactions(tx_data, self.db)
            wallet_address = tx_info['wallet']
            tx_type = tx_info['tx_type']

            # Fetch wallet info
            wallet = await self.db.get_wallet(wallet_address)
            if not wallet:
                logger.debug(f"Ignoring transaction for unknown wallet: {wallet_address}")
                return

            alias = wallet['alias']
            logger.info(f"Wallet Info: {alias}")

            # Update wallet activity
            await self.db.record_wallet_activity(wallet_address)

            # Prepare notification data
            timestamp = datetime.fromtimestamp(tx_data.get('timestamp'), tz=timezone.utc) if isinstance(tx_data.get('timestamp'), (int, float)) else tx_data.get('timestamp')
            signature = tx_data.get('signature', '')[:10] + '...'

            # Process specific transaction type
            if tx_type == 'TRANSFER':
                await self.process_transfer(tx_data)
            elif tx_type == 'SWAP':
                await self.process_swap(tx_data)
            else:
                await self.send_general_notification(tx_type, timestamp, signature, alias)
                logger.info(f"Unhandled transaction type: {tx_type}")

        except Exception as e:
            logger.error(f"[Tx {tx_data.get('signature')}] Processing error: {str(e)}", exc_info=True)

    async def process_transfer(self, tx_data):
        """Process transfer transactions"""
        try:
            transfer_data = await parse_transfer(tx_data)
            if not transfer_data:
                logger.warning("Failed to parse transfer data")
                return

            if transfer_data['is_native']:
                await self.notify_sol_transfer(transfer_data)
            elif transfer_data['is_single_token']:
                await self.notify_single_token_transfer(transfer_data)
            else:  # Batch distribution
                await self.notify_batch_transfer(transfer_data)

        except Exception as e:
            logger.error(f"[Tx {tx_data.get('signature')}] Transfer processing error: {str(e)}", exc_info=True)

    async def process_swap(self, tx_data):
        """Process swap transactions"""
        try:
            swap_data = parse_swap(tx_data) 
            if swap_data:
                await self.notify_swap(swap_data)
        except Exception as e:
            logger.error(f"[Tx {tx_data.get('signature')}] Swap processing error: {str(e)}", exc_info=True)

    async def send_general_notification(self, tx_type, timestamp, signature, alias):
        """Send basic transaction notification"""
        try:
            safe_alias = self._escape(alias)
            time_ago = self._escape(format_time_ago(timestamp))
            safe_sig = self._escape(signature)

            text = (
                f"🔔 New *{self._escape(tx_type)}* Transaction in _{safe_alias}_:\n"
                f"⏱ `{time_ago}`\n"
                f"📜 Sig: `{safe_sig}`"
            )

            await self.send_notification(text)
        except Exception as e:
            logger.error(f"Failed to send general notification: {str(e)}")

    async def _get_address_display(self, address: str) -> str:
        """Get alias or truncated address for display"""
        try:
            wallet = await self.db.get_wallet(address)
            if wallet:
                return self._escape(wallet['alias'])
            return f"`{self._escape(address[:6])}...{self._escape(address[-4:])}`"
        except Exception as e:
            logger.error(f"Address display error: {str(e)}")
            return f"`{self._escape(address[:10])}...`"

    async def notify_sol_transfer(self, transfer_data):
        """Notify SOL transfer with aliases"""
        try:
            from_display = await self._get_address_display(transfer_data['from'])
            to_display = await self._get_address_display(transfer_data['to'])
            
            text = (
                f"💸 *SOL Transfer*:\n"
                f"Amount: `{self._escape(transfer_data['amount'])} SOL`\n"
                f"From: {from_display}\n"
                f"To: {to_display}\n"
                f"⏱ {self._escape(format_time_ago(transfer_data['timestamp']))}\n"
                f"📜 `{self._escape(transfer_data['signature'])}`"
            )
            await self.send_notification(text)
        except Exception as e:
            logger.error(f"SOL transfer notification failed: {str(e)}")

    async def notify_single_token_transfer(self, transfer_data):
        """Notify token transfer with aliases"""
        try:
            token = transfer_data['token']
            from_display = await self._get_address_display(transfer_data['from'])
            to_display = await self._get_address_display(transfer_data['to'])
            formatted_amount = f"{transfer_data['amount']:.3f}".rstrip('0').rstrip('.')
            if '.' not in formatted_amount:
                formatted_amount += '.000'
            text = (
                f"💰 *{self._escape(token['name'])} \\({self._escape(token['symbol'])}\\) Transfer*:\n"
                f"🪙 Amount: `{self._escape(formatted_amount)} {self._escape(token['symbol'])}`\n"
                f"From: {from_display}\n"
                f"To: {to_display}\n"
                f"⏱ {self._escape(format_time_ago(transfer_data['timestamp']))}\n"
                f"📜 `{self._escape(transfer_data['signature'])}`"
            )
            await self.send_notification(text)
        except Exception as e:
            logger.error(f"Token transfer notification failed: {str(e)}")

    async def notify_swap(self, swap_data):
        """Swap notification with contract address"""
        try:
            wallet = await self.db.get_wallet(swap_data['wallet'])
            if not wallet:
                return

            sold = swap_data['sold_token']
            bought = swap_data['bought_token']
            ca = swap_data.get('contract_address', 'Unknown')

            # Format SOL transfers
            if not sold:
                sold = {'symbol': 'SOL', 'amount': abs(swap_data.get('nativeBalanceChange', 0))/1e9}
            if not bought:
                bought = {'symbol': 'SOL', 'amount': abs(swap_data.get('nativeBalanceChange', 0))/1e9}

            text = (
                f"🔄 *New Swap in {self._escape(wallet['alias'])}*\n"
                f"⬆️ Sold: `{self._escape(sold['amount'])} {self._escape(sold.get('symbol', 'UNK'))}`\n"
                f"⬇️ Bought: `{self._escape(bought['amount'])} {self._escape(bought.get('symbol', 'UNK'))}`\n"
                f"🏦 DEX: `{self._escape(swap_data['dex'])}`\n"
                f"⏱ {self._escape(format_time_ago(swap_data['timestamp']))}\n"
                f"🔗 [Transaction]({self._escape(swap_data['tx_url'])})\n"
                f"📜 *CA:* `{self._escape(ca)}`"
            )
            await self.send_notification(text)
            
        except Exception as e:
            logger.error(f"Swap notification failed: {str(e)}")
            
    async def send_notification(self, text):
        """Send notification with proper connection cleanup"""
        session = None
        try:
            session = aiohttp.ClientSession()
            await self._safe_send_message(session, text)
        except Exception as e:
            logger.error(f"Notification failed: {str(e)}")
        finally:
            if session:
                await session.close()

    async def _safe_send_message(self, session, text, attempt=1):
        """Send message with retry logic"""
        try:
            async with self.session_manager.session.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    'chat_id': settings.telegram_chat_id,
                    'text': text,
                    'parse_mode': 'MarkdownV2',
                    'disable_web_page_preview': True
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response.raise_for_status()
                await response.read()
        except RetryAfter as e:
            if attempt > 3:
                raise
            wait_time = e.retry_after + 2
            logger.warning(f"Rate limited. Waiting {wait_time}s (attempt {attempt}/3)")
            await asyncio.sleep(wait_time)
            return await self._safe_send_message(session, text, attempt + 1)
        except Exception as e:
            logger.error(f"Message error: {str(e)}")
            # Fallback to plain text
            clean_text = self._escape(text)
            await self._safe_send_message(session, clean_text)
            
    def _escape(self, text: str) -> str:
        """Escape markdown text"""
        return escape_markdown(str(text), version=2)

    async def start(self):
        """Start the webhook server"""
        await self.session_manager.start()  # Start pool before server
        self.client_session = aiohttp.ClientSession(
            timeout=ClientTimeout(total=10),
            raise_for_status=True
        )
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '0.0.0.0', 8080)
        await self.site.start()
        logger.info("Webhook server started on port 8080")

    async def stop(self):
        """Stop the webhook server gracefully"""
        await self.session_manager.stop()   # Close pool after server
        stop_tasks = []
        if self.site:
            stop_tasks.append(self.site.stop())
        if self.runner:
            stop_tasks.append(self.runner.cleanup())
        if self.client_session:
            stop_tasks.append(self.client_session.close())

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        logger.info("Webhook server stopped")