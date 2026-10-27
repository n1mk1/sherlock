"""Chat (TRD §4.9, §5.3): the thread, sending a message as an SSE stream, and an answer's receipt
(the model calls that made it).

`POST /chat` runs the agent in a worker thread and streams its events. The thread keeps going if
the client disconnects, so the answer is saved and a reload reads it from `GET /chat`.
"""

import asyncio
import json
import sqlite3

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from sherlock.agent.loop import Agent, to_message
from sherlock.db.connection import connect, get_db
from sherlock.errors import ApiError, not_found
from sherlock.jobs.events import emit as emit_event
from sherlock.llm import calls
from sherlock.llm.client import LLMClient
from sherlock.ownership import Owned, owned, owned_dataset
from sherlock.query import context as qx
from sherlock.ratelimit import llm_rate_limit

router = APIRouter(tags=["chat"])
log_event = "event: {type}\ndata: {data}\n\n"


class ChatContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tab: str = "csv"  # accepted and ignored: there is one view (TRD §8.2)
    selection_id: str | None = None
    selected_cells: dict | None = None
    plan_id: str | None = None  # the open cleaning plan: the chat can change it (`edit_plan`)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    context: ChatContext = Field(default_factory=ChatContext)
    clarification_of: str | None = None
    choice: str | None = Field(default=None, max_length=200)


def thread_changed(db: sqlite3.Connection, bus, dataset: sqlite3.Row) -> None:
    """`chat.updated` on the dataset stream: another tab open on the dataset reads its thread again
    (TRD §5.1). Sent when an answer is saved and when a proposal in the thread is decided."""
    emit_event(db, bus, dataset["id"], dataset["user_id"], "chat.updated", {})


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
    return [to_message(r, db, dataset["current_version"]) for r in reversed(rows)]


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
            env = qx.Env(app.state.settings, db, app.state.duckdb, app.state.bus)
            Agent(env, LLMClient(app.state.settings), row, emit).run(
                body.text, body.context.model_dump(), body.clarification_of, body.choice)
        except Exception as exc:  # the stream ends with an error event rather than a broken connection
            emit("error", {"code": "internal", "message": "Something went wrong answering that. Try again."})
            import logging

            logging.getLogger("sherlock.chat").exception("chat failed: %s", exc)
        finally:
            try:
                thread_changed(db, app.state.bus, dataset)  # the saved messages, for the dataset's other tabs
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


@router.get("/chat/messages/{mid}/calls", response_model=calls.Receipt)
def message_calls(owned_message: Owned = Depends(owned("message")), db: sqlite3.Connection = Depends(get_db)) -> calls.Receipt:
    """"How I worked it out": every model call (and web request) made answering this message, oldest
    first, with a total. A user's own message made none."""
    return calls.for_message(db, owned_message.id)
