# aeon-forge-bot

Aeon Forge's Discord bot (the Forge Bot). It posts NFT activity for Aeon Forge collections: mints with "#N of M" progress, burns, transfers from Aeon Forge company wallets, sales and Forum One listings. It reads on-chain events through Alchemy and runs in Docker on the Beast.

## Configuration

`.env` is a symlink to `/etc/stixed/secrets/aeon-forge-bot.env` and holds only `DISCORD_TOKEN`, `ALCHEMY_API_KEY`, `DB_PASSWORD` and optionally `LOG_LEVEL` (see `.env.example`). Collections, channels, per-collection switches, company wallets and marketplace marks live in the bot's Postgres database and are edited in Adminer on port 8888.

## Running

`docker compose up -d` starts three containers: `aeon-forge-bot`, `aeon-forge-bot-postgres` and `aeon-forge-bot-adminer`.

## Development

```
scripts/check.sh format   # ruff format --check on app, tests, scripts
scripts/check.sh lint     # ruff, mypy strict, sqlfluff on migrations, detect-secrets, pip-audit
scripts/check.sh test     # pytest (Postgres integration tests skip without TEST_DATABASE_URL)
```

Each command syncs its own Python 3.11 environment from `uv.lock`. To fix formatting: `uv run ruff format app tests scripts`.

`scripts/lint_baseline.json` holds the findings that existed when the checks were added, counted per (file, rule); only new findings fail. After fixing some, run `scripts/check.sh lint --update` to lower the baseline. It may only go down, unless the commit message says why it went up. detect-secrets and pip-audit have no baseline; fix an advisory with `uv lock --upgrade-package NAME`.

The baseline also covers Ruff's function-size rules C901, PLR0915 and PLR0912 (Ruff's default thresholds). The Review lint check also runs Stixed's global code size check (`check_file_size.py --base main`, default limits, no `filesize.toml`), the same one the global commit hook runs.
