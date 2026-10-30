import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .approvals import ApprovalBroker, ApprovalError
from .config import get_settings
from .itsm import ItsmClient
from .models import Approval, ApprovalDecision, ApprovalStatus, Ticket
from .service import TicketService
from .store import Store

TicketNumber = Annotated[str, Path(pattern=r"^[A-Z]{3,4}\d{4,12}$", examples=["INC0010001"])]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    store = Store(settings.dbaops_db_path)
    store.recover_after_restart()
    broker = ApprovalBroker(store)
    itsm = ItsmClient(settings)
    app.state.store = store
    app.state.broker = broker
    app.state.service = TicketService(settings, store, broker, itsm)
    yield
    await app.state.service.shutdown()
    await itsm.aclose()


app = FastAPI(
    title="DBopsv3",
    description="Coordinator + specialist subagents (Claude Agent SDK) working SQL Server tickets. "
    "Click **Authorize** and enter the DBAOPS_API_TOKEN to try the endpoints.",
    lifespan=lifespan,
)
bearer = HTTPBearer()


def require_token(creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer)]) -> None:
    expected = get_settings().dbaops_api_token.get_secret_value()
    if not secrets.compare_digest(creds.credentials.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API token")


def _store(request: Request) -> Store:
    return request.app.state.store


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/tickets",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_token)],
    tags=["tickets"],
    summary="Pipeline intake: start an agent run for a ticket",
)
async def intake(ticket: Ticket, request: Request) -> dict[str, str]:
    run_id = request.app.state.service.start(ticket)
    if run_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{ticket.number} already has an active run")
    return {"ticket": ticket.number, "run_id": run_id, "status": "accepted"}


@app.get("/api/tickets/{number}/runs", dependencies=[Depends(require_token)], tags=["trace"])
async def list_runs(number: TicketNumber, request: Request) -> list[dict[str, Any]]:
    return _store(request).list_runs(number)


@app.get(
    "/api/tickets/{number}/trace",
    dependencies=[Depends(require_token)],
    tags=["trace"],
    summary="Every logged event for a ticket: SDK messages, tool calls/results, approvals, work notes",
)
async def trace(
    number: TicketNumber,
    request: Request,
    run_id: str | None = None,
    agent: str | None = Query(default=None, examples=["coordinator", "health-performance"]),
    kind: str | None = Query(default=None, examples=["tool_call", "AssistantMessage", "work_note"]),
    after_id: int = 0,
    limit: int = Query(default=1000, le=5000),
) -> list[dict[str, Any]]:
    return _store(request).list_events(number, run_id, agent, kind, after_id, limit)


@app.get("/api/approvals", dependencies=[Depends(require_token)], tags=["approvals"])
async def list_approvals(
    request: Request,
    ticket_number: str | None = None,
    status_filter: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
) -> list[Approval]:
    return _store(request).list_approvals(ticket_number, status_filter)


@app.post("/api/approvals/{approval_id}", dependencies=[Depends(require_token)], tags=["approvals"])
async def decide_approval(approval_id: str, decision: ApprovalDecision, request: Request) -> Approval:
    broker: ApprovalBroker = request.app.state.broker
    try:
        return broker.decide(approval_id, decision.decision == "approve", decision.approver, decision.comment)
    except ApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
