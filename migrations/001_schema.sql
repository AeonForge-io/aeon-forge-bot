-- Aeon Forge bot schema: collections, settings tables, chain cursors and NFT events.
-- Addresses and hex values are stored lowercased; CHECKs refuse anything else.

-- One row per tracked collection; edited in Adminer and re-read every 60 seconds
CREATE TABLE nft_collections (
    id SERIAL PRIMARY KEY,
    collection_id TEXT UNIQUE NOT NULL,  -- slug, e.g. "dragonz-series-1"
    name TEXT NOT NULL,
    chain TEXT NOT NULL CHECK (chain IN ('base', 'base-sepolia')),
    contract_address TEXT NOT NULL CHECK (contract_address = lower(contract_address)),
    discord_channel_id BIGINT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    track_onchain BOOLEAN NOT NULL DEFAULT TRUE,
    track_marketplace BOOLEAN NOT NULL DEFAULT FALSE,
    marketplaces TEXT[] NOT NULL DEFAULT '{}',  -- 'forum_one' is the only value in use
    post_mints BOOLEAN NOT NULL DEFAULT TRUE,
    post_burns BOOLEAN NOT NULL DEFAULT TRUE,
    post_sales BOOLEAN NOT NULL DEFAULT TRUE,
    post_listings BOOLEAN NOT NULL DEFAULT TRUE,
    transfer_mode TEXT NOT NULL DEFAULT 'company'
        CHECK (transfer_mode IN ('off', 'company', 'all')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (chain, contract_address)
);

-- Aeon Forge wallets whose outgoing transfers post (transfer_mode 'company' or 'all')
CREATE TABLE company_wallets (
    id SERIAL PRIMARY KEY,
    address TEXT UNIQUE NOT NULL CHECK (address = lower(address)),
    label TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Marks that name the marketplace behind a Seaport sale
CREATE TABLE marketplace_marks (
    id SERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('fee_wallet', 'zone', 'calldata_tag')),
    value TEXT NOT NULL CHECK (value = lower(value)),
    marketplace TEXT NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (kind, value)
);

-- Last block whose logs are stored, per chain
CREATE TABLE chain_cursors (
    chain TEXT PRIMARY KEY,
    last_block BIGINT NOT NULL,
    last_block_time TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Post status of every recorded event:
--   pending  waiting to be posted (or retried)
--   posted   sent to Discord
--   skipped  its switch was off when it was recorded; never posted later
--   expired  still unposted 6 hours after the event

CREATE TABLE nft_mints (
    id SERIAL PRIMARY KEY,
    collection_id INT NOT NULL REFERENCES nft_collections(id),
    token_id TEXT NOT NULL,
    to_address TEXT NOT NULL,
    chain TEXT,
    token_image_url TEXT,
    price_native NUMERIC,
    price_usd NUMERIC,
    progress_number INT,  -- N in "#N of M"
    max_supply INT,       -- M in "#N of M"
    transaction_hash TEXT,
    block_number BIGINT,
    event_timestamp TIMESTAMPTZ NOT NULL,
    post_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (post_status IN ('pending', 'posted', 'skipped', 'expired')),
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (collection_id, token_id, transaction_hash)
);

CREATE TABLE nft_transfers (
    id SERIAL PRIMARY KEY,
    collection_id INT NOT NULL REFERENCES nft_collections(id),
    token_id TEXT NOT NULL,
    from_address TEXT NOT NULL,
    to_address TEXT NOT NULL,
    chain TEXT,
    token_image_url TEXT,
    transaction_hash TEXT,
    block_number BIGINT,
    event_timestamp TIMESTAMPTZ NOT NULL,
    post_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (post_status IN ('pending', 'posted', 'skipped', 'expired')),
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (collection_id, token_id, transaction_hash)
);

CREATE TABLE nft_burns (
    id SERIAL PRIMARY KEY,
    collection_id INT NOT NULL REFERENCES nft_collections(id),
    token_id TEXT NOT NULL,
    from_address TEXT NOT NULL,
    chain TEXT,
    token_image_url TEXT,
    transaction_hash TEXT,
    block_number BIGINT,
    event_timestamp TIMESTAMPTZ NOT NULL,
    post_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (post_status IN ('pending', 'posted', 'skipped', 'expired')),
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (collection_id, token_id, transaction_hash)
);

CREATE TABLE nft_listings (
    id SERIAL PRIMARY KEY,
    collection_id INT NOT NULL REFERENCES nft_collections(id),
    token_id TEXT NOT NULL,
    token_name TEXT,
    token_image_url TEXT,
    seller_address TEXT NOT NULL,
    marketplace TEXT NOT NULL,
    price_native NUMERIC NOT NULL,
    price_usd NUMERIC,
    currency TEXT,
    floor_price_native NUMERIC,
    rarity_rank INT,
    listing_id TEXT,  -- the marketplace's id; Forum One's orderHash
    expires_at TIMESTAMPTZ,
    event_timestamp TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    post_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (post_status IN ('pending', 'posted', 'skipped', 'expired')),
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (collection_id, marketplace, listing_id)
);

CREATE TABLE nft_sales (
    id SERIAL PRIMARY KEY,
    collection_id INT NOT NULL REFERENCES nft_collections(id),
    token_id TEXT NOT NULL,
    token_name TEXT,
    token_image_url TEXT,
    seller_address TEXT NOT NULL,
    buyer_address TEXT NOT NULL,
    marketplace TEXT NOT NULL,
    price_native NUMERIC NOT NULL,
    price_usd NUMERIC,
    currency TEXT,
    floor_price_native NUMERIC,
    rarity_rank INT,
    sale_id TEXT,
    transaction_hash TEXT,
    event_timestamp TIMESTAMPTZ NOT NULL,
    post_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (post_status IN ('pending', 'posted', 'skipped', 'expired')),
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (collection_id, marketplace, sale_id),
    -- One sale posts once, whichever source sees it
    UNIQUE (collection_id, transaction_hash, token_id)
);

CREATE INDEX idx_nft_mints_pending ON nft_mints(post_status, event_timestamp);
CREATE INDEX idx_nft_transfers_pending ON nft_transfers(post_status, event_timestamp);
CREATE INDEX idx_nft_burns_pending ON nft_burns(post_status, event_timestamp);
CREATE INDEX idx_nft_listings_pending ON nft_listings(post_status, event_timestamp);
CREATE INDEX idx_nft_sales_pending ON nft_sales(post_status, event_timestamp);

-- Marketplace polling state per collection; a row means the first-poll baseline is stored
CREATE TABLE nft_marketplace_state (
    collection_id INT NOT NULL REFERENCES nft_collections(id),
    marketplace TEXT NOT NULL,
    last_poll_timestamp TIMESTAMPTZ,
    last_event_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (collection_id, marketplace)
);
