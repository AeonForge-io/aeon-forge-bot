"""Post sample bot posts in five design variants to the test channel.

Usage: uv run python scripts/preview_designs.py [--variant A..E] [--type mint|batch|transfer|burn|listing|sale]

Posts only to the test channel. Reads DISCORD_TOKEN from the main checkout's .env,
so it runs from any worktree.
"""

import argparse
import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import discord
from discord import ui

TEST_CHANNEL_ID = 1215729486994210897
ENV_FILE = Path("/mnt/volumes/projects/aeon-forge-bot/.env")

LOGO_URL = "https://aeonforge.io/afimg/AF.png"
WEBSITE_URL = "https://aeonforge.io"
MINT_URL = "https://aeonforge.io/mint"
SERIES_1_IMAGE = "https://aeonforge.myfilebase.com/ipfs/QmbzChm6thk9y9DcooXKyxVfharxQ98ubPhsxSfFmg8eDW/{id}.jpg"
LIMITED_EDITION_IMAGE = "https://aeonforge.myfilebase.com/ipfs/bafybeihzuj42qllwqgnz4snidjexn5lbca6x6mvhu5qn7hzgcdwnqadr7q/{id}.jpg"
TX_URL = "https://basescan.org/tx/0x9f2c61d4a7b35e08c1d94f6a2b7e83051c6d4ab9e2f7380d5c1a46b79e03d8ab"

# Website palette (af-website Tailwind theme)
CYAN = 0x00F3FF
BLUE = 0x00AAFF
ORANGE = 0xFF4D00
PURPLE = 0xBC13FE
RED = 0xB93931
NEAR_BLACK = 0x0B0B1A  # #050511 is nearly invisible on Discord's dark theme

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
TYPE_EMOJI = {"mint": "⚒️", "batch": "⚒️", "sale": "💰", "listing": "🏷️", "transfer": "📦", "burn": "🔥"}


@dataclass
class Sample:
    kind: str
    collection: str
    image_template: str
    token_ids: list[int]
    progress: list[int]  # "#N" per token, mints only
    max_supply: int
    minter: str = "0xab12…c4cd"
    price: str | None = None
    marketplace: str | None = None
    sender: str | None = None
    receiver: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

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
        links = [("Mint yours", MINT_URL)] if self.is_mint else []
        return [*links, ("Transaction", TX_URL)]

    def detail_lines(self) -> list[tuple[str, str, str]]:
        """(emoji, label, value) lines describing the event for the first token."""
        n = self.progress[0] if self.progress else 0
        if self.is_mint:
            lines = [("👤", "Minter", self.minter)]
            if self.price:
                lines.append(("💎", "Price", self.price))
            lines.append(("📈", "Progress", self.bar(n)))
            return lines
        if self.kind == "transfer":
            return [("🏦", "From", self.sender or ""), ("📬", "To", self.receiver or "")]
        if self.kind == "burn":
            return [("🔥", "Burned by", self.sender or "")]
        lines = [("💎", "Price", self.price or ""), ("🛒", "Marketplace", self.marketplace or "")]
        if self.kind == "sale":
            lines += [("🧑", "Seller", self.sender or ""), ("🤝", "Buyer", self.receiver or "")]
        else:
            lines.append(("🧑", "Seller", self.sender or ""))
        return lines


def build_samples() -> dict[str, Sample]:
    return {
        "mint": Sample("mint", "DragonZ Limited Edition", LIMITED_EDITION_IMAGE, [289], [212], 750, price="0.0015 ETH"),
        "batch": Sample(
            "batch", "DragonZ Limited Edition", LIMITED_EDITION_IMAGE, [301, 302, 303], [210, 211, 212], 750,
            price="0.0015 ETH",
        ),
        "transfer": Sample(
            "transfer", "DragonZ Series 1", SERIES_1_IMAGE, [77], [], 1122,
            sender="Aeon Forge · Treasury", receiver="0x5e9a…17f0",
        ),
        "burn": Sample("burn", "DragonZ Series 1", SERIES_1_IMAGE, [904], [], 1122, sender="0x31d4…88ae"),
        "listing": Sample(
            "listing", "DragonZ Series 1", SERIES_1_IMAGE, [412], [], 1122,
            price="0.045 ETH", marketplace="Forum One", sender="0x7c03…a9e1",
        ),
        "sale": Sample(
            "sale", "DragonZ Series 1", SERIES_1_IMAGE, [412], [], 1122,
            price="0.045 ETH", marketplace="OpenSea", sender="0x7c03…a9e1", receiver="0xb8f6…02d5",
        ),
    }


