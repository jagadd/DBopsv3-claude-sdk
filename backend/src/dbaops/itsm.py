import asyncio
from typing import Any

import httpx

from .config import Settings
from .models import TicketState, WorkNote

ATTEMPTS = 3


class ItsmClient:
    """Posts work notes and state changes back to the ITSM-mimic frontend."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        headers = {}
        if settings.itsm_token:
            headers["Authorization"] = f"Bearer {settings.itsm_token.get_secret_value()}"
        self._client = client or httpx.AsyncClient(base_url=settings.itsm_base_url, headers=headers, timeout=30)

    async def _send(self, method: str, path: str, body: dict[str, Any]) -> None:
        # Retries transport failures only (e.g. a pooled keep-alive connection the server just closed).
        for attempt in range(1, ATTEMPTS + 1):
            try:
                resp = await self._client.request(method, path, json=body)
                break
            except httpx.TransportError:
                if attempt == ATTEMPTS:
                    raise
                await asyncio.sleep(0.2 * attempt)
        resp.raise_for_status()

    async def post_work_note(self, note: WorkNote) -> None:
        await self._send("POST", f"/api/incidents/{note.ticket_number}/work_notes", note.model_dump(mode="json"))

    async def set_state(self, ticket_number: str, state: TicketState) -> None:
        await self._send("PATCH", f"/api/incidents/{ticket_number}", {"state": state.value})

    async def aclose(self) -> None:
        await self._client.aclose()
