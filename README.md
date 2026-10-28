# aeon-forge-bot

Aeon Forge's Discord bot (the Forge Bot). It posts NFT activity for Aeon Forge collections: mints with "#N of M" progress, burns, transfers from Aeon Forge company wallets, sales and Forum One listings. It reads on-chain events through Alchemy and runs in Docker on the Beast.

## Configuration

`.env` is a symlink to `/etc/stixed/secrets/aeon-forge-bot.env` and holds only `DISCORD_TOKEN`, `ALCHEMY_API_KEY`, `DB_PASSWORD` and optionally `LOG_LEVEL` (see `.env.example`). Collections, channels, per-collection switches, company wallets and marketplace marks live in the bot's Postgres database and are edited in Adminer on port 8888.

## Running

`docker compose up -d` starts three containers: `aeon-forge-bot`, `aeon-forge-bot-postgres` and `aeon-forge-bot-adminer`.

## Development

```
uv sync --extra dev
uv run pytest
uv run ruff check app tests scripts
uv run mypy app tests
```
