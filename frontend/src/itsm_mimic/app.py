import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path as FsPath
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Path, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from . import backend, db
from .config import get_settings
from .dispatch import dispatch_incident
from .models import (
    AGENT_GROUP,
    APPROVAL_ID_PATTERN,
    ASSIGNMENT_GROUPS,
    CATEGORIES,
    NUMBER_PATTERN,
    STATES,
    AgentWorkNote,
    IncidentIn,
    IncidentUpdate,
    StatePatch,
)

HERE = FsPath(__file__).parent
Number = Annotated[str, Path(pattern=NUMBER_PATTERN)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init(get_settings().itsm_db_path)
    yield


app = FastAPI(title="DBopsv3 ITSM", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
bearer = HTTPBearer()

CHOICES = {"groups": ASSIGNMENT_GROUPS, "states": STATES, "categories": CATEGORIES}


def _db() -> str:
    return get_settings().itsm_db_path


def _incident_or_404(number: str) -> dict[str, Any]:
    incident = db.get_incident(_db(), number)
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{number} not found")
    return incident


def require_agent(creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer)]) -> None:
    expected = get_settings().itsm_api_token.get_secret_value()
    if not secrets.compare_digest(creds.credentials.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API token")


def _errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]


# ---------- UI ----------


@app.get("/", response_class=HTMLResponse)
def incident_list(request: Request):
    return templates.TemplateResponse(request, "list.html", {"incidents": db.list_incidents(_db())})


@app.get("/incidents/new", response_class=HTMLResponse)
def new_incident_form(request: Request):
    return templates.TemplateResponse(request, "new.html", {**CHOICES, "form": {}, "errors": []})


@app.post("/incidents", response_class=HTMLResponse)
def create_incident(
    request: Request,
    background: BackgroundTasks,
    short_description: Annotated[str, Form()],
    configuration_item: Annotated[str, Form()],
    assignment_group: Annotated[str, Form()],
    priority: Annotated[int, Form()],
    description: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "",
):
    form = {
        "short_description": short_description,
        "description": description,
        "configuration_item": configuration_item,
        "assignment_group": assignment_group,
        "priority": priority,
        "category": category or None,
    }
    try:
        incident = IncidentIn(**form)
    except ValidationError as exc:
        ctx = {**CHOICES, "form": form, "errors": _errors(exc)}
        return templates.TemplateResponse(request, "new.html", ctx, status_code=422)

    number = db.create_incident(_db(), incident.model_dump())
    if incident.assignment_group == AGENT_GROUP:
        background.add_task(dispatch_incident, number, get_settings())
    return RedirectResponse(f"/incidents/{number}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/incidents/{number}", response_class=HTMLResponse)
def incident_detail(request: Request, number: Number):
    return templates.TemplateResponse(request, "detail.html", {**CHOICES, "incident": _incident_or_404(number)})


@app.post("/incidents/{number}")
def update_incident(
    number: Number,
    background: BackgroundTasks,
    assignment_group: Annotated[str, Form()],
    state: Annotated[str, Form()],
    priority: Annotated[int, Form()],
):
    current = _incident_or_404(number)
    try:
        update = IncidentUpdate(assignment_group=assignment_group, state=state, priority=priority)  # type: ignore[arg-type]
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _errors(exc)) from exc

    db.update_incident(_db(), number, **update.model_dump())
    if update.assignment_group == AGENT_GROUP and current["assignment_group"] != AGENT_GROUP:
        background.add_task(dispatch_incident, number, get_settings())
    return RedirectResponse(f"/incidents/{number}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/incidents/{number}/notes")
def add_manual_note(number: Number, text: Annotated[str, Form(min_length=1, max_length=20000)]):
    _incident_or_404(number)
    db.add_work_note(_db(), number, "manual", "ITSM User", text)
    return RedirectResponse(f"/incidents/{number}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/incidents/{number}/approvals/{approval_id}")
async def decide_approval(
    number: Number,
    approval_id: Annotated[str, Path(pattern=APPROVAL_ID_PATTERN)],
    decision: Annotated[Literal["approve", "deny"], Form()],
    approver: Annotated[str, Form(min_length=1, max_length=100)],
    comment: Annotated[str, Form(max_length=2000)] = "",
):
    _incident_or_404(number)
    try:
        await backend.decide_approval(get_settings(), approval_id, decision, approver, comment)
    except backend.BackendError as exc:
        db.add_work_note(_db(), number, "system", "Integration", f"Approval {approval_id} could not be recorded: {exc}")
    return RedirectResponse(f"/incidents/{number}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/incidents/{number}/trace", response_class=HTMLResponse)
async def incident_trace(request: Request, number: Number, run_id: str | None = None):
    incident = _incident_or_404(number)
    settings = get_settings()
    try:
        runs = await backend.runs(settings, number)
        selected = run_id or (runs[0]["run_id"] if runs else None)
        events = await backend.trace(settings, number, selected) if selected else []
        error = None
    except backend.BackendError as exc:
        runs, events, selected, error = [], [], None, str(exc)
    for event in events:
        event["data_json"] = json.dumps(event["data"], indent=2, default=str)
    ctx = {"incident": incident, "runs": runs, "events": events, "selected": selected, "error": error}
    return templates.TemplateResponse(request, "trace.html", ctx)


# ---------- API ----------


@app.get("/api/incidents/{number}")
def api_get_incident(number: Number) -> dict[str, Any]:
    incident = _incident_or_404(number)
    return {**incident, "work_notes": db.list_work_notes(_db(), number)}


@app.get("/api/incidents/{number}/approvals")
async def api_pending_approvals(number: Number) -> list[dict[str, Any]]:
    _incident_or_404(number)
    try:
        return await backend.pending_approvals(get_settings(), number)
    except backend.BackendError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@app.post("/api/incidents/{number}/work_notes", status_code=201, dependencies=[Depends(require_agent)])
def api_add_work_note(number: Number, note: AgentWorkNote) -> dict[str, str]:
    _incident_or_404(number)
    created = note.created_at.isoformat(timespec="seconds") if note.created_at else None
    author = f"DBopsv3 · {note.agent}" if note.agent else "DBopsv3 Agent"
    db.add_work_note(_db(), number, note.kind, author, note.text, created)
    return {"status": "created"}


@app.patch("/api/incidents/{number}", dependencies=[Depends(require_agent)])
def api_set_state(number: Number, patch: StatePatch) -> dict[str, str]:
    _incident_or_404(number)
    db.update_incident(_db(), number, state=patch.state)
    return {"status": "updated"}
