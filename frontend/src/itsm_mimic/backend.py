"""Server-side client for the DBAops backend API. The browser never sees the backend token."""

from typing import Any

import httpx

from .config import Settings


class BackendError(Exception):
    pass


async def _request(settings: Settings, method: str, path: str, **kwargs: Any) -> Any:
    headers = {"Authorization": f"Bearer {settings.dbaops_api_token.get_secret_value()}"}
    try:
        async with httpx.AsyncClient(base_url=settings.dbaops_api_url, headers=headers, timeout=15) as client:
            resp = await client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise BackendError(f"DBAops backend unreachable: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        raise BackendError(f"DBAops backend returned HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def submit_ticket(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    return await _request(settings, "POST", "/api/tickets", json=payload)


async def pending_approvals(settings: Settings, number: str) -> list[dict[str, Any]]:
    return await _request(settings, "GET", "/api/approvals", params={"ticket_number": number, "status": "pending"})


async def decide_approval(
    settings: Settings, approval_id: str, decision: str, approver: str, comment: str
) -> dict[str, Any]:
    body = {"decision": decision, "approver": approver, "comment": comment}
    return await _request(settings, "POST", f"/api/approvals/{approval_id}", json=body)


async def runs(settings: Settings, number: str) -> list[dict[str, Any]]:
    return await _request(settings, "GET", f"/api/tickets/{number}/runs")


async def trace(settings: Settings, number: str, run_id: str | None = None) -> list[dict[str, Any]]:
    params = {"run_id": run_id} if run_id else {}
    return await _request(settings, "GET", f"/api/tickets/{number}/trace", params={**params, "limit": 5000})
