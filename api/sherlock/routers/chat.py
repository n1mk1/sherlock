"""Chat (TRD §4.9, §5.3): the thread, sending a message as an SSE stream, and pinning an answer.

`POST /chat` runs the agent in a worker thread and streams its events. The thread keeps going if
the client disconnects, so the answer is saved and a reload reads it from `GET /chat`.
"""

import asyncio
import json
import sqlite3

from fastapi import APIRouter, Body, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from sherlock.agent import flow
from sherlock.agent.loop import Agent, to_message
from sherlock.db.connection import connect, get_db
from sherlock.db.users import User
from sherlock.errors import ApiError, not_found
from sherlock.identity import current_user
from sherlock.llm.client import LLMClient
from sherlock.ownership import Owned, check_dataset, owned, owned_dataset
from sherlock.ratelimit import llm_rate_limit
from sherlock.widgets import layout as wl
from sherlock.widgets import service as ws

router = APIRouter(tags=["chat"])
log_event = "event: {type}\ndata: {data}\n\n"


class ChatContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tab: str = "dashboard"
    global_filter: dict | None = None
    selection_id: str | None = None
    focused_widget_id: str | None = None
    selected_cells: dict | None = None
    selected_card_ids: list[str] | None = None
    plan_id: str | None = None  # the open cleaning plan: the chat can change it (`edit_plan`)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    context: ChatContext = Field(default_factory=ChatContext)
    clarification_of: str | None = None
    choice: str | None = Field(default=None, max_length=200)


@router.get("/datasets/{dataset_id}/chat")
def get_thread(
    before: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    """The dataset's thread, oldest first: the last `limit` messages before `before` (a message ID)."""
    params: list = [dataset["id"]]
    where = "dataset_id = ?"
    if before:
        anchor = db.execute("SELECT created_at FROM messages WHERE id = ? AND dataset_id = ?", (before, dataset["id"])).fetchone()
        if anchor is None:
            raise not_found("Message not found")
        where += " AND (created_at < ? OR (created_at = ? AND id < ?))"
        params += [anchor["created_at"], anchor["created_at"], before]
    rows = db.execute(f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ?",  # noqa: S608
                      (*params, limit)).fetchall()
    return [to_message(r, db) for r in reversed(rows)]


@router.post("/datasets/{dataset_id}/chat", dependencies=[Depends(llm_rate_limit)])
async def send(
    body: ChatRequest,
    request: Request,
    dataset: sqlite3.Row = Depends(owned_dataset),
) -> StreamingResponse:
    if dataset["status"] in ("profiling", "failed"):
        raise ApiError(409, "conflict", "Chat opens once the file is profiled.")
    app = request.app
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(type_: str, data: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (type_, data))

    def work() -> None:
        db = connect(app.state.settings)
        try:
            row = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset["id"],)).fetchone()
            env = ws.Env(app.state.settings, db, app.state.duckdb, app.state.bus)
            Agent(env, LLMClient(app.state.settings), row, emit).run(
                body.text, body.context.model_dump(), body.clarification_of, body.choice)
        except Exception as exc:  # the stream ends with an error event rather than a broken connection
            emit("error", {"code": "internal", "message": "Something went wrong answering that. Try again."})
            import logging

            logging.getLogger("sherlock.chat").exception("chat failed: %s", exc)
        finally:
            db.close()
            emit("", {})

    task = loop.run_in_executor(None, work)

    async def stream():
        while True:
            type_, data = await queue.get()
            if not type_:
                break
            yield log_event.format(type=type_, data=json.dumps(data, separators=(",", ":"), default=str))
        await task

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/messages/{mid}/pin", status_code=status.HTTP_201_CREATED)
def pin(
    request: Request,
    body: dict = Body(...),
    owned_message: Owned = Depends(owned("message")),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Pin a chart or table answer to the dashboard as a widget made by chat, or (`target: "flow"`) an
    answer's text to the canvas as an `answer` card."""
    dataset = check_dataset(db, user.id, owned_message.dataset_id)
    target = body.get("target", "dashboard")
    if target not in ("dashboard", "flow"):
        raise ApiError(422, "invalid", "target: dashboard or flow")
    row = db.execute("SELECT * FROM messages WHERE id = ?", (owned_message.id,)).fetchone()
    blocks = json.loads(row["blocks_json"])
    index = body.get("block_index")
    if target == "flow":
        if not isinstance(index, int):
            raise ApiError(422, "invalid", "block_index: no such block in this message")
        return flow.add_to_flow(db, request.app.state.bus, dataset, row, index)
    if not isinstance(index, int) or not 0 <= index < len(blocks):
        raise ApiError(422, "invalid", "block_index: no such block in this message")
    block = blocks[index]
    if block["type"] == "chart":
        spec = block["spec"]
    elif block["type"] == "table" and block.get("result"):
        focus = json.loads(row["focus_json"] or "{}")
        sources = {s.get("result"): s for s in json.loads(row["sources_json"])}
        if block["result"] not in sources or not focus.get("sql"):
            raise ApiError(422, "invalid", "This table can't be pinned.")
        spec = {"op": {"type": "sql", "sql": focus["sql"]}, "view": {"type": "table"}}
    else:
        raise ApiError(422, "invalid", "Only chart and table answers can be pinned.")
    env = ws.Env(request.app.state.settings, db, request.app.state.duckdb, request.app.state.bus)
    question = db.execute(
        "SELECT text FROM messages WHERE dataset_id = ? AND role = 'user' AND created_at <= ? ORDER BY created_at DESC LIMIT 1",
        (dataset["id"], row["created_at"]),
    ).fetchone()
    title = (question["text"][:80] if question else None)
    widget = ws.create(env, dataset, spec, title=title, created_by="chat")
    saved = wl.stored(db, dataset["id"])
    if saved is not None:
        wl.save(db, dataset["id"], wl.append(saved, widget["id"], spec["view"]["type"]))
    return ws.to_widget(widget)
