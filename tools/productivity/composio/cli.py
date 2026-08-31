"""CLI for executing non-GitHub tools via Composio."""

from dotenv import load_dotenv

load_dotenv()

import json
import typer

app = typer.Typer(
    name="composio",
    help="Execute non-GitHub tools from services such as Gmail, Slack, and Notion via Composio",
)


@app.callback()
def main() -> None:
    """composio CLI."""


@app.command("health")
def health():
    """Assert composio connectivity and auth with a safe read-only check."""
    from .client import _client

    client = _client()
    try:
        details = client.list_tools("hackernews")
        payload = {"ok": True, "tool": "composio", "error": None, "details": details}
    except Exception as exc:
        payload = {"ok": False, "tool": "composio", "error": str(exc), "details": {}}
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        raise typer.Exit(1) from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    app()
