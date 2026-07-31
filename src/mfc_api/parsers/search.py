"""Parser for item search results."""

from __future__ import annotations

from ..models import SearchResults
from .base import Parser


class SearchParser(Parser):
    def __init__(self, html: str, *, query: str, url=None) -> None:
        super().__init__(html, url=url)
        self.query = query

    def parse(self) -> SearchResults:
        return SearchResults(
            query=self.query,
            items=self.item_summaries(),
            pagination=self.pagination(),
        )
