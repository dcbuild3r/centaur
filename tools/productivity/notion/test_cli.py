from __future__ import annotations

import json

import httpx
from typer.testing import CliRunner

from notion import cli
from notion.cli import extract_id
from notion.client import NotionClient

ADDRESS_BOOK_VIEW_URL = (
    "https://app.notion.com/p/worldcoinfoundation/"
    "554a958e3a6740b7ac355b6b5339b83d"
    "?v=35bc09d5041e4729841a09d4a2bca79c&source=copy_link"
)


def test_extract_id_supports_app_notion_view_urls() -> None:
    assert extract_id(ADDRESS_BOOK_VIEW_URL) == (
        "554a958e-3a67-40b7-ac35-5b6b5339b83d"
    )


def test_extract_id_normalizes_bare_notion_ids() -> None:
    assert extract_id("554a958e3a6740b7ac355b6b5339b83d") == (
        "554a958e-3a67-40b7-ac35-5b6b5339b83d"
    )


def test_page_or_database_falls_back_for_a_database_share_link() -> None:
    object_id = "554a958e-3a67-40b7-ac35-5b6b5339b83d"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == f"/v1/pages/{object_id}":
            return httpx.Response(
                400,
                json={
                    "code": "validation_error",
                    "message": "Provided ID is a database, not a page.",
                },
            )
        if request.url.path == f"/v1/databases/{object_id}":
            return httpx.Response(
                200,
                json={"object": "database", "id": object_id, "title": []},
            )
        return httpx.Response(404)

    client = NotionClient.__new__(NotionClient)
    client._http = httpx.Client(
        base_url="https://api.notion.com/v1",
        transport=httpx.MockTransport(handler),
    )

    result = client.page_or_database(object_id)

    assert result["object"] == "database"
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", f"/v1/pages/{object_id}"),
        ("GET", f"/v1/databases/{object_id}"),
    ]


def test_page_command_queries_rows_when_a_share_link_targets_a_database(monkeypatch) -> None:
    object_id = "554a958e-3a67-40b7-ac35-5b6b5339b83d"

    class StubClient:
        def page_or_database(self, value: str) -> dict:
            assert value == object_id
            return {"object": "database", "id": object_id, "title": []}

        def get_all_pages(self, value: str) -> list[dict]:
            assert value == object_id
            return [{"id": "address-book-row"}]

    monkeypatch.setattr(cli, "get_client", lambda: StubClient())

    result = CliRunner().invoke(
        cli.app,
        ["page", ADDRESS_BOOK_VIEW_URL, "--content", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["_content"] == [{"id": "address-book-row"}]
