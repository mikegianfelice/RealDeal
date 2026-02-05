"""RapidAPI Redfin Canada API connector.

Uses redfin-canada.p.rapidapi.com (Apidojo).
Endpoints: properties/auto-complete (get regionId), properties/search-sale (listings).
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx

from ..models import Listing
from .base import ConnectorResult, ListingConnector


# Same Ontario cities as Realtor connector - search by area
CITY_NAMES = [
    "Windsor", "Sarnia", "Chatham-Kent", "Sudbury", "North Bay", "Thunder Bay",
    "Timmins", "Sault Ste. Marie", "Cornwall", "Welland", "St. Catharines",
    "Niagara Falls", "Brantford", "Peterborough", "Belleville", "Kingston",
    "London", "Oshawa", "Hamilton", "Elliot Lake", "Kapuskasing", "Cochrane",
    "Pembroke", "Owen Sound", "Stratford", "Leamington", "Amherstburg",
    "Kincardine", "Walkerton", "Hanover", "Port Elgin", "Southampton",
]


# Redfin propertyType numeric -> string (common values)
PROPERTY_TYPE_MAP = {
    6: "Single Family",
    7: "Condo",
    8: "Townhouse",
    9: "Multi-Family",
    10: "Land",
    11: "Mobile",
    12: "Rental",
}


class RapidAPIRedfinConnector(ListingConnector):
    """
    Connector for RapidAPI Redfin Canada API (Apidojo).
    https://rapidapi.com/apidojo/api/redfin-canada

    Uses auto-complete to get regionId by city, then search-sale for listings.
    """

    def __init__(
        self,
        api_key: str | None = None,
        host: str = "redfin-canada.p.rapidapi.com",
        delay_seconds: float = 2.0,
        min_price: float = 20000,
    ) -> None:
        self.api_key = api_key or os.environ.get("RAPIDAPI_KEY", "")
        self.host = host
        self.base_url = f"https://{host}"
        self.delay_seconds = delay_seconds
        self.min_price = min_price

    @property
    def source_name(self) -> str:
        return "rapidapi_redfin"

    def fetch(
        self,
        cities: list[str],
        max_price: float,
        province: str = "ON",
    ) -> ConnectorResult:
        """Fetch listings from Redfin Canada API."""
        if not self.api_key:
            return ConnectorResult(
                listings=[],
                raw_payloads=[],
                source=self.source_name,
                errors=["RAPIDAPI_KEY not set. Set env var or pass api_key."],
            )

        all_listings: list[Listing] = []
        all_raw: list[dict] = []
        errors: list[str] = []
        seen_ids: set[str] = set()

        for i, city in enumerate(cities):
            if i > 0:
                time.sleep(self.delay_seconds)
            try:
                result = self._fetch_city(city, max_price, province, seen_ids)
                for lst in result.listings:
                    if lst.id not in seen_ids:
                        seen_ids.add(lst.id)
                        all_listings.append(lst)
                all_raw.extend(result.raw_payloads)
                errors.extend(result.errors)
            except Exception as e:
                errors.append(f"{city}: {e!s}")

        return ConnectorResult(
            listings=all_listings,
            raw_payloads=all_raw,
            source=self.source_name,
            errors=errors,
        )

    def _get_region_id(self, city: str, province: str) -> str | None:
        """Get regionId from auto-complete for city/area."""
        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": self.host,
        }
        query = f"{city}, {province}" if province else city
        resp = httpx.get(
            f"{self.base_url}/properties/auto-complete",
            params={"query": query},
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        rows = (data.get("data") or [{}])[0].get("rows", []) if data.get("data") else []
        province_upper = (province or "").upper()
        city_lower = (city or "").lower()
        for row in rows:
            rid = row.get("id")
            if not rid:
                continue
            name = str(row.get("name", "")).lower()
            sub = str(row.get("subName", "")).upper()
            if city_lower in name and (not province_upper or province_upper in sub or "ON" in sub):
                return rid
        return rows[0].get("id") if rows else None

    def _fetch_city(
        self,
        city: str,
        max_price: float,
        province: str,
        seen_ids: set[str],
    ) -> ConnectorResult:
        """Fetch listings for a single city via auto-complete + search-sale."""
        region_id = self._get_region_id(city, province)
        if not region_id:
            return ConnectorResult(
                listings=[],
                raw_payloads=[],
                source=self.source_name,
                errors=[f"{city}: Could not get regionId from auto-complete"],
            )

        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": self.host,
        }
        resp = httpx.get(
            f"{self.base_url}/properties/search-sale",
            params={"regionId": region_id},
            headers=headers,
            timeout=60,
        )

        if resp.status_code != 200:
            return ConnectorResult(
                listings=[],
                raw_payloads=[],
                source=self.source_name,
                errors=[f"{city}: HTTP {resp.status_code}"],
            )

        data = resp.json()
        listings: list[Listing] = []
        raw_list: list[dict] = []

        items = data.get("data") or []
        if not isinstance(items, list):
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            raw_list.append(item)
            try:
                listing = self._item_to_listing(item, city)
                if listing and listing.id not in seen_ids:
                    if self.min_price <= listing.price <= max_price:
                        listings.append(listing)
            except Exception:
                continue

        return ConnectorResult(
            listings=listings,
            raw_payloads=raw_list,
            source=self.source_name,
            errors=[],
        )

    def _parse_price(self, val: Any) -> float:
        """Parse price from various formats."""
        if val is None:
            return 0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        s = re.sub(r"[^\d.]", "", s)
        try:
            return float(s) if s else 0
        except ValueError:
            return 0

    def _item_to_listing(self, item: dict[str, Any], default_city: str) -> Listing | None:
        """Convert Redfin item to Listing. Expects item with homeData."""
        hd = item.get("homeData") or item
        if not isinstance(hd, dict):
            return None

        lid = str(hd.get("mlsId") or hd.get("listingId") or hd.get("propertyId") or "")
        if not lid:
            lid = str(hash(str(item)))[:16]

        price_info = hd.get("priceInfo") or {}
        hp = price_info.get("homePrice") or {}
        price = self._parse_price(
            price_info.get("amount")
            or hp.get("int64Value")
            or hp.get("amount")
        )
        if price <= 0 or price < self.min_price:
            return None

        addr_info = hd.get("addressInfo") or {}
        address = str(addr_info.get("formattedStreetLine") or addr_info.get("streetLine") or "").strip()
        if not address:
            city_part = str(addr_info.get("city") or addr_info.get("location") or default_city)
            address = f"{city_part} ({lid})" if city_part else f"Listing {lid}"
        city = str(addr_info.get("city") or addr_info.get("location") or default_city)
        province = str(addr_info.get("state") or "ON")
        postal = str(addr_info.get("zip") or addr_info.get("postalCode") or "")

        beds = int(hd.get("beds") or 1)
        bath_info = hd.get("bathInfo") or {}
        baths = float(bath_info.get("computedTotalBaths") or hd.get("baths") or 1)

        ptype_num = hd.get("propertyType")
        ptype = PROPERTY_TYPE_MAP.get(ptype_num, "Residential") if ptype_num is not None else "Residential"

        url_path = str(hd.get("url") or "")
        url = f"https://www.redfin.ca{url_path}" if url_path.startswith("/") else url_path or ""

        desc = str(hd.get("publicRemarks") or hd.get("remarks") or hd.get("description") or "")

        return Listing(
            id=lid,
            source=self.source_name,
            address=address,
            city=city,
            province=province,
            postal_code=postal,
            price=price,
            bedrooms=max(1, beds),
            bathrooms=baths,
            property_type=ptype,
            description=desc,
            url=url,
            raw_payload=item,
        )