def _link_row(sample: Sample) -> ui.ActionRow:
    return ui.ActionRow(
        *[ui.Button(style=discord.ButtonStyle.link, label=label, url=url) for label, url in sample.buttons()]
    )


def _link_view(sample: Sample) -> ui.View:
    view = ui.View()
    for label, url in sample.buttons():
        view.add_item(ui.Button(style=discord.ButtonStyle.link, label=label, url=url))
    return view


def _single_embed(sample: Sample, token_id: int) -> discord.Embed:
    """Base for classic variants: one embed for one token."""
    embed = discord.Embed(colour=TYPE_COLOURS[sample.kind], timestamp=datetime.now(UTC))
    embed.set_image(url=sample.image(token_id))
    return embed


def variant_a(sample: Sample) -> dict:
    """Neon Forge: classic embed per token, fields, progress bar, branded footer."""
    embeds = []
    for index, token_id in enumerate(sample.token_ids):
        n = sample.progress[index] if sample.progress else None
        embed = _single_embed(sample, token_id)
        embed.set_author(name=sample.collection, icon_url=LOGO_URL, url=WEBSITE_URL)
        embed.title = f"{TYPE_EMOJI[sample.kind]} {sample.title(token_id)}"
        embed.url = TX_URL
        if sample.is_mint:
            embed.add_field(name="Progress", value=f"`{sample.bar(n or 0)}`", inline=True)
            if sample.price:
                embed.add_field(name="Price", value=sample.price, inline=True)
            embed.add_field(name="Minter", value=sample.minter, inline=True)
        else:
            for _, label, value in sample.detail_lines():
                embed.add_field(name=label, value=value, inline=True)
        embed.set_footer(text="Aeon Forge · Base", icon_url=LOGO_URL)
        embeds.append(embed)
    return {"embeds": embeds, "view": _link_view(sample)}


def _forge_card(sample: Sample, token_ids: list[int], headline: str, subline: str) -> ui.Container:
    container = ui.Container(accent_colour=TYPE_COLOURS[sample.kind])
    container.add_item(ui.TextDisplay(f"{headline}\n{subline}"))
    gallery = ui.MediaGallery()
    for token_id in token_ids:
        gallery.add_item(media=sample.image(token_id), description=sample.title(token_id))
    container.add_item(gallery)
    container.add_item(ui.Separator())
    return container


def variant_b(sample: Sample) -> dict:
    """Forge Card: one V2 container per token."""
    views = []
    for index, token_id in enumerate(sample.token_ids):
        n = sample.progress[index] if sample.progress else 0
        container = _forge_card(
            sample,
            [token_id],
            f"## {sample.title(token_id)}",
            f"-# {sample.collection.removeprefix('DragonZ ')} · {TYPE_VERBS[sample.kind]} on Base",
        )
        details = sample.detail_lines()
        if sample.is_mint:
            details = [(e, label, sample.bar(n) if label == "Progress" else value) for e, label, value in details]
        container.add_item(ui.TextDisplay("\n".join(f"{e} **{label}** {value}" for e, label, value in details)))
        container.add_item(ui.Separator())
        container.add_item(_link_row(sample))
        view = ui.LayoutView()
        view.add_item(container)
        views.append(view)
    return {"views": views}


def variant_c(sample: Sample) -> dict:
    """Gallery Drop: a mint transaction is one container with a grid of every token."""
    if not sample.is_mint or len(sample.token_ids) == 1:
        return variant_b(sample)
    ids = sample.token_ids
    first, last = sample.progress[0], sample.progress[-1]
    container = _forge_card(
        sample,
        ids,
        f"## {len(ids)} DragonZ forged",
        f"-# {sample.collection} · minted on Base",
    )
    container.add_item(
        ui.TextDisplay(
            f"⚒️ **{len(ids)} DragonZ forged** by {sample.minter} · #{first}–{last} of {sample.max_supply}\n"
            f"📈 {sample.bar(last)}"
        )
    )
    container.add_item(_link_row(sample))
    view = ui.LayoutView()
    view.add_item(container)
    return {"views": [view]}


