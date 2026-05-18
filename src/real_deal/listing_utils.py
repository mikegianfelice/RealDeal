"""Shared listing helpers (deduplication, etc.)."""

from __future__ import annotations

from .models import Listing


def listing_address_key(listing: Listing) -> tuple[str, str, int]:
    """Stable key for cross-source dedup: (postal_or_address, city, price_bucket)."""
    postal = (listing.postal_code or "").replace(" ", "").upper()[:6]
    addr = " ".join((listing.address or "").lower().split())[:80]
    city = (listing.city or "").strip().lower()
    price_bucket = int(listing.price / 5000) * 5000
    return (postal if postal else addr, city, price_bucket)


def dedupe_listings(
    listings: list[Listing],
    prefer_source: str = "rapidapi_redfin",
) -> list[Listing]:
    """Dedupe by listing id, then by address key. Prefer *prefer_source* on conflicts."""
    def prefer(a: Listing, b: Listing) -> Listing:
        if a.source == prefer_source:
            return a
        if b.source == prefer_source:
            return b
        return a

    by_id: dict[str, Listing] = {}
    for lst in listings:
        if lst.id in by_id:
            by_id[lst.id] = prefer(lst, by_id[lst.id])
        else:
            by_id[lst.id] = lst

    by_addr: dict[tuple[str, str, int], Listing] = {}
    for lst in by_id.values():
        key = listing_address_key(lst)
        if key in by_addr:
            by_addr[key] = prefer(lst, by_addr[key])
        else:
            by_addr[key] = lst

    return list(by_addr.values())
