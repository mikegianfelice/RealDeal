"""RapidAPI Realtor.ca Scraper API connector.

Uses realtor-ca-scraper-api.p.rapidapi.com (baqo271).
Endpoints: /parseUrl, /properties/search, /properties/details
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx

from ..models import Listing
from .base import ConnectorResult, ListingConnector
from .city_coords import get_city_coords


class RapidAPIRealtorConnector(ListingConnector):
    """
    Connector for RapidAPI Realtor.ca Scraper API (baqo271).
    https://rapidapi.com/baqo271/api/realtor-ca-scraper-api

    Uses /properties/search with searchQuery for listings.
    """

    def __init__(
        self,
        api_key: str | None = None,
        host: str = "realtor-ca-scraper-api.p.rapidapi.com",
        delay_seconds: float = 2.0,
        min_price: float = 20000,
        property_type_group_id: str = "1",
        bounding_box_delta: float = 0.15,
        zoom_level: str = "10",
    ) -> None:
        self.api_key = api_key or os.environ.get("RAPIDAPI_KEY", "")
        self.host = host
        self.base_url = f"https://{host}"
        self.delay_seconds = delay_seconds
        self.min_price = min_price
        self.property_type_group_id = property_type_group_id
        self.bounding_box_delta = bounding_box_delta
        self.zoom_level = zoom_level

    @property
    def source_name(self) -> str:
        return "rapidapi_realtor"

    def fetch(
        self,
        cities: list[str],
        max_price: float,
        province: str = "ON",
    ) -> ConnectorResult:
        """Fetch listings from RapidAPI Realtor.ca Scraper."""
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

        with httpx.Client(timeout=60) as client:
            for i, city in enumerate(cities):
                if i > 0:
                    time.sleep(self.delay_seconds)
                try:
                    result = self._fetch_city(city, max_price, province, client)
                    all_listings.extend(result.listings)
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

    def _build_search_query(self, city: str, max_price: float, province: str) -> dict[str, Any]:
        """Build searchQuery for /properties/search endpoint."""
        lat, lng = get_city_coords(city)
        delta = self.bounding_box_delta
        query: dict[str, Any] = {
            "ZoomLevel": self.zoom_level,
            "Center": f"{lat},{lng}",
            "LatitudeMax": str(lat + delta),
            "LongitudeMax": str(lng + delta),
            "LatitudeMin": str(lat - delta),
            "LongitudeMin": str(lng - delta),
            "Sort": "6-D",
            "Currency": "CAD",
            "PriceMin": str(int(self.min_price)),
            "PriceMax": str(int(max_price)),
        }
        if self.property_type_group_id:
            query["PropertyTypeGroupID"] = self.property_type_group_id
        return query

    def _fetch_city(
        self,
        city: str,
        max_price: float,
        province: str,
        client: httpx.Client,
    ) -> ConnectorResult:
        """Fetch listings for a single city via /properties/search."""
        search_query = self._build_search_query(city, max_price, province)
        headers = {
            "Content-Type": "application/json",
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": self.host,
        }
        payload = {"SearchQuery": search_query}

        resp = client.post(
            f"{self.base_url}/properties/search",
            json=payload,
            headers=headers,
        )

        if resp.status_code != 200:
            return ConnectorResult(
                listings=[],
                raw_payloads=[],
                source=self.source_name,
                errors=[f"{city}: HTTP {resp.status_code}"],
            )

        data = resp.json()
        listings, raw_list = self._normalize_response(data, city, province or "ON")
        return ConnectorResult(
            listings=listings,
            raw_payloads=raw_list,
            source=self.source_name,
            errors=[],
        )

    def _normalize_response(
        self, data: Any, city: str, expected_province: str = "ON"
    ) -> tuple[list[Listing], list[dict]]:
        """Normalize API response to Listing schema. Response is array of listings."""
        listings: list[Listing] = []
        raw_list: list[dict] = []

        items = data if isinstance(data, list) else []
        if isinstance(data, dict):
            items = data.get("Results") or data.get("Result") or data.get("data") or data.get("listings") or []

        if not isinstance(items, list):
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            raw_list.append(item)
            try:
                listing = self._item_to_listing(item, city, expected_province=expected_province)
                if listing:
                    listings.append(listing)
            except Exception:
                continue

        return listings, raw_list

    def _parse_price(self, val: Any) -> float:
        """Parse price from various formats: 550000, '$550,000', '$2,600/Monthly'."""
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

    def _item_to_listing(
        self, item: dict[str, Any], default_city: str, expected_province: str = "ON"
    ) -> Listing | None:
        """Convert API item to Listing. Excludes US listings and Land/vacant lots."""
        lid = str(
            item.get("MslNumber")
            or item.get("MlsNumber")
            or item.get("Id")
            or item.get("id")
            or item.get("ListingId")
            or ""
        )
        if not lid:
            lid = str(hash(str(item)))[:16]

        price = self._parse_price(
            item.get("PriceUnformatted")
            or item.get("Price")
            or item.get("price")
            or item.get("ListPrice")
        )
        if price <= 0 or price < self.min_price:
            return None

        addr_raw = item.get("Address") or item.get("address") or item.get("UnparsedAddress") or ""
        addr_parts = str(addr_raw).split("|")
        address = addr_parts[0].strip() if addr_parts else "Unknown"
        city = default_city
        if len(addr_parts) > 1:
            loc = addr_parts[1].strip()
            city_match = re.search(r"^([^,]+)", loc)
            if city_match:
                city = city_match.group(1).strip()
        city = str(item.get("City") or item.get("city") or city)
        prov = str(item.get("Province") or item.get("province") or item.get("ProvinceCode") or "ON")
        if prov.upper() != (expected_province or "ON").upper():
            return None  # Exclude US / other-province listings

        postal = str(item.get("PostalCode") or item.get("postal_code") or item.get("PostalCode1") or "")
        beds = int(item.get("Bedrooms") or item.get("bedrooms") or item.get("BedsTotal") or item.get("BedroomsTotal") or 1)
        baths = float(item.get("Bathrooms") or item.get("bathrooms") or item.get("BathTotal") or item.get("BathroomTotal") or 1)
        ptype = str(item.get("PropertyType") or item.get("property_type") or item.get("PropertyTypeName") or "Residential")
        ptype_lower = ptype.lower()
        addr_lower = str(addr_raw).lower()
        if any(x in ptype_lower or x in addr_lower for x in ("land", "lot", "vacant", "parking")):
            return None  # Exclude lots and parking
        desc = str(item.get("Description") or item.get("description") or item.get("PublicRemarks") or item.get("PublicRemarksEn") or "")
        url = str(item.get("URL") or item.get("url") or item.get("PermaLink") or item.get("RelativeURL") or "")
        if url and not url.startswith("http"):
            url = f"https://www.realtor.ca{url}" if url.startswith("/") else f"https://www.realtor.ca/{url}"

        lease_rent = item.get("LeaseRent", "")
        if lease_rent and not desc:
            desc = f"Rent: {lease_rent}"

        return Listing(
            id=lid,
            source=self.source_name,
            address=address,
            city=city,
            province=prov,
            postal_code=postal,
            price=price,
            bedrooms=beds,
            bathrooms=baths,
            property_type=ptype,
            description=desc,
            url=url,
            raw_payload=item,
        )
