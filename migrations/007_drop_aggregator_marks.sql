-- The eight aggregator calldata tags seeded by 003 name no chosen marketplace and none appears
-- on Base. A tag hit comes before the fee wallet and zone, so one of them would mislabel an
-- OpenSea order filled through an aggregator.
-- The OpenSea and OKX marks stay.

DELETE FROM marketplace_marks
WHERE kind = 'calldata_tag'
  AND value IN (
    '0x332d1229',  -- Blur
    '0x72db8c0b',  -- Gem
    '0x0021fb3f',  -- Mint.fun
    '0x1d4da48b',  -- Reservoir
    '0xc4ac6e7e',  -- LooksRare
    '0xa8a9c101',  -- Magically
    '0x61598d6d',  -- Flip
    '0x64617461'   -- Rarible
  );

UPDATE marketplace_marks
SET note = 'checked on Base 2026-10-28 (aeon-forge-bot#13)'
WHERE (kind, value) IN (
    ('fee_wallet', '0x0000a26b00c1f0df003000390027140000faa719'),
    ('zone', '0x000056f7000000ece9003ca63978907a00ffd100'),
    ('zone', '0xdf2d4bffec010debd302674c9fb9cda99bb5e852')
);
