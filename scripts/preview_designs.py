"""Post sample bot posts in the chosen design (Forge Card) to the test channel.

Usage: uv run python scripts/preview_designs.py [--type mint|batch|transfer|burn|listing|sale]

Posts only to the test channel. Reads DISCORD_TOKEN from the main checkout's .env,
so it runs from any worktree.
"""

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

import discord
from discord import ui

TEST_CHANNEL_ID = 1215729486994210897
ENV_FILE = Path("/mnt/volumes/projects/aeon-forge-bot/.env")

MINT_URL = "https://aeonforge.io/mint"
FORUM_ONE_COLLECTION_URL = "https://forumone.io/collection/8453/{contract}"
SERIES_1_CONTRACT = "0xc7c1b8a5d8777dac959cb2b274debeda1c0ecc09"
LIMITED_EDITION_CONTRACT = "0xa02fff7fe01eeb235cb65d501efc65c65d7ad509"
SERIES_1_IMAGE = (
    "https://aeonforge.myfilebase.com/ipfs/QmbzChm6thk9y9DcooXKyxVfharxQ98ubPhsxSfFmg8eDW/{id}.jpg"
)
LIMITED_EDITION_IMAGE = "https://aeonforge.myfilebase.com/ipfs/bafybeihzuj42qllwqgnz4snidjexn5lbca6x6mvhu5qn7hzgcdwnqadr7q/{id}.jpg"
TX_URL = (
    "https://basescan.org/tx/0x9f2c61d4a7b35e08c1d94f6a2b7e83051c6d4ab9e2f7380d5c1a46b79e03d8ab"
)

# Website palette (af-website Tailwind theme)
CYAN = 0x00F3FF
BLUE = 0x00AAFF
ORANGE = 0xFF4D00
PURPLE = 0xBC13FE
RED = 0xB93931

TYPE_COLOURS = {
    "mint": CYAN,
    "batch": CYAN,
    "sale": ORANGE,
    "listing": PURPLE,
    "transfer": BLUE,
    "burn": RED,
}
TYPE_VERBS = {
    "mint": "minted",
    "batch": "minted",
    "sale": "sold",
    "listing": "listed",
    "transfer": "sent",
    "burn": "burned",
}


@dataclass
class Sample:
    kind: str
    collection: str
    image_template: str
    token_ids: list[int]
    progress: list[int]  # "#N" per token, mints only
    max_supply: int
    contract: str
    minter: str = "0xab12…c4cd"
    price: str | None = None
    marketplace: str | None = None
    sender: str | None = None
    receiver: str | None = None

    @property
    def is_mint(self) -> bool:
        return self.kind in ("mint", "batch")

    def image(self, token_id: int) -> str:
        return self.image_template.format(id=token_id)

    def title(self, token_id: int) -> str:
        return f"{self.collection} #{token_id}"

    def bar(self, n: int) -> str:
        filled = round(10 * n / self.max_supply)
        return "▰" * filled + "▱" * (10 - filled) + f" {n} / {self.max_supply}"

    def buttons(self) -> list[tuple[str, str]]:
        """Transaction link on the left, the post's own link on the right."""
        if self.is_mint:
            return [("Transaction", TX_URL), ("Mint yours", MINT_URL)]
        browse = FORUM_ONE_COLLECTION_URL.format(contract=self.contract)
        return [("Transaction", TX_URL), ("Browse Forum One", browse)]

    def detail_lines(self) -> list[tuple[str, str]]:
        """(label, value) lines describing the event."""
        n = self.progress[0] if self.progress else 0
        if self.is_mint:
            lines = [("Minter", self.minter)]
            if self.price:
                lines.append(("Price", self.price))
            lines.append(("Progress", self.bar(n)))
            return lines
        if self.kind == "transfer":
            return [("From", self.sender or ""), ("To", self.receiver or "")]
        if self.kind == "burn":
            return [("Burned by", self.sender or "")]
        lines = [("Price", self.price or ""), ("Marketplace", self.marketplace or "")]
        if self.kind == "sale":
            lines += [("Seller", self.sender or ""), ("Buyer", self.receiver or "")]
        else:
            lines.append(("Seller", self.sender or ""))
        return lines


