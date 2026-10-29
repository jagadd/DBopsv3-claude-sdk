import httpx

from dbaops.itsm import ItsmClient
from dbaops.models import WorkNote, WorkNoteKind


async def test_retries_dropped_connection(settings):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(201)

    client = httpx.AsyncClient(base_url="http://itsm.test", transport=httpx.MockTransport(handler))
    itsm = ItsmClient(settings, client)
    await itsm.post_work_note(WorkNote(ticket_number="INC0010001", kind=WorkNoteKind.PROGRESS, text="x"))
    assert len(calls) == 2