def variant_d(sample: Sample) -> dict:
    """Minimal Luxe: no fields, markdown description, logo thumbnail, one button."""
    embeds = []
    for index, token_id in enumerate(sample.token_ids):
        n = sample.progress[index] if sample.progress else None
        embed = _single_embed(sample, token_id)
        embed.colour = NEAR_BLACK if sample.kind in ("sale", "listing", "transfer", "burn") else CYAN
        lines = [f"### {sample.title(token_id)}"]
        if sample.is_mint:
            lines.append(f"-# #{n} of {sample.max_supply} · minted by {sample.minter}")
            if sample.price:
                lines.append(f"-# {sample.price}")
        else:
            lines.extend(f"-# {label}: {value}" for _, label, value in sample.detail_lines())
        embed.description = "\n".join(lines)
        embed.set_thumbnail(url=LOGO_URL)
        embeds.append(embed)
    view = ui.View()
    label, url = sample.buttons()[0]
    view.add_item(ui.Button(style=discord.ButtonStyle.link, label=label, url=url))
    return {"embeds": embeds, "view": view}


def variant_e(sample: Sample) -> dict:
    """Terminal: details in an ansi block coloured like the website's code highlighting."""
    purple, blue, green, grey, reset = "\u001b[35m", "\u001b[34m", "\u001b[32m", "\u001b[30m", "\u001b[0m"
    embeds = []
    for index, token_id in enumerate(sample.token_ids):
        n = sample.progress[index] if sample.progress else None
        embed = _single_embed(sample, token_id)
        embed.colour = CYAN
        embed.title = sample.title(token_id)
        verb = {"mint": "mint", "sale": "sale", "listing": "list", "transfer": "send", "burn": "burn"}.get(
            sample.kind, "mint"
        )
        lines = [f"{purple}forge{reset}.{blue}{verb}{reset}(token={token_id}) → #{n or token_id} / {sample.max_supply}"]
        if sample.is_mint:
            lines.append(f'{purple}minter{reset} = {green}"{sample.minter}"{reset}')
        else:
            for _, label, value in sample.detail_lines():
                lines.append(f'{purple}{label.lower().replace(" ", "_")}{reset} = {green}"{value}"{reset}')
        if sample.price and sample.is_mint:
            lines.append(f'{purple}price{reset} = {green}"{sample.price}"{reset}')
        lines.append(f"{grey}// Aeon Forge · Base{reset}")
        embed.description = "```ansi\n" + "\n".join(lines) + "\n```"
        embeds.append(embed)
    return {"embeds": embeds, "view": _link_view(sample)}


VARIANTS: dict[str, tuple[str, Callable[[Sample], dict]]] = {
    "A": ("Neon Forge", variant_a),
    "B": ("Forge Card", variant_b),
    "C": ("Gallery Drop", variant_c),
    "D": ("Minimal Luxe", variant_d),
    "E": ("Terminal", variant_e),
}


def read_token() -> str:
    for line in ENV_FILE.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "DISCORD_TOKEN" and value.strip():
            return value.strip().strip("\"'")
    raise SystemExit(f"DISCORD_TOKEN is not set in {ENV_FILE}")


async def post(variants: list[str], kinds: list[str]) -> None:
    samples = build_samples()
    client = discord.Client(intents=discord.Intents.none())
    await client.login(read_token())
    try:
        channel = await client.fetch_channel(TEST_CHANNEL_ID)
        assert isinstance(channel, discord.abc.Messageable)
        for letter in variants:
            name, build = VARIANTS[letter]
            for kind in kinds:
                await channel.send(f"**Variant {letter}: {name}** · {kind}")
                built = build(samples[kind])
                if "views" in built:
                    for view in built["views"]:
                        await channel.send(view=view)
                else:
                    await channel.send(embeds=built["embeds"], view=built["view"])
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=sorted(VARIANTS), help="one variant (default all)")
    parser.add_argument("--type", choices=list(TYPE_COLOURS), help="one post type (default all)")
    args = parser.parse_args()
    asyncio.run(post([args.variant] if args.variant else sorted(VARIANTS), [args.type] if args.type else list(TYPE_COLOURS)))


if __name__ == "__main__":
    main()
