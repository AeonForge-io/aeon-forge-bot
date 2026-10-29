-- Primary names found for wallets (ENS on Ethereum, Basename on Base), cached for 7 days.
-- A wallet with neither is stored too (both names NULL) so it is not looked up again.
CREATE TABLE IF NOT EXISTS wallet_names (
    address TEXT PRIMARY KEY,
    ens_name TEXT,
    base_name TEXT,
    checked_at TIMESTAMPTZ NOT NULL
);
