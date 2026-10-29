-- Token images come from Aeon Forge's Filebase IPFS gateway: {token_id} is replaced by the token id.
-- The tokenURI metadata route failed: the Pinata gateway refuses content not pinned to the account (Staxed, 2026-10-28).

ALTER TABLE nft_collections ADD COLUMN image_url_template TEXT;

UPDATE nft_collections SET image_url_template =
    'https://aeonforge.myfilebase.com/ipfs/QmbzChm6thk9y9DcooXKyxVfharxQ98ubPhsxSfFmg8eDW/{token_id}.jpg'
WHERE collection_id = 'dragonz-series-1';

-- DragonZ Limited Edition; 005 moves the test contracts to their own folder
UPDATE nft_collections SET image_url_template =
    'https://aeonforge.myfilebase.com/ipfs/bafybeihzuj42qllwqgnz4snidjexn5lbca6x6mvhu5qn7hzgcdwnqadr7q/{token_id}.jpg'
WHERE collection_id IN ('dragonz-limited-edition', 'sepolia-test');
