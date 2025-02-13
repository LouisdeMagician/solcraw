import os
import asyncio
import logging
import sqlite3
import json
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
from dotenv import load_dotenv
import aiohttp
from_stringfrom aiohttp_retry import RetryClient, ExponentialRetry
from solana.rpc.api import Client
from solana.exceptions import SolanaRpcException
from aiohttp import web
from aiohttp.web import AppKey

# Define a proper application key
TG_APP_KEY = AppKey("tg_app", Application)

# Load environment variables
load_dotenv()
API_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
CHAT_ID2 = os.getenv('CHAT_ID2')
SOLANA_CLUSTER_URL = "https://api.mainnet-beta.solana.com"
DAS_ENDPOINT = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
DB_NAME = 'wallets.db'

def migrate_database():
    """Initialize database with proper schema"""
    conn = sqlite3.connect(DB_NAME)
    conn.execute('''CREATE TABLE IF NOT EXISTS wallets
                 (address TEXT PRIMARY KEY,
                  alias TEXT UNIQUE NOT NULL,
                  last_checked INTEGER,
                  tx_count INTEGER DEFAULT 0,
                  sol_balance REAL DEFAULT 0,
                  last_asset_check INTEGER,
                  tokens TEXT)''')
    
    # Add missing columns if needed
    cursor = conn.execute("PRAGMA table_info(wallets)")
    columns = [row[1] for row in cursor.fetchall()]
    for column in [('sol_balance', 'REAL'), ('last_asset_check', 'INTEGER'), ('tokens', 'TEXT')]:
        if column[0] not in columns:
            conn.execute(f"ALTER TABLE wallets ADD COLUMN {column[0]} {column[1]}")
    
    conn.commit()
    conn.close()

migrate_database()

# Retry configuration
RETRY_OPTIONS = ExponentialRetry(attempts=3, start_timeout=1, factor=2)

# ======================
#  CORE FUNCTIONALITY
# ======================
def validate_solana_address(address: str) -> bool:
    """Validate Solana address using official library"""
    try:
        Pubkey.from_string(address)
        return True
    except ValueError:
        return False


async def handle_webhook(request):
    """Handle incoming webhook events"""
    try:
        tg_app = request.app[TG_APP_KEY]
        data = await request.json()
        
        # Handle both single transaction and batch formats
        transactions = data if isinstance(data, list) else [data]
        
        logger.info(f"Processing {len(transactions)} transactions")
        
        for transaction in transactions:
            await process_transaction(transaction, tg_app)
            
        return web.Response(status=200)
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}", exc_info=True)
        return web.Response(status=500)

async def process_webhook_event(data):
    """Process incoming webhook event"""
    event_type = data.get("type")
    if event_type == "accountUpdate":
        await handle_account_update(data)
    else:
        logger.warning(f"Unhandled event type: {event_type}")

async def handle_account_update(data):
    """Handle account update events"""
    wallet_address = data.get("account")
    transactions = data.get("transactions", [])
    
    wallet = get_wallet(wallet_address)
    if not wallet:
        logger.warning(f"Wallet not found: {wallet_address}")
        return
    
    for tx in transactions:
        await process_transaction(wallet, tx)
    
    logger.info(f"Processed {len(transactions)} transactions for {wallet['alias']}")


async def get_sol_balance(wallet_address: str) -> float:
    """Get native SOL balance using direct RPC"""
    try:
        pubkey = Pubkey.from_string(wallet_address)
        loop = asyncio.get_event_loop()
        client = Client(SOLANA_CLUSTER_URL)
        balance = await loop.run_in_executor(
            None, 
            lambda: client.get_balance(pubkey).value
        )
        return balance / 1e9
    except (ValueError, SolanaRpcException) as e:
        logger.error(f"Error getting SOL balance: {e}")
        return 0.0

