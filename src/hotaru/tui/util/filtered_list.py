"""Filtered list utility for autocomplete.

Provides fuzzy filtering and keyboard navigation for list selection,
similar to opencode's useFilteredList hook.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, List, Optional, TypeVar

T = TypeVar("T")


def fuzzy_match(query: str, text: str) -> float:
    """Simple fuzzy matching score.

    Args:
        query: Search query (lowercase)
        text: Text to match against

    Returns:
        Match score (0.0 to 1.0), higher is better
    """
    if not query:
        return 1.0

    text_lower = text.lower()

    # Exact match
    if query == text_lower:
        return 1.0

    # Prefix match
    if text_lower.startswith(query):
        return 0.9

    # Contains match
    if query in text_lower:
        return 0.7

    # Fuzzy character match
    query_idx = 0
    matches = 0
    consecutive = 0
    max_consecutive = 0

    for char in text_lower:
        if query_idx < len(query) and char == query[query_idx]:
            matches += 1
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
            query_idx += 1
        else:
            consecutive = 0

    if query_idx < len(query):
        return 0.0  # Not all characters matched

    # Score based on match ratio and consecutive matches
    ratio = matches / len(text)
    consecutive_bonus = max_consecutive / len(query) * 0.3
    return min(0.6 + ratio * 0.2 + consecutive_bonus, 0.85)


@dataclass
class FilteredItem(Generic[T]):
    """Item with filter score."""
    item: T
    score: float
    group: str = ""


@dataclass
class FilteredListState(Generic[T]):
    """State for filtered list."""
    items: List[T] = field(default_factory=list)
    filtered: List[FilteredItem[T]] = field(default_factory=list)
    filter_text: str = ""
    active_index: int = 0


class FilteredList(Generic[T]):
    """Filtered list with fuzzy search and keyboard navigation.

    Provides:
    - Fuzzy filtering across multiple keys
    - Grouping and sorting
    - Keyboard navigation (up/down, enter)
    - Active item tracking
    """

    def __init__(
        self,
        items: List[T],
        key: Callable[[T], str],
        filter_keys: Optional[List[str]] = None,
        group_by: Optional[Callable[[T], str]] = None,
        sort_by: Optional[Callable[[T, T], int]] = None,
        on_select: Optional[Callable[[T], None]] = None,
    ) -> None:
        """Initialize filtered list.

        Args:
            items: List of items to filter
            key: Function to get unique key from item
            filter_keys: List of attribute names to filter on
            group_by: Function to get group name from item
            sort_by: Comparison function for sorting
            on_select: Callback when item is selected
        """
        self._items = items
        self._key = key
        self._filter_keys = filter_keys or []
        self._group_by = group_by
        self._sort_by = sort_by
        self._on_select = on_select

        self._filter_text = ""
        self._filtered: List[FilteredItem[T]] = []
        self._active_index = 0

        self._update_filtered()

    @property
    def items(self) -> List[T]:
        """Get all items."""
        return self._items

    @items.setter
    def items(self, value: List[T]) -> None:
        """Set items and re-filter."""
        self._items = value
        self._update_filtered()

    @property
    def filter_text(self) -> str:
        """Get current filter text."""
        return self._filter_text

    @property
    def filtered(self) -> List[T]:
        """Get filtered items (flat list)."""
        return [f.item for f in self._filtered]

    @property
    def active_index(self) -> int:
        """Get active item index."""
        return self._active_index

    @property
    def active(self) -> Optional[T]:
        """Get active item."""
        if 0 <= self._active_index < len(self._filtered):
            return self._filtered[self._active_index].item
        return None

    @property
    def active_key(self) -> str:
        """Get active item key."""
        item = self.active
        return self._key(item) if item else ""

    def set_filter(self, text: str) -> None:
        """Set filter text and update filtered list.

        Args:
            text: Filter text
        """
        self._filter_text = text.lower()
        self._update_filtered()

    def set_active(self, key: str) -> None:
        """Set active item by key.

        Args:
            key: Item key to activate
        """
        for i, f in enumerate(self._filtered):
            if self._key(f.item) == key:
                self._active_index = i
                return

    def set_active_index(self, index: int) -> None:
        """Set active item by index.

        Args:
            index: Index to activate
        """
        if self._filtered:
            self._active_index = max(0, min(index, len(self._filtered) - 1))

    def move_up(self) -> None:
        """Move active selection up."""
        if self._filtered:
            self._active_index = (self._active_index - 1) % len(self._filtered)

    def move_down(self) -> None:
        """Move active selection down."""
        if self._filtered:
            self._active_index = (self._active_index + 1) % len(self._filtered)

    def select(self) -> Optional[T]:
        """Select the active item.

        Returns:
            Selected item or None
        """
        item = self.active
        if item and self._on_select:
            self._on_select(item)
        return item

    def reset(self) -> None:
        """Reset filter and selection."""
        self._filter_text = ""
        self._active_index = 0
        self._update_filtered()

    def _update_filtered(self) -> None:
        """Update filtered list based on current filter."""
        query = self._filter_text

        # Score and filter items
        scored: List[FilteredItem[T]] = []
        for item in self._items:
            score = self._score_item(item, query)
            if score > 0:
                group = self._group_by(item) if self._group_by else ""
                scored.append(FilteredItem(item=item, score=score, group=group))

        # Sort by score (descending), then by custom sort
        scored.sort(key=lambda x: -x.score)

        if self._sort_by:
            # Stable sort within same score
            scored.sort(key=lambda x: 0)  # Reset for stable sort
            for i in range(len(scored)):
                for j in range(i + 1, len(scored)):
                    if scored[i].score == scored[j].score:
                        if self._sort_by(scored[i].item, scored[j].item) > 0:
                            scored[i], scored[j] = scored[j], scored[i]

        self._filtered = scored

        # Reset active index if out of bounds
        if self._active_index >= len(self._filtered):
            self._active_index = 0

    def _score_item(self, item: T, query: str) -> float:
        """Score an item against the query.

        Args:
            item: Item to score
            query: Search query

        Returns:
            Match score (0.0 if no match)
        """
        if not query:
            return 1.0

        best_score = 0.0

        for key in self._filter_keys:
            value = getattr(item, key, None)
            if value is None:
                continue

            if isinstance(value, str):
                score = fuzzy_match(query, value)
                best_score = max(best_score, score)

        return best_score

    def grouped(self) -> List[tuple[str, List[T]]]:
        """Get filtered items grouped.

        Returns:
            List of (group_name, items) tuples
        """
        if not self._group_by:
            return [("", self.filtered)]

        groups: dict[str, List[T]] = {}
        for f in self._filtered:
            if f.group not in groups:
                groups[f.group] = []
            groups[f.group].append(f.item)

        return list(groups.items())
