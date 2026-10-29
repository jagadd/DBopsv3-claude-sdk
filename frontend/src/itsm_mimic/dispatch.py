"""Pipeline stand-in: pushes incidents assigned to DBAopsv3 to the DBAops backend."""

from . import backend, db
from .config import Settings

TICKET_FIELDS = (
    "number",
    "short_description",
    "description",
    "configuration_item",
    "assignment_group",
    "priority",
    "category",
)


async def dispatch_incident(number: str, settings: Settings) -> None:
    incident = db.get_incident(settings.itsm_db_path, number)
    if incident is None:
        return
    try:
        result = await backend.submit_ticket(settings, {field: incident[field] for field in TICKET_FIELDS})
        text = f"Ticket dispatched to the DBAopsv3 agent (run {result['run_id'][:8]})."
    except backend.BackendError as exc:
        text = f"Dispatch to DBAopsv3 failed: {exc}"
    db.add_work_note(settings.itsm_db_path, number, "system", "Integration", text)
