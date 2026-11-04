-- How long a collection holds new Forum One listings,
-- so a burst posts as one grouped post. 0 posts each listing at once.
-- 360 minutes is the 6-hour expiry of a pending listing.
ALTER TABLE nft_collections
ADD COLUMN IF NOT EXISTS listing_group_minutes INT NOT NULL DEFAULT 15
CHECK (listing_group_minutes BETWEEN 0 AND 360);
