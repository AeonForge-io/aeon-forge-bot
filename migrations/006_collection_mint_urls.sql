-- Mint posts link to the collection's mint page; a collection without one gets no "Mint yours" button.
-- Series 1 is minted out and has none.

ALTER TABLE nft_collections ADD COLUMN mint_url TEXT;

UPDATE nft_collections SET mint_url = 'https://aeonforge.io/mint'
WHERE collection_id IN ('dragonz-limited-edition', 'sepolia-test');
