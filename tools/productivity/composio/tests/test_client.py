from client import ComposioClient


class _FakeTools:
    def __init__(self) -> None:
        self.get_calls: list[tuple] = []
        self.execute_calls: list[tuple] = []
        self.search_results: list[dict] = []

    def get(self, *args, **kwargs):
        self.get_calls.append((args, kwargs))
        return self.search_results

    def execute(self, *args, **kwargs):
        self.execute_calls.append((args, kwargs))
        return {"successful": True, "data": {"ok": True}}


class _FakeComposio:
    def __init__(self) -> None:
        self.tools = _FakeTools()


def _client() -> tuple[ComposioClient, _FakeComposio]:
    client = ComposioClient(api_key="test-key")
    fake = _FakeComposio()
    client._composio = fake
    return client, fake


def test_list_tools_blocks_github_before_sdk_call() -> None:
    client, fake = _client()

    result = client.list_tools("  GitHub  ")

    assert result["successful"] is False
    assert "dedicated GitHub integration" in result["error"]
    assert fake.tools.get_calls == []


def test_search_tools_filters_github_actions_but_keeps_other_toolkits() -> None:
    client, fake = _client()
    fake.tools.search_results = [
        {"function": {"name": "GITHUB_CREATE_ISSUE", "description": "Create an issue"}},
        {"function": {"name": "SLACK_SEND_MESSAGE", "description": "Send a message"}},
    ]

    result = client.search_tools("send or create")

    assert result["count"] == 1
    assert result["tools"][0]["name"] == "SLACK_SEND_MESSAGE"
    assert len(fake.tools.get_calls) == 1


def test_get_tool_schema_blocks_github_before_sdk_call() -> None:
    client, fake = _client()

    result = client.get_tool_schema("github_create_issue")

    assert result["successful"] is False
    assert fake.tools.get_calls == []


def test_execute_blocks_github_before_sdk_call() -> None:
    client, fake = _client()

    result = client.execute(" GITHUB_CREATE_ISSUE ", {"title": "test"})

    assert result["successful"] is False
    assert fake.tools.execute_calls == []


def test_execute_allows_non_github_action() -> None:
    client, fake = _client()

    result = client.execute("SLACK_SEND_MESSAGE", {"text": "hello"})

    assert result == {"successful": True, "error": None, "data": {"ok": True}}
    assert len(fake.tools.execute_calls) == 1
