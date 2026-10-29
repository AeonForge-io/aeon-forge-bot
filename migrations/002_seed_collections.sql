-- The three collections: both DragonZ collections on Base post to the main channel,
-- the Base Sepolia test contract posts to the test channel.

INSERT INTO nft_collections (
    collection_id, name, chain, contract_address, discord_channel_id,
    track_onchain, track_marketplace, marketplaces
) VALUES
    ('dragonz-series-1', 'DragonZ Series 1', 'base',
     '0xc7c1b8a5d8777dac959cb2b274debeda1c0ecc09', 1445253310574755912,
     TRUE, TRUE, '{forum_one}'),
    ('dragonz-limited-edition', 'DragonZ Limited Edition', 'base',
     '0xa02fff7fe01eeb235cb65d501efc65c65d7ad509', 1445253310574755912,
     TRUE, TRUE, '{forum_one}'),
    ('sepolia-test', 'Sepolia Test Mint', 'base-sepolia',
     '0xad1f02d8b22fed6798a6474b65a5778cc0918afc', 1215729486994210897,
     TRUE, FALSE, '{}');
