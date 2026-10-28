"""The 60-second settings reload: collections, company wallets and marketplace marks.

Each reload replaces the in-memory snapshot. When the set of tracked contracts on a
chain changes, the reloader calls on_contracts_changed so that chain's subscription
can be replaced.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.core.store import Collection, CompanyWallet, MarketplaceMark, Store

logger = get_logger(__name__)

RELOAD_INTERVAL_SECONDS = 60

ContractsChanged = Callable[[str, frozenset[str]], Awaitable[None]]


@dataclass(frozen=True)
class BotSettings:
    """One reload's view of the settings tables."""

    collections: tuple[Collection, ...] = ()
    company_wallets: tuple[CompanyWallet, ...] = ()
    marketplace_marks: tuple[MarketplaceMark, ...] = ()
    tracked_contracts: dict[str, frozenset[str]] = field(default_factory=dict)

    def company_label(self, address: str) -> str | None:
        """The label of a company wallet, or None if the address is not one."""
        address = address.lower()
        for wallet in self.company_wallets:
            if wallet.address == address:
                return wallet.label
        return None


def tracked_contracts(collections: list[Collection]) -> dict[str, frozenset[str]]:
    """Contracts read on-chain, per chain: active collections with track_onchain on."""
    by_chain: dict[str, set[str]] = {}
    for c in collections:
        if c.is_active and c.track_onchain:
            by_chain.setdefault(c.chain, set()).add(c.contract_address.lower())
    return {chain: frozenset(contracts) for chain, contracts in by_chain.items()}


class SettingsReloader:
    """Re-reads the settings tables and signals tracked-contract changes per chain."""

    def __init__(self, store: Store, on_contracts_changed: ContractsChanged) -> None:
        self.store = store
        self.on_contracts_changed = on_contracts_changed
        self.current = BotSettings()

    async def reload(self) -> BotSettings:
        """Read the settings once; signal every chain whose contract set changed."""
        collections = await self.store.list_collections()
        wallets = await self.store.list_company_wallets()
        marks = await self.store.list_marketplace_marks()
        previous = self.current.tracked_contracts
        contracts = tracked_contracts(collections)
        self.current = BotSettings(
            collections=tuple(collections),
            company_wallets=tuple(wallets),
            marketplace_marks=tuple(marks),
            tracked_contracts=contracts,
        )
        for chain in sorted(previous.keys() | contracts.keys()):
            new = contracts.get(chain, frozenset())
            if new != previous.get(chain, frozenset()):
                logger.info("settings.contracts.changed", chain=chain, contracts=sorted(new))
                await self.on_contracts_changed(chain, new)
        return self.current

    async def run(self, interval: float = RELOAD_INTERVAL_SECONDS) -> None:
        """Reload forever; a failed reload is logged and the last snapshot kept."""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.reload()
            except Exception as e:
                logger.error("settings.reload.failed", error=str(e), exc_info=True)
