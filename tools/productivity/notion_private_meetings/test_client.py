from __future__ import annotations

import tomllib
from pathlib import Path

import httpx
from typer.testing import CliRunner

from notion_private_meetings import cli
from notion_private_meetings.client import NotionPrivateMeetingsClient


def test_tool_exposes_only_private_meeting_methods_and_distinct_secret():
    metadata = tomllib.loads(Path(__file__).with_name("pyproject.toml").read_text())
    assert metadata["project"]["name"] == "notion-private-meetings"
    assert metadata["tool"]["centaur"]["secrets"][0]["name"] == (
        "NOTION_PRIVATE_MEETINGS_API_KEY"
    )
    public_methods = {
        name
        for name in dir(NotionPrivateMeetingsClient)
        if not name.startswith("_")
    }
    assert public_methods == {"create_page", "query_database"}
    assert metadata["project"]["scripts"]["notion-private-meetings"] == (
        "centaur_tool_notion_private_meetings.cli:app"
    )


def test_cli_exposes_only_purpose_bound_operations():
    result = CliRunner().invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "query-database" in result.stdout
    assert "create-page" in result.stdout


def test_query_and_create_use_only_bounded_notion_endpoints():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"results": []})

    client = NotionPrivateMeetingsClient.__new__(NotionPrivateMeetingsClient)
    client._http = httpx.Client(
        base_url="https://api.notion.com/v1",
        transport=httpx.MockTransport(handler),
    )

    client.query_database("private-db", page_size=10)
    client.create_page({"database_id": "private-db"}, {"Meeting": {"title": []}})

    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v1/databases/private-db/query"),
        ("POST", "/v1/pages"),
    ]
