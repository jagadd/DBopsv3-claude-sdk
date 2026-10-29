import asyncio
import uuid

from .approvals import ApprovalBroker
from .config import Settings
from .itsm import ItsmClient
from .models import Ticket
from .runner import TicketRunner
from .store import Store


class TicketService:
    def __init__(self, settings: Settings, store: Store, broker: ApprovalBroker, itsm: ItsmClient):
        self._settings = settings
        self._store = store
        self._broker = broker
        self._itsm = itsm
        self._tasks: set[asyncio.Task] = set()

    def start(self, ticket: Ticket) -> str | None:
        """Start a run in the background. Returns the run id, or None if the ticket already has an active run."""
        run_id = uuid.uuid4().hex
        if not self._store.start_run(run_id, ticket.number, ticket.model_dump()):
            return None
        runner = TicketRunner(ticket, run_id, self._settings, self._store, self._broker, self._itsm)
        task = asyncio.create_task(runner.run(), name=f"run-{ticket.number}-{run_id[:8]}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run_id

    async def shutdown(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
