-- Where a posted listing's Discord message lives, so it can be deleted or marked sold.
ALTER TABLE nft_listings
    ADD COLUMN IF NOT EXISTS discord_channel_id BIGINT,
    ADD COLUMN IF NOT EXISTS discord_message_id BIGINT;
