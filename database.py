import aiosqlite
from contextlib import asynccontextmanager
from typing import Optional, Dict, List, Any
import json
from datetime import datetime
import asyncio
import logging

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path.split("///")[-1]
        self.pool: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Create thread-safe connection pool"""
        self.pool = await aiosqlite.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,
            timeout=10
        )
        # Set row factory to return dictionaries
        self.pool.row_factory = aiosqlite.Row
        await self.pool.execute("PRAGMA journal_mode=WAL")
        await self.pool.execute("PRAGMA synchronous=NORMAL")
        await self._migrate()

    async def close(self):
        """Ensure complete database cleanup"""
        if self.pool:
            try:
                await self.pool.close()
                # Wait for all connections to close
                await asyncio.sleep(0.25)
                if self.pool._connection:
                    await self.pool._connection.close()
            except Exception as e:
                logger.error(f"Database close error: {str(e)}")
            finally:
                self.pool = None

    async def _migrate(self):
        """Initialize database schema with proper cursor management"""
        try:
            # Start transaction
            await self.pool.execute("BEGIN")
            
            # Create main table
            await self.pool.execute('''
                CREATE TABLE IF NOT EXISTS wallets (
                    address TEXT PRIMARY KEY,
                    alias TEXT UNIQUE NOT NULL,
                    last_checked INTEGER DEFAULT 0,
                    tx_count INTEGER DEFAULT 0,
                    sol_balance REAL DEFAULT 0,
                    tokens TEXT,
                    last_asset_check INTEGER DEFAULT 0,
                    last_activity_at INTEGER DEFAULT 0
                )''')

            # Get existing columns
            columns = []
            async with self.pool.execute("PRAGMA table_info(wallets)") as cursor:
                rows = await cursor.fetchall()
                columns = [row['name'] for row in rows]

            # Add missing columns
            for col, col_type in [('last_activity_at', 'INTEGER'),
                                ('tokens', 'TEXT'),
                                ('sol_balance', 'REAL')]:
                if col not in columns:
                    await self.pool.execute(f"ALTER TABLE wallets ADD COLUMN {col} {col_type}")

            # Commit transaction
            await self.pool.execute("COMMIT")
            
        except Exception as e:
            # Rollback on error
            await self.pool.execute("ROLLBACK")
            raise


    async def get_wallet(self, identifier: str) -> Optional[Dict[str, Any]]:
        async with self.pool.execute(
            """SELECT *, MAX(last_activity_at, last_asset_check) as last_modified 
               FROM wallets 
               WHERE address = ? OR LOWER(alias) = LOWER(?)""",
            (identifier, identifier)
        ) as cursor:
            result = await cursor.fetchone()
            return dict(result) if result else None

    async def save_wallet(self, address: str, alias: str) -> None:
        try:
            await self.pool.execute(
                "INSERT INTO wallets (address, alias, last_checked) VALUES (?, ?, ?)",
                (address, alias.lower(), int(datetime.now().timestamp()))
            )
            await self.pool.commit()
        except aiosqlite.IntegrityError as e:
            raise ValueError(f"Alias '{alias}' already exists") from e

    async def remove_wallet(self, address: str) -> None:
        await self.pool.execute("DELETE FROM wallets WHERE address = ?", (address,))
        await self.pool.commit()

    async def load_all_wallets(self) -> List[Dict[str, Any]]:
        async with self.pool.execute("SELECT * FROM wallets") as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def update_portfolio(self, address: str, sol_balance: float, tokens: List[Dict]) -> None:
        await self.pool.execute(
            """UPDATE wallets 
            SET sol_balance = ?, 
                tokens = ?,
                last_asset_check = ?
            WHERE address = ?""",
            (sol_balance, json.dumps(tokens), int(datetime.now().timestamp()), address)
            )
        await self.pool.commit()

    async def record_wallet_activity(self, address: str) -> None:
        await self.pool.execute('''
            UPDATE wallets 
            SET 
                last_activity_at = ?,
                tx_count = tx_count + 1
            WHERE address = ?
        ''', (int(datetime.now().timestamp()), address))
        await self.pool.commit()

    async def get_all_wallet_addresses(self) -> List[str]:
        async with self.pool.execute("SELECT address FROM wallets") as cursor:
            return [row['address'] for row in await cursor.fetchall()]