async def get_all_assets(session, wallet_address: str):
    """Get all assets (fungible and NFTs) using DAS API"""
    assets = []
    page = 1
    
    while True:
        payload = {
            "jsonrpc": "2.0",
            "id": "wallet-scanner",
            "method": "getAssetsByOwner",
            "params": {
                "ownerAddress": wallet_address,
                "page": page,
                "limit": 100,
                "displayOptions": {
                    "showUnverifiedCollections": True,
                    "showCollectionMetadata": True,
                    "showFungible": True
                }
            }
        }
        
        try:
            async with session.post(DAS_ENDPOINT, json=payload) as response:
                response.raise_for_status()
                data = await response.json()
                
                if 'error' in data:
                    logger.error(f"DAS API Error: {data['error']}")
                    break
                    
                assets.extend(data['result']['items'])
                
                if len(data['result']['items']) < 100:
                    break
                    
                page += 1
                
        except Exception as e:
            logger.error(f"Error fetching assets: {e}")
            break
            
    return assets

def process_fungible_assets(assets):
    """Process fungible tokens with proper formatting"""
    fungible_tokens = []
    
    for asset in assets:
        if asset['interface'] not in ['FungibleToken', 'FungibleAsset']:
            continue
            
        try:
            token_info = asset.get('token_info', {})
            metadata = asset.get('content', {}).get('metadata', {})
            
            fungible_tokens.append({
                'mint': asset['id'],
                'symbol': metadata.get('symbol', asset['id'][:4]),
                'name': metadata.get('name', 'Unnamed Token'),
                'amount': token_info.get('balance', 0) / (10 ** token_info.get('decimals', 0)),
                'decimals': token_info.get('decimals', 0),
                'verified': asset.get('ownership', {}).get('verified', False)
            })
            
        except Exception as e:
            logger.error(f"Error processing asset {asset['id']}: {e}")
            
    return fungible_tokens

def format_holdings(sol_balance: float, tokens: list) -> str:
    """Format portfolio for human-readable display"""
    output = [f"SOL Balance: {sol_balance:.6f}", "Token Holdings:"]
    
    for token in tokens:
        display_name = f"{token['symbol']} ({token['name']})" if token['symbol'] != token['name'] else token['name']
        verification = "✓" if token['verified'] else "⚠"
        output.append(
            f"\n{verification} {display_name}\n"
            f"   Mint: {token['mint']}\n"
            f"   Amount: {token['amount']:.{token['decimals']}f}"
        )
        
    return "\n".join(output)

# ======================
#  DATABASE OPERATIONS
# ======================

def get_wallet(identifier: str) -> dict | None:
    """Get wallet by address or alias"""
    try:
        pubkey = Pubkey.from_string(identifier)
        address = str(pubkey)
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT address, alias, last_checked, tx_count, sol_balance, last_asset_check, tokens FROM wallets WHERE address=?",
                (address,)
            )
            result = cursor.fetchone()
    except ValueError:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT address, alias, last_checked, tx_count, sol_balance, last_asset_check, tokens FROM wallets WHERE alias=?",
                (identifier.lower(),)
            )
            result = cursor.fetchone()
    
    if result:
        return {
            "address": result[0],
            "alias": result[1],
            "last_checked": result[2],
            "tx_count": result[3],
            "sol_balance": result[4],
            "last_asset_check": result[5],
            "tokens": result[6]
        }
    return None

def save_wallet(address: str, alias: str):
    """Save wallet to database"""
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            "INSERT INTO wallets (address, alias) VALUES (?, ?)",
            (address, alias.lower())
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise ValueError("Alias already exists!") from e
    finally:
        conn.close()

def remove_wallet(address: str):
    """Remove wallet from database"""
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM wallets WHERE address=?", (address,))
    conn.commit()
    conn.close()

