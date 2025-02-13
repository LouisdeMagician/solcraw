import aiohttp
from aiohttp import TCPConnector, ClientTimeout
import logging

logger = logging.getLogger(__name__)

class HTTPSessionManager:
    def __init__(self, pool_size=10, timeout=10):
        self.pool_size = pool_size
        self.timeout = timeout
        self._session = None

    async def start(self):
        """Initialize the connection pool"""
        self._session = aiohttp.ClientSession(
            connector=TCPConnector(
                limit=self.pool_size,
                force_close=True,
                enable_cleanup_closed=True
            ),
            timeout=ClientTimeout(total=self.timeout)
        )
        logger.info(f"HTTP connection pool started (size={self.pool_size})")

    async def stop(self):
        """Close the connection pool"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("HTTP connection pool stopped")

    @property
    def session(self):
        if not self._session:
            raise RuntimeError("Session manager not started")
        return self._session