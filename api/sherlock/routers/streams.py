"""Server-sent events (TRD §5): `GET /datasets/{id}/events` and the user-level `GET /events`.

On connect the stream subscribes to the bus first, then replays from `job_events` everything after
`Last-Event-ID` (the header a reconnecting `EventSource` sends, or the `last_event_id` query
parameter for a first connection), then streams live events, skipping any the replay already
sent. A comment line every 15 s keeps proxies from closing an idle stream.
"""

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from sherlock.db.connection import connect
from sherlock.db.users import User
from sherlock.identity import current_user
from sherlock.jobs.events import USER_STREAM_TYPES, Event, replay_dataset, replay_user
from sherlock.ownership import owned_dataset

router = APIRouter(tags=["events"])
HEARTBEAT_S = 15.0
HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _last_id(request: Request, query: int | None) -> int | None:
    header = request.headers.get("last-event-id")
    if header is not None:
        try:
            return max(int(header.strip()), 0)
        except ValueError:
            return None
    return query


async def _stream(
    request: Request,
    match: Callable[[Event], bool],
    replay: Callable[[sqlite3.Connection, int], list[Event]],
    last_id: int | None,
) -> AsyncIterator[str]:
    bus = request.app.state.bus
    settings = request.app.state.settings
    sub = bus.subscribe(match)
    try:
        yield "retry: 3000\n\n"
        replayed = 0
        if last_id is not None:

            def read() -> list[Event]:
                db = connect(settings)
                try:
                    return replay(db, last_id)
                finally:
                    db.close()

            for event in await asyncio.to_thread(read):
                yield event.sse()
                replayed = event.id
        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), HEARTBEAT_S)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if event.id <= replayed:
                continue  # committed before the replay read, so already sent
            yield event.sse()
    finally:
        bus.unsubscribe(sub)


@router.get("/datasets/{dataset_id}/events")
async def dataset_events(
    request: Request,
    last_event_id: int | None = Query(default=None, ge=0),
    dataset: sqlite3.Row = Depends(owned_dataset),
) -> StreamingResponse:
    dataset_id = dataset["id"]
    stream = _stream(
        request,
        lambda e: e.dataset_id == dataset_id,
        lambda db, after: replay_dataset(db, dataset_id, after),
        _last_id(request, last_event_id),
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers=HEADERS)


@router.get("/events")
async def user_events(
    request: Request,
    last_event_id: int | None = Query(default=None, ge=0),
    user: User = Depends(current_user),
) -> StreamingResponse:
    user_id = user.id
    stream = _stream(
        request,
        lambda e: e.user_id == user_id and e.type in USER_STREAM_TYPES,
        lambda db, after: replay_user(db, user_id, after),
        _last_id(request, last_event_id),
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers=HEADERS)
