import aiohttp
import logging
from typing import Dict, List, Tuple, Any, Optional
from aiohttp_retry import RetryClient, ExponentialRetry
from config import settings
import asyncio
from connection_pool import HTTPSessionManager

logger = logging.getLogger(__name__)

class HeliusClient:
    def __init__(self, api_key: str, session_manager: HTTPSessionManager):
        self.session_manager = session_manager
        
        if not api_key:
            raise ValueError("HELIUS_API_KEY must be provided")
        self.api_key = api_key
        self.solana_rpc_url = "https://api.mainnet-beta.solana.com"
        self.helius_base_url = f"https://mainnet.helius-rpc.com/?api-key={self.api_key}"
        self.client: Optional[RetryClient] = None
        self._session: Optional[aiohttp.ClientSession] = None

        self.retry_options = ExponentialRetry(
            attempts=3,
            statuses={429, 500, 502, 503, 504},
            exceptions={aiohttp.ClientError, asyncio.TimeoutError},
            factor=2
        )

    async def __aenter__(self):
        """Async context manager entry"""
        timeout = aiohttp.ClientTimeout(total=10)
        self._session = aiohttp.ClientSession(timeout=timeout)
        self.client = RetryClient(
            client_session=self._session,
            retry_options=self.retry_options
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Async context manager exit with proper cleanup"""
        await self.close()
        
        # Log unexpected exceptions
        if exc_type and not isinstance(exc, asyncio.CancelledError):
            logger.error(f"HeliusClient error: {exc}", exc_info=True)

    async def get_portfolio(self, wallet_address: str) -> Tuple[float, List[Dict[str, Any]]]:
        """Fetch complete portfolio using both Solana RPC and Helius API"""
        try:
            async with asyncio.TaskGroup() as tg:
                sol_task = tg.create_task(self._get_sol_balance(wallet_address))
                tokens_task = tg.create_task(self._get_token_assets(wallet_address))
            
            return sol_task.result(), tokens_task.result()
        except Exception as e:
            logger.error(f"Failed to fetch portfolio: {str(e)}")
            raise

    async def _get_sol_balance(self, wallet_address: str) -> float:
        """Get SOL balance using Solana public RPC"""
        if not self.client:
            raise RuntimeError("Client not initialized")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [wallet_address]
        }
        
        async with self.client.post(self.solana_rpc_url, json=payload) as response:
            response.raise_for_status()
            data = await response.json()
            return float(data['result']['value']) / (10 ** 9)

    async def _get_token_assets(self, wallet_address: str) -> List[Dict[str, Any]]:
        """Get token assets using Helius getAssetsByOwner method"""
        if not self.client:
            raise RuntimeError("Client not initialized")

        payload = {
            "jsonrpc": "2.0",
            "id": "my-id",
            "method": "getAssetsByOwner",
            "params": {
                "ownerAddress": wallet_address,
                "displayOptions": {"showFungible": True}
            }
        }
        
        async with self.client.post(self.helius_base_url, json=payload) as response:
            response.raise_for_status()
            data = await response.json()
            return self._parse_token_data(data)

    def _parse_token_data(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse token data with enhanced validation and error handling"""
        try:
            items = data.get('result', {}).get('items', [])
            return [
                {
                    'name': item['content']['metadata'].get('name', 'Unknown Token'),
                    'symbol': item['token_info'].get('symbol', 'UNKNOWN'),
                    'amount': item['token_info'].get('balance', 0),
                    'decimals': item['token_info'].get('decimals', 0)
                }
                for item in items 
                if item.get('interface') == 'FungibleToken'
            ]
        except KeyError as e:
            logger.error(f"Missing key in token data: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error parsing token data: {str(e)}")
            return []

    async def close(self):
        """Cleanup client resources"""
        try:
            if self.client:
                await self.client.close()
            if self._session:
                await self._session.close()
        except Exception as e:
            logger.warning(f"Error closing client: {str(e)}")
        finally:
            self.client = None
            self._session = None