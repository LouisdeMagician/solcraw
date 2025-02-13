import resource
import psutil
from datetime import datetime
import logging
import asyncio

logger = logging.getLogger(__name__)

class ResourceMonitor:
    def __init__(self, interval=60):
        self.interval = interval
        self._task = None

    async def start(self):
        """Start periodic resource monitoring"""
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Resource monitor started")

    async def stop(self):
        """Stop resource monitoring"""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Resource monitor stopped")

    async def _monitor_loop(self):
        """Periodically log resource usage"""
        while True:
            self.log_resources()
            await asyncio.sleep(self.interval)

    def log_resources(self):
        """Log current resource usage"""
        try:
            process = psutil.Process()
            connections = process.net_connections(kind='tcp') 
            mem = psutil.virtual_memory()
            
            log_data = {
                "timestamp": datetime.now().isoformat(),
                "cpu_percent": process.cpu_percent(interval=0.1),
                "memory_rss": process.memory_info().rss / 1024 / 1024,
                "connections": len(connections),
                "open_files": len(process.open_files()),
                "system_memory_used": mem.used / 1024 / 1024,
                "system_memory_total": mem.total / 1024 / 1024
            }

            logger.debug(
                f"Resource Usage | "
                f"CPU: {log_data['cpu_percent']:.1f}% | "
                f"Memory: {log_data['memory_rss']:.1f}MB | "
                f"Files: {log_data['open_files']} | "
                f"Connections: {log_data['connections']}"
            )
        except Exception as e:
            logger.error(f"Resource monitoring error: {str(e)}")