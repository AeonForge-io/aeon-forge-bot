"""Reads a sent Components V2 message back into what a reader sees: text, images, buttons."""

from collections.abc import Iterator
from typing import Any

from discord import ui


def _walk(item: Any) -> Iterator[Any]:
    yield item
    for child in getattr(item, "children", []):
        yield from _walk(child)


class Card:
    """What a LayoutView shows."""

    def __init__(self, view: ui.LayoutView) -> None:
        self.items = [node for child in view.children for node in _walk(child)]

    @property
    def accent(self) -> int | None:
        container = next(i for i in self.items if isinstance(i, ui.Container))
        return int(container.accent_colour) if container.accent_colour is not None else None

    @property
    def text(self) -> str:
        return "\n".join(i.content for i in self.items if isinstance(i, ui.TextDisplay))

    @property
    def images(self) -> list[str]:
        return [
            gallery_item.media.url
            for i in self.items
            if isinstance(i, ui.MediaGallery)
            for gallery_item in i.items
        ]

    @property
    def buttons(self) -> list[tuple[str, str | None]]:
        """(label, url) in display order."""
        return [(i.label or "", i.url) for i in self.items if isinstance(i, ui.Button)]

    def values(self, label: str) -> list[str]:
        """Every value after a bold label, like '**Progress** ▰▰ 2 / 750', one per token."""
        prefix = f"**{label}** "
        return [line[len(prefix) :] for line in self.text.splitlines() if line.startswith(prefix)]
