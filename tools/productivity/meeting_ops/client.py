"""Narrow client for the approved Meeting Ops Apps Script functions."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

import httplib2
import socks
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from centaur_sdk import secret

SCRIPT_ID_SECRET = "MEETING_OPS_SCRIPT_ID"


class MeetingOpsError(RuntimeError):
    """Raised when Apps Script rejects or fails a worker invocation."""


def _build_http() -> httplib2.Http:
    """Build an HTTP client that routes through the sandbox's iron-proxy."""

    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")  # noqa: TID251
    proxy_info = None
    if proxy_url:
        parts = urlsplit(proxy_url)
        proxy_info = httplib2.ProxyInfo(
            proxy_type=socks.PROXY_TYPE_HTTP,
            proxy_host=parts.hostname,
            proxy_port=parts.port or 8080,
        )
    ca_certs = os.environ.get("SSL_CERT_FILE") or os.environ.get(  # noqa: TID251
        "REQUESTS_CA_BUNDLE"
    )
    return httplib2.Http(proxy_info=proxy_info, ca_certs=ca_certs)


def get_script_service():
    """Return the Apps Script Execution API client with proxy-supplied auth."""

    return build("script", "v1", http=_build_http())


def _script_id(explicit: str | None) -> str:
    value = explicit if explicit is not None else secret(SCRIPT_ID_SECRET)
    value = value.strip()
    if not value:
        raise MeetingOpsError(f"Missing {SCRIPT_ID_SECRET}")
    return value


def _execution_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if not isinstance(error, dict):
        return "Apps Script execution failed"
    details = error.get("details")
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, dict) and detail.get("errorMessage"):
                return str(detail["errorMessage"])
    return str(error.get("message") or "Apps Script execution failed")


def _run_function(
    function: str,
    parameters: list[Any] | None = None,
) -> Any:
    body: dict[str, Any] = {"function": function, "devMode": False}
    if parameters is not None:
        body["parameters"] = parameters

    try:
        payload = get_script_service().scripts().run(scriptId=_script_id(None), body=body).execute()
    except HttpError as error:
        status = getattr(error.resp, "status", None)
        suffix = f" (HTTP {status})" if status is not None else ""
        raise MeetingOpsError(f"Google Apps Script request failed{suffix}") from None
    if payload.get("error"):
        raise MeetingOpsError(_execution_message(payload))
    response = payload.get("response")
    if not isinstance(response, dict):
        return None
    return response.get("result")


def run_cadence(
    cadence_id: str,
    *,
    now: str | None = None,
) -> dict[str, Any] | None:
    """Create the agenda for one approved cadence occurrence."""

    request: dict[str, str] = {"cadenceId": cadence_id}
    if now:
        request["now"] = now
    result = _run_function("runCadenceJob", [request])
    if result is not None and not isinstance(result, dict):
        raise MeetingOpsError("runCadenceJob returned an unexpected result")
    return result


def pending_notifications() -> list[dict[str, Any]]:
    """Return notifications that Orbie has not yet delivered and acknowledged."""

    result = _run_function("getPendingOrbieNotifications")
    if result is None:
        return []
    if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
        raise MeetingOpsError("getPendingOrbieNotifications returned an unexpected result")
    return result


def acknowledge_notification(
    notification_id: str,
) -> dict[str, Any]:
    """Remove an outbox item after Orbie has confirmed Slack delivery."""

    result = _run_function(
        "acknowledgeOrbieNotification",
        [notification_id],
    )
    if not isinstance(result, dict):
        raise MeetingOpsError("acknowledgeOrbieNotification returned an unexpected result")
    return result
