"""Minimal Notion client for private meeting publication only."""

from __future__ import annotations

from typing import Any

import httpx

from centaur_sdk import secret

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionPrivateMeetingsClient:
    """Expose only the two Notion mutations needed by the meeting workflow."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or secret("NOTION_PRIVATE_MEETINGS_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("NOTION_PRIVATE_MEETINGS_API_KEY not set")
        self._http = httpx.Client(
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
            },
            timeout=30.0,
        )

    def query_database(
        self,
        database_id: str,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"page_size": page_size}
        if filter:
            body["filter"] = filter
        if sorts:
            body["sorts"] = sorts
        if start_cursor:
            body["start_cursor"] = start_cursor
        response = self._http.post(f"/databases/{database_id}/query", json=body)
        response.raise_for_status()
        return response.json()

    def create_page(
        self,
        parent: dict[str, Any],
        properties: dict[str, Any],
        children: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"parent": parent, "properties": properties}
        if children:
            body["children"] = children
        response = self._http.post("/pages", json=body)
        response.raise_for_status()
        return response.json()


def _client() -> NotionPrivateMeetingsClient:
    return NotionPrivateMeetingsClient(
        api_key=secret("NOTION_PRIVATE_MEETINGS_API_KEY", "")
    )