def build_samples() -> dict[str, Sample]:
    return {
        "mint": Sample(
            "mint",
            "DragonZ Limited Edition",
            LIMITED_EDITION_IMAGE,
            [289],
            [212],
            750,
            LIMITED_EDITION_CONTRACT,
            price="0.0015 ETH",
        ),
        "batch": Sample(
            "batch",
            "DragonZ Limited Edition",
            LIMITED_EDITION_IMAGE,
            [301, 302, 303],
            [210, 211, 212],
            750,
            LIMITED_EDITION_CONTRACT,
            price="0.0015 ETH",
        ),
        "transfer": Sample(
            "transfer",
            "DragonZ Series 1",
            SERIES_1_IMAGE,
            [77],
            [],
            1122,
            SERIES_1_CONTRACT,
            sender="Aeon Forge · Treasury",
            receiver="0x5e9a…17f0",
        ),
        "burn": Sample(
            "burn",
            "DragonZ Series 1",
            SERIES_1_IMAGE,
            [904],
            [],
            1122,
            SERIES_1_CONTRACT,
            sender="0x31d4…88ae",
        ),
        "listing": Sample(
            "listing",
            "DragonZ Series 1",
            SERIES_1_IMAGE,
            [412],
            [],
            1122,
            SERIES_1_CONTRACT,
            price="0.045 ETH",
            marketplace="Forum One",
            sender="0x7c03…a9e1",
        ),
        "sale": Sample(
            "sale",
            "DragonZ Series 1",
            SERIES_1_IMAGE,
            [412],
            [],
            1122,
            SERIES_1_CONTRACT,
            price="0.045 ETH",
            marketplace="OpenSea",
            sender="0x7c03…a9e1",
            receiver="0xb8f6…02d5",
        ),
    }


def _link_row(sample: Sample) -> ui.ActionRow[ui.LayoutView]:
    return ui.ActionRow(
        *[
            ui.Button(style=discord.ButtonStyle.link, label=label, url=url)
            for label, url in sample.buttons()
        ]
    )


def forge_card(sample: Sample) -> list[ui.LayoutView]:
    """Forge Card: one V2 container per token (tokens in a mint are not sequential)."""
    views = []
    for index, token_id in enumerate(sample.token_ids):
        n = sample.progress[index] if sample.progress else 0
        details = sample.detail_lines()
        if sample.is_mint:
            details = [
                (label, sample.bar(n) if label == "Progress" else value) for label, value in details
            ]
        container: ui.Container[ui.LayoutView] = ui.Container(
            accent_colour=TYPE_COLOURS[sample.kind]
        )
        container.add_item(
            ui.TextDisplay(f"## {sample.title(token_id)}\n-# {TYPE_VERBS[sample.kind]} on Base")
        )
        gallery: ui.MediaGallery[ui.LayoutView] = ui.MediaGallery()
        gallery.add_item(media=sample.image(token_id), description=sample.title(token_id))
        container.add_item(gallery)
        container.add_item(ui.Separator())
        container.add_item(
            ui.TextDisplay("\n".join(f"**{label}** {value}" for label, value in details))
        )
        container.add_item(ui.Separator())
        container.add_item(_link_row(sample))
        view = ui.LayoutView()
        view.add_item(container)
        views.append(view)
    return views


def read_token() -> str:
    for line in ENV_FILE.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "DISCORD_TOKEN" and value.strip():
            return value.strip().strip("\"'")
    raise SystemExit(f"DISCORD_TOKEN is not set in {ENV_FILE}")


async def post(kinds: list[str]) -> None:
    samples = build_samples()
    client = discord.Client(intents=discord.Intents.none())
    await client.login(read_token())
    try:
        channel = await client.fetch_channel(TEST_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise SystemExit(f"Channel {TEST_CHANNEL_ID} cannot take messages")
        for kind in kinds:
            await channel.send(f"**Variant B: Forge Card (round 3)** · {kind}")
            for view in forge_card(samples[kind]):
                await channel.send(view=view)
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", choices=list(TYPE_COLOURS), help="one post type (default all)")
    args = parser.parse_args()
    asyncio.run(post([args.type] if args.type else list(TYPE_COLOURS)))


if __name__ == "__main__":
    main()
