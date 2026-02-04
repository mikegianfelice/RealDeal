"""Base connector interface for listing sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Listing


@dataclass
class ConnectorResult:
    """Result of a connector fetch operation."""

    listings: list[Listing]
    raw_payloads: list[dict]
    source: str
    errors: list[str]


class ListingConnector(ABC):
    """
    Abstract interface for listing data sources.
    Implementations: RapidAPI Realtor, Apify HouseSigma, etc.
    """

    @abstractmethod
    def fetch(
        self,
        cities: list[str],
        max_price: float,
        province: str = "ON",
    ) -> ConnectorResult:
        """
        Fetch listings for given cities and constraints.
        Returns normalized listings + raw payloads for debugging.
        """
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Identifier for this data source."""
        ...
