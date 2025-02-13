from pydantic import BaseModel
from typing import List, Optional

class Wallet(BaseModel):
    address: str
    alias: str
    last_checked: Optional[int] = None
    tx_count: int = 0
    sol_balance: float = 0.0
    last_asset_check: Optional[int] = None
    tokens: Optional[str] = None

class TokenTransfer(BaseModel):
    mint: str
    token_amount: float
    decimals: int
    from_account: str
    to_account: str

class SolanaTransaction(BaseModel):
    signature: str
    timestamp: int
    type: str
    account_data: List[dict]
    token_transfers: List[TokenTransfer]