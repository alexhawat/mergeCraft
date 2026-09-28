"""Page through a GitHub list endpoint that answers with a bare JSON array.

Issue comments and pull-request reviews come back as a plain array, at most
100 rows per page, with a short page marking the end. ``utils.github``'s
paginator walks object payloads keyed by an item list, so it does not fit these
endpoints; the MCP tools page here instead and say when they stopped early.

Exports:
    ListPages: The rows collected and whether the page cap cut the listing.
    collect_list_pages: Fetch pages until a short page or the page cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.utils.github import GITHUB_LIST_MAX_PAGES, GITHUB_LIST_PAGE_SIZE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass(slots=True)
class ListPages:
    """Rows from every page fetched, and whether more pages were left unread.

    Attributes:
        rows: Rows in the order GitHub returned them, page after page.
        incomplete: ``True`` only when the page cap stopped the listing while
            the last page read was still full.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    incomplete: bool = False


async def collect_list_pages(
    fetch_page: Callable[[dict[str, Any]], Awaitable[Any]],
    *,
    label: str,
) -> ListPages:
    """Fetch ``page``/``per_page=100`` pages until a short page or the page cap.

    A full page is not proof of the end, so the next page is requested; an
    empty or short page ends the listing. After ``GITHUB_LIST_MAX_PAGES`` full
    pages the listing stops and is reported ``incomplete``.

    Args:
        fetch_page: Called with the query params for one page; returns that
            page's rows.
        label: What is being listed, for the truncation log line.

    Returns:
        The collected rows and the truncation flag.
    """
    listing = ListPages()
    for page in range(1, GITHUB_LIST_MAX_PAGES + 1):
        raw = list(await fetch_page({"per_page": GITHUB_LIST_PAGE_SIZE, "page": page}) or [])
        listing.rows.extend(row for row in raw if isinstance(row, dict))
        if len(raw) < GITHUB_LIST_PAGE_SIZE:
            return listing
    listing.incomplete = True
    logger.warning(
        "{} listing stopped at the {}-page cap ({} rows); later rows were not read",
        label,
        GITHUB_LIST_MAX_PAGES,
        len(listing.rows),
    )
    return listing


__all__ = ["ListPages", "collect_list_pages"]
