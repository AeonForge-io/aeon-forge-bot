-- Test contracts use the DragonZ Test image folder, the one their own tokenURI metadata names;
-- 004 gave them the Limited Edition folder by mistake (Staxed, 2026-10-28).

UPDATE nft_collections SET image_url_template =
    'https://aeonforge.myfilebase.com/ipfs/bafybeidqwthjxicxwve62yq6rczswf5gdfaibha3cofmwm4ct5vcmewa64/{token_id}.jpg'
WHERE collection_id = 'sepolia-test';
