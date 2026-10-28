-- NFT Tracking Tables
-- Migration: 006_nft_tracking.sql
-- Purpose: Add tables for tracking NFT on-chain and marketplace events

-- NFT Collections (mirrors JSON config for FK relationships)
CREATE TABLE IF NOT EXISTS nft_collections (
    id SERIAL PRIMARY KEY,
    collection_id TEXT UNIQUE NOT NULL,  -- e.g., "aeon-forge-genesis"
    name TEXT NOT NULL,
    chain TEXT NOT NULL,
    contract_address TEXT NOT NULL,
    discord_channel_id BIGINT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(chain, contract_address)
);

CREATE INDEX IF NOT EXISTS idx_nft_collections_chain ON nft_collections(chain);
CREATE INDEX IF NOT EXISTS idx_nft_collections_contract ON nft_collections(contract_address);

-- NFT Mints
CREATE TABLE IF NOT EXISTS nft_mints (
    id SERIAL PRIMARY KEY,
    collection_id INT REFERENCES nft_collections(id),
    token_id TEXT NOT NULL,
    to_address TEXT NOT NULL,
    price_native NUMERIC,
    price_usd NUMERIC,
    transaction_hash TEXT,
    block_number BIGINT,
    event_timestamp TIMESTAMP NOT NULL,
    posted_to_discord BOOLEAN DEFAULT FALSE,
    posted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(collection_id, token_id, transaction_hash)
);

CREATE INDEX IF NOT EXISTS idx_nft_mints_collection ON nft_mints(collection_id);
CREATE INDEX IF NOT EXISTS idx_nft_mints_unposted ON nft_mints(posted_to_discord, created_at);

-- NFT Transfers
CREATE TABLE IF NOT EXISTS nft_transfers (
    id SERIAL PRIMARY KEY,
    collection_id INT REFERENCES nft_collections(id),
    token_id TEXT NOT NULL,
    from_address TEXT NOT NULL,
    to_address TEXT NOT NULL,
    transaction_hash TEXT,
    block_number BIGINT,
    event_timestamp TIMESTAMP NOT NULL,
    posted_to_discord BOOLEAN DEFAULT FALSE,
    posted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(collection_id, token_id, transaction_hash)
);

CREATE INDEX IF NOT EXISTS idx_nft_transfers_collection ON nft_transfers(collection_id);
CREATE INDEX IF NOT EXISTS idx_nft_transfers_unposted ON nft_transfers(posted_to_discord, created_at);

-- NFT Burns
CREATE TABLE IF NOT EXISTS nft_burns (
    id SERIAL PRIMARY KEY,
    collection_id INT REFERENCES nft_collections(id),
    token_id TEXT NOT NULL,
    from_address TEXT NOT NULL,
    transaction_hash TEXT,
    block_number BIGINT,
    event_timestamp TIMESTAMP NOT NULL,
    posted_to_discord BOOLEAN DEFAULT FALSE,
    posted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(collection_id, token_id, transaction_hash)
);

CREATE INDEX IF NOT EXISTS idx_nft_burns_collection ON nft_burns(collection_id);
CREATE INDEX IF NOT EXISTS idx_nft_burns_unposted ON nft_burns(posted_to_discord, created_at);

-- NFT Listings
CREATE TABLE IF NOT EXISTS nft_listings (
    id SERIAL PRIMARY KEY,
    collection_id INT REFERENCES nft_collections(id),
    token_id TEXT NOT NULL,
    token_name TEXT,
    token_image_url TEXT,
    seller_address TEXT NOT NULL,
    marketplace TEXT NOT NULL,
    price_native NUMERIC NOT NULL,
    price_usd NUMERIC,
    floor_price_native NUMERIC,
    rarity_rank INT,
    listing_id TEXT,  -- Marketplace's listing ID for deduplication
    event_timestamp TIMESTAMP NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    posted_to_discord BOOLEAN DEFAULT FALSE,
    posted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(collection_id, marketplace, listing_id)
);

CREATE INDEX IF NOT EXISTS idx_nft_listings_collection ON nft_listings(collection_id);
CREATE INDEX IF NOT EXISTS idx_nft_listings_marketplace ON nft_listings(marketplace);
CREATE INDEX IF NOT EXISTS idx_nft_listings_unposted ON nft_listings(posted_to_discord, created_at);
CREATE INDEX IF NOT EXISTS idx_nft_listings_active ON nft_listings(collection_id, is_active);

-- NFT Sales
CREATE TABLE IF NOT EXISTS nft_sales (
    id SERIAL PRIMARY KEY,
    collection_id INT REFERENCES nft_collections(id),
    token_id TEXT NOT NULL,
    token_name TEXT,
    token_image_url TEXT,
    seller_address TEXT NOT NULL,
    buyer_address TEXT NOT NULL,
    marketplace TEXT NOT NULL,
    price_native NUMERIC NOT NULL,
    price_usd NUMERIC,
    floor_price_native NUMERIC,
    rarity_rank INT,
    sale_id TEXT,  -- Marketplace's sale/transaction ID for deduplication
    event_timestamp TIMESTAMP NOT NULL,
    posted_to_discord BOOLEAN DEFAULT FALSE,
    posted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(collection_id, marketplace, sale_id)
);

CREATE INDEX IF NOT EXISTS idx_nft_sales_collection ON nft_sales(collection_id);
CREATE INDEX IF NOT EXISTS idx_nft_sales_marketplace ON nft_sales(marketplace);
CREATE INDEX IF NOT EXISTS idx_nft_sales_unposted ON nft_sales(posted_to_discord, created_at);

-- Processing state for marketplace polling (per collection per marketplace)
CREATE TABLE IF NOT EXISTS nft_marketplace_state (
    collection_id INT REFERENCES nft_collections(id),
    marketplace TEXT NOT NULL,
    last_poll_timestamp TIMESTAMP,
    last_event_id TEXT,  -- For cursor-based pagination if supported
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (collection_id, marketplace)
);
