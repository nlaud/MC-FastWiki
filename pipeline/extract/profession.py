"""Extract villager professions from Tier A registry data filtered by trade presence.

The vanilla data pack registers 15 villager professions in `registries["villager_profession"]`.
Thirteen become entity pages. `none` and `nitwit` are excluded because neither offers trades:
`none` has no trades, no sprite, and is an unemployed redirect; `nitwit` offers no trades and
is excluded by scope decision.

The rule is: keep professions known to the trade index.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from pipeline.enrich.resource_location import NAMESPACE

__all__ = [
    "ProfessionEntry",
    "ProfessionIndex",
    "extract_professions",
]


def _profession_display_name(path: str) -> str:
    """Return the display name for a profession registry path."""
    return path.replace("_", " ").title()


@dataclass(frozen=True)
class ProfessionEntry:
    """The complete extracted facts of one villager profession from Tier A data."""

    id: str
    path: str
    name: str
    page_title: str
    trade_name: str


@dataclass(frozen=True)
class ProfessionIndex:
    """All villager professions extracted from Tier A data and known to the trade index."""

    entries: tuple[ProfessionEntry, ...] = ()
    by_id: Mapping[str, ProfessionEntry] = field(default_factory=dict)
    by_path: Mapping[str, ProfessionEntry] = field(default_factory=dict)
    by_name: Mapping[str, ProfessionEntry] = field(default_factory=dict)

    @classmethod
    def build(cls, entries: Sequence[ProfessionEntry]) -> "ProfessionIndex":
        return cls(
            entries=tuple(entries),
            by_id={entry.id: entry for entry in entries},
            by_path={entry.path: entry for entry in entries},
            by_name={entry.name: entry for entry in entries},
        )

    def __getitem__(self, key: str) -> ProfessionEntry:
        if key in self.by_id:
            return self.by_id[key]
        if key in self.by_path:
            return self.by_path[key]
        return self.by_name[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.by_id)

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, key: object) -> bool:
        return key in self.by_id or key in self.by_path or key in self.by_name


def extract_professions(
    profession_paths: Sequence[str],
    trade_professions: Iterable[str],
) -> ProfessionIndex:
    """Extract villager professions whose trade name is known to the trade index.

    Filters out `none` and `nitwit` (neither has trades in the trade index).
    """
    trade_set = set(trade_professions)
    entries: list[ProfessionEntry] = []
    for raw_path in profession_paths:
        path = raw_path.removeprefix(f"{NAMESPACE}:")
        display_name = _profession_display_name(path)
        if display_name in trade_set:
            entry = ProfessionEntry(
                id=f"{NAMESPACE}:{path}",
                path=path,
                name=display_name,
                page_title=display_name,
                trade_name=display_name,
            )
            entries.append(entry)

    entries.sort(key=lambda e: e.id)
    return ProfessionIndex.build(entries)
