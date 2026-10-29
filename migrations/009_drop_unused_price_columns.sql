-- Dollar prices, floor prices and rarity ranks are no longer stored or shown.
ALTER TABLE nft_mints DROP COLUMN IF EXISTS price_usd;
ALTER TABLE nft_listings
    DROP COLUMN IF EXISTS price_usd,
    DROP COLUMN IF EXISTS floor_price_native,
    DROP COLUMN IF EXISTS rarity_rank;
ALTER TABLE nft_sales
    DROP COLUMN IF EXISTS price_usd,
    DROP COLUMN IF EXISTS floor_price_native,
    DROP COLUMN IF EXISTS rarity_rank;
