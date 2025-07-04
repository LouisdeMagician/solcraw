# Solana Wallet Monitor Bot 🍍

Telegram bot for monitoring Solana wallet activity with real-time notifications via Helius webhooks.

## Features

- Add/remove Solana wallets with aliases
- Real-time transaction alerts
- Token swap notifications
- Portfolio tracking
- Dual-channel notifications (general + token-specific)

## Setup

1. **Clone repo**
   ```bash
   git clone https://github.com/yourusername/solana-wallet-bot.git
   cd solana-wallet-bot

 2.   **Install dependencies**
    ```bash
    pip install -r requirements.txt

 3.   **Configure environment**
    ```bash
    cp .env.example .env

    Edit .env with your credentials:
    ```ini
    TELEGRAM_BOT_TOKEN="your_bot_token"
    HELIUS_API_KEY="your_helius_key"
    TELEGRAM_CHAT_ID="your_main_chat_id"
    CHAT_ID2="your_token_chat_id"

 4.   **Run bot**
    ```bash
    python bot.py

## Webhook Setup

    Get your Codespaces URL:
    ```bash
    https://<your-codespace>-8080.preview.app.github.dev/webhook

    Register webhook with Helius:
    ```bash
    curl -X POST "https://api.helius.xyz/v0/webhooks?api-key=$HELIUS_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "webhookURL": "YOUR_WEBHOOK_URL",
        "accountAddresses": ["WALLET_ADDRESS_1","WALLET_ADDRESS_2"],
        "webhookType": "enhanced"
      }'

## Usage Command
```bash
/addwallet <address> <alias> - Track new wallet
/removewallet <alias|address> - Stop tracking
/listwallets - Show monitored wallets
/portfolio <alias> - Show assets

License

MIT License - See LICENSE
