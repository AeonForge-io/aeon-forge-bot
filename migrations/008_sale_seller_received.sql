-- A sale found only by payment to the seller shows what the seller received, not a gross price
ALTER TABLE nft_sales ADD COLUMN seller_received BOOLEAN NOT NULL DEFAULT FALSE;
