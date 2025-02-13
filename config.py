# config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    telegram_bot_token: str
    helius_api_key: str
    telegram_chat_id: str
    telegram_chat_id2: str
    database_url: str = "wallets.db" # Add this line
    solana_cluster_url: str = "https://api.mainnet-beta.solana.com"
    CACHE_TTL: int 
    webhook_secret: str

    @property
    def das_endpoint(self) -> str:
        return f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

settings = Settings()