def load_all_wallets():
    """Load all wallets from database"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT address, alias, last_checked, tx_count, sol_balance, last_asset_check, tokens FROM wallets")
    wallets = [{
        "address": row[0],
        "alias": row[1],
        "last_checked": row[2],
        "tx_count": row[3],
        "sol_balance": row[4],
        "last_asset_check": row[5],
        "tokens": row[6]
    } for row in cursor.fetchall()]
    conn.close()
    return wallets

def update_portfolio_cache(wallet_address: str, sol_balance: float, tokens: list):
    """Update portfolio cache in database"""
    conn = sqlite3.connect(DB_NAME)
    current_time = int(datetime.now().timestamp())
    try:
        conn.execute(
            """UPDATE wallets 
            SET sol_balance = ?, last_asset_check = ?, tokens = ? 
            WHERE address = ?""",
            (sol_balance, current_time, json.dumps(tokens), wallet_address)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error updating portfolio cache: {e}")
    finally:
        conn.close()

# ======================
#  BOT COMMANDS
# ======================

async def menu_command(update: Update, context: CallbackContext):
    """Show command menu"""
    menu_text = """
    🍍 Private PalmBot Menu 🍍
    /addwallet <address> <alias> - Add wallet (alias required)
    /removewallet <alias|address> - Remove wallet
    /listwallets - Show monitored wallets
    /walletstatus <alias|address> - Check wallet status
    /portfolio <alias|address> - Show portfolio summary
    /help - Show commands
    """
    await update.message.reply_text(menu_text)

async def add_wallet_command(update: Update, context: CallbackContext):
    """Add new wallet with mandatory alias"""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /addwallet <address> <alias>")
        return
    
    raw_address = args[0].strip()
    alias = args[1].strip().lower()

    try:
        pubkey = Pubkey.from_string(raw_address)
        address = str(pubkey)
    except ValueError:
        await update.message.reply_text("❌ Invalid Solana address!")
        return

    try:
        save_wallet(address, alias)
        await update.message.reply_text(
            f"✅ Wallet added!\n"
            f"Address: {address}\n"
            f"Alias: {alias}"
        )
    except ValueError as e:
        await update.message.reply_text(f"❌ {str(e)}")


async def remove_wallet_command(update: Update, context: CallbackContext):
    """Remove wallet by alias or address"""
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /removewallet <alias|address>")
        return
    
    identifier = args[0].strip()
    wallet = get_wallet(identifier)
    
    if not wallet:
        await update.message.reply_text("ℹ️ Wallet not found")
        return
    
    remove_wallet(wallet['address'])
    await update.message.reply_text(f"✅ Removed wallet: {wallet['alias']}")

async def list_wallets_command(update: Update, context: CallbackContext):
    """List all monitored wallets"""
    wallets = load_all_wallets()
    if not wallets:
        await update.message.reply_text("No wallets being monitored")
        return
    
    response = "📋 Monitored Wallets:\n"
    for wallet in wallets:
        response += f"• {wallet['alias']} ({wallet['address']})\n"
    
    await update.message.reply_text(response)

async def wallet_status_command(update: Update, context: CallbackContext):
    """Show wallet status"""
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /walletstatus <alias|address>")
        return
    
    wallet = get_wallet(args[0].strip())
    if not wallet:
        await update.message.reply_text("ℹ️ Wallet not found")
        return
    
    last_checked = (
        datetime.fromtimestamp(wallet["last_checked"]).strftime('%Y-%m-%d %H:%M:%S')
        if wallet["last_checked"]
        else "Never"
    )
    
    status = (
        f"📊 Wallet Status: {wallet['alias']}\n"
        f"Address: {wallet['address']}\n"
        f"Last Checked: {last_checked}\n"
        f"Transactions Tracked: {wallet['tx_count']}"
    )
    await update.message.reply_text(status)

async def portfolio_command(update: Update, context: CallbackContext):
    """Show portfolio summary by making an API call on demand"""
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /portfolio <alias|address>")
        return
    
    identifier = args[0].strip()
    wallet = get_wallet(identifier)
    
    if not wallet:
        await update.message.reply_text("ℹ️ Wallet not found")
        return

    async with RetryClient(retry_options=RETRY_OPTIONS) as session:
        try:
            sol_balance = await get_sol_balance(wallet['address'])
            assets = await get_all_assets(session, wallet['address'])
            fungible_tokens = process_fungible_assets(assets)
            update_portfolio_cache(wallet['address'], sol_balance, fungible_tokens)
            
            # Format and send the portfolio
            formatted = format_holdings(sol_balance, fungible_tokens)
            await update.message.reply_text(formatted[:4096])  # Truncate for Telegram limits
        except Exception as e:
            logger.error(f"Error fetching portfolio for {wallet['alias']}: {e}")
            await update.message.reply_text("⚠️ Failed to refresh portfolio data")


# ======================
#  MONITORING SYSTEM
# ======================

async def start_webhook_server(tg_application: Application) -> web.Application:
    """Create and configure webhook server"""
    app = web.Application()
    app[TG_APP_KEY] = tg_application  # Store reference using proper key
    app.router.add_post("/webhook", handle_webhook)
    return app


async def process_transaction(tx_data, tg_application):
    """Process transactions with dual notification system"""
    try:
        # Common transaction details
        signature = tx_data.get('signature', 'Unknown')[:10] + "..."
        timestamp = datetime.fromtimestamp(tx_data.get('timestamp', 0))
        tx_type = tx_data.get('type', 'Unknown')
        
        # 1. General Notification (ALL transactions)
        for account in tx_data.get('accountData', []):
            wallet = get_wallet(account['account'])
            if wallet:
                # Basic alert for any activity
                await tg_application.bot.send_message(
                    chat_id=CHAT_ID,
                    text=(
                        f"🔔 Transaction in {wallet['alias']}\n"
                        f"Type: {tx_type}\n"
                        f"Time: {timestamp.strftime('%Y-%m-%d %H:%M')}\n"
                        f"Sig: {signature}"
                    )
                )

        # 2. Token Swap Notifications (Specific to CHAT_ID2)
        if tx_data.get('tokenTransfers'):
            for transfer in tx_data['tokenTransfers']:
                mint = transfer.get('mint')
                amount = transfer.get('tokenAmount', 0)
                decimals = transfer.get('rawTokenAmount', {}).get('decimals', 0)
                
                # Format amount with decimals
                formatted_amount = amount / (10 ** decimals) if decimals else amount
                
                # Find involved wallets
                from_wallet = get_wallet(transfer.get('fromUserAccount', ''))
                to_wallet = get_wallet(transfer.get('toUserAccount', ''))
                
                for wallet in [w for w in [from_wallet, to_wallet] if w]:
                    await tg_application.bot.send_message(
                        chat_id=CHAT_ID2,
                        text=(
                            f"🔄 Token Swap in {wallet['alias']}\n"
                            f"Time: {timestamp.strftime('%Y-%m-%d %H:%M')}\n"
                            f"Amount: {formatted_amount:.2f}\n"
                            f"Contract: {mint}"
                        )
                    )

    except Exception as e:
        logger.error(f"Transaction processing error: {e}", exc_info=True)
    

async def notify_new_token(alias: str, mint_address: str):
    """Notify about new token mint or purchase"""
    message = (
        f"🆕 New token in {alias}'s wallet:\n"
        f"Mint Address: {mint_address}"
    )
    await tg_application.bot.send_message(chat_id=CHAT_ID2, text=message)



# ======================
#  APPLICATION SETUP
# ======================

async def main():
    """Main async entry point"""
    # Initialize Telegram app
    application = Application.builder().token(API_TOKEN).build()
    
    # Register handlers
    handlers = [
        CommandHandler("menu", menu_command),
        CommandHandler("addwallet", add_wallet_command),
        CommandHandler("removewallet", remove_wallet_command),
        CommandHandler("listwallets", list_wallets_command),
        CommandHandler("walletstatus", wallet_status_command),
        CommandHandler("portfolio", portfolio_command),
    ]
    
    for handler in handlers:
        application.add_handler(handler)

# Create web server components
    web_app = await start_webhook_server(application)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)

    try:
        # Start web server first
        await site.start()
        logger.info("Webhook server running on port 8080")

        # Manually control Telegram lifecycle
        await application.initialize()
        await application.updater.start_polling()
        await application.start()

        # Keep alive until interrupted
        while True:
            await asyncio.sleep(3600)  # Adjust sleep as needed

    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutdown initiated")
    finally:
        # Ordered cleanup
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await site.stop()
        await runner.cleanup()

if __name__ == '__main__':
    # Configure event policy for clean shutdown
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped successfully")

