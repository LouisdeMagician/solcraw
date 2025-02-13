from decimal import Decimal
from typing import Optional, Dict, List
from time_utils import format_time_ago
from datetime import datetime, timezone
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from database import Database
import logging
import json
import re

logger = logging.getLogger(__name__)


async def parse_transactions(tx_data, db) -> Dict:
    """
    Parse general transaction data to identify the wallet address that triggered the event 
    and the transaction type.

    Args:
        tx_data (dict): The transaction data received from the webhook.
        db (Database): An instance of the Database class.

    Returns:
        Dict: A dictionary containing:
            - 'wallet': The wallet address that triggered the transaction.
            - 'tx_type': The type of transaction (TRANSFER, SWAP, etc.).
    """
    logger.info("PARSING TRANSACTION")
    wallet = tx_data.get('feePayer', 'Unknown')

    # Determine transaction type
    tx_type = tx_data.get('type', 'Unknown')
    if tx_type == "TRANSFER":
        desc = tx_data.get('description', '').split()  
        logger.info(f"Description words: {desc}")
        wallet = await find_addr(desc, db)
        return {
            'wallet': wallet,
            'tx_type': tx_type
        }

    return {
        'wallet': wallet,
        'tx_type': tx_type
    }

async def parse_transfer(tx_data: dict) -> dict:
    """Parse transfer data with async token info lookup"""
    transfers = tx_data.get('tokenTransfers', [])
    account_data = tx_data.get('accountData', [])

    if not transfers and any(account['nativeBalanceChange'] != 0 for account in account_data):
        return {
            'is_native': True,
            'is_single_token': False,
            'amount': sum(abs(account['nativeBalanceChange']) for account in account_data if account['nativeBalanceChange'] != 0),
            'from': next((acc['account'] for acc in account_data if acc['nativeBalanceChange'] < 0), 'Unknown'),
            'to': next((acc['account'] for acc in account_data if acc['nativeBalanceChange'] > 0), 'Unknown'),
            'timestamp': tx_data.get('timestamp'),
            'signature': tx_data.get('signature', '')[:10] + '...'
        }

    if len(transfers) == 1:
        transfer = transfers[0]
        amount = Decimal(transfer.get('tokenAmount', 0))
        mint = transfer.get('mint')
        token_name, symbol = await get_token_info(mint)  # Proper async call
        
        return {
            'is_native': False,
            'is_single_token': True,
            'amount': amount,
            'token': {'name': token_name, 'symbol': symbol},
            'from': transfer.get('fromUserAccount'),
            'to': transfer.get('toUserAccount'),
            'timestamp': tx_data.get('timestamp'),
            'signature': tx_data.get('signature', '')[:10] + '...'
        }

    # Batch transfers need async processing
    processed_transfers = []
    for transfer in transfers:
        token_name, symbol = await get_token_info(transfer.get('mint'))
        processed_transfers.append({
            'amount': Decimal(transfer.get('tokenAmount', 0)),
            'token': {'name': token_name, 'symbol': symbol},
            'from': transfer.get('fromUserAccount'),
            'to': transfer.get('toUserAccount')
        })

    return {
        'is_native': False,
        'is_single_token': False,
        'transfers': processed_transfers,
        'timestamp': tx_data.get('timestamp'),
        'signature': tx_data.get('signature', '')[:10] + '...'
    }


def parse_swap(tx_data: dict) -> Optional[dict]:
    """Parse swap transactions and identify contract address"""
    try:
        if not isinstance(tx_data, dict) or tx_data.get('type') != 'SWAP':
            return None

        fee_payer = tx_data.get('feePayer')
        token_transfers = tx_data.get('tokenTransfers', [])
        native_transfers = tx_data.get('nativeTransfers', [])
        contract_address = None

        # Identify SOL transfers
        sol_sent = any(t['fromUserAccount'] == fee_payer for t in native_transfers)
        sol_received = any(t['toUserAccount'] == fee_payer for t in native_transfers)

        # Get token mints involved
        token_mints = [t['mint'] for t in token_transfers if t.get('mint')]

        if sol_sent and token_mints:
            # SOL -> Token swap
            contract_address = token_mints[0]
        elif sol_received and token_mints:
            # Token -> SOL swap
            contract_address = token_mints[0]
        elif len(token_mints) >= 2:
            # Token -> Token swap
            contract_address = token_mints[1]  # Assuming second is bought token

        # Original swap parsing logic
        sold_token = None
        bought_token = None
        
        if token_transfers:
            # First transfer is typically the sold token
            if token_transfers[0].get('tokenAmount', 0) < 0:
                sold_transfer = token_transfers[0]
                sold_token = {
                    'mint': sold_transfer['mint'],
                    'symbol': get_token_info(sold_transfer['mint'], 'symbol'),
                    'name': get_token_info(sold_transfer['mint'], 'name'),
                    'amount': abs(sold_transfer['tokenAmount']),
                    'decimals': sold_transfer['rawTokenAmount']['decimals']
                }

            # Second transfer is typically the bought token
            if len(token_transfers) > 1 and token_transfers[1].get('tokenAmount', 0) > 0:
                bought_transfer = token_transfers[1]
                bought_token = {
                    'mint': bought_transfer['mint'],
                    'symbol': get_token_info(bought_transfer['mint'], 'symbol'),
                    'name': get_token_info(bought_transfer['mint'], 'name'),
                    'amount': bought_transfer['tokenAmount'],
                    'decimals': bought_transfer['rawTokenAmount']['decimals']
                }

        return {
            'wallet': fee_payer,
            'timestamp': tx_data.get('timestamp'),
            'sold_token': sold_token,
            'bought_token': bought_token,
            'contract_address': contract_address,
            'dex': tx_data.get('source', 'Unknown DEX'),
            'tx_url': f"https://solscan.io/tx/{tx_data.get('signature')}"
        }

    except Exception as e:
        logger.error(f"Swap parsing error: {str(e)}")
        return None
                
async def get_token_info(token_mint_str: str, rpc_url: str = "https://api.mainnet-beta.solana.com") -> tuple[str, str]:
    """Fetch token metadata asynchronously with proper await syntax."""
    client = AsyncClient(rpc_url)  # Use async client
    token_mint = Pubkey.from_string(token_mint_str)
    metadata_program_id = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
    
    # Get metadata PDA
    metadata_pda = Pubkey.find_program_address(
        [b"metadata", bytes(metadata_program_id), bytes(token_mint)],
        metadata_program_id
    )[0]

    # Proper async call
    account_info = await client.get_account_info(metadata_pda)
    
    if account_info.value is None:
        return "Unknown Token", "UNK"

    data = bytes(account_info.value.data)
    offset = 68
    
    # Parse name and symbol
    name = data[offset:offset+32].rstrip(b'\x00').decode('utf-8', 'ignore')
    offset += 32
    
    symbol_length = int.from_bytes(data[offset:offset+4], byteorder='little')
    offset += 4
    symbol = data[offset:offset+10][:symbol_length].decode('utf-8', 'ignore')

    return (
        name.replace('\x00', '').strip() or "Unknown Token",
        symbol.replace('\x00', '').strip() or "UNK"
    )


async def find_addr(desc: list[str], db: Database) -> Optional[str]:
    """Async version of address finder"""
    wallet_addresses = await db.get_all_wallet_addresses()  
    normalized_wallet_addresses = {addr.lower().strip('.,!?') for addr in wallet_addresses}
    
    for addr in desc:
        normalized_addr = addr.lower().strip('.,!?')
        if normalized_addr in normalized_wallet_addresses:
            return addr.strip('.,!?')
    return None