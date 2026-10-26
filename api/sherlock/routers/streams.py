"""Server-sent events (TRD §5): `GET /datasets/{id}/events` and the user-level `GET /events`.

On connect the stream subscribes to the bus first, then reads the newest event id and replays from
`job_events` everything after `Last-Event-ID` up to it (the header a reconnecting `EventSource` sends,
or the `last_event_id` query parameter for a first connection). Then an `id:` line alone with that
newest id, so a browser that reconnects before any event arrives still asks for what it missed. Then
live events, skipping any the replay already sent. A comment line every 15 s keeps proxies from
closing an idle stream.
"""

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from sherlock.db.connection import connect
from sherlock.db.users import User
from sherlock.identity import current_user
from sherlock.jobs.events import USER_STREAM_TYPES, Event, newest_id, replay_dataset, replay_user
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
    replay: Callable[[sqlite3.Connection, int, int], list[Event]],
    last_id: int | None,
) -> AsyncIterator[str]:
    bus = request.app.state.bus
    settings = request.app.state.settings
    sub = bus.subscribe(match)
    try:
        yield "retry: 3000\n\n"

        def read() -> tuple[int, list[Event]]:
            db = connect(settings)
            try:
                newest = newest_id(db)  # after subscribing: anything later reaches the queue
                return newest, (replay(db, last_id, newest) if last_id is not None else [])
            finally:
                db.close()

        newest, events = await asyncio.to_thread(read)
        for event in events:
            yield event.sse()
        yield f"id: {newest}\n\n"  # dispatches nothing, but a reconnect now sends Last-Event-ID
        # After a replay, an event at or below `newest` was in it (it was written before the read);
        # without one, everything the queue holds is new to this stream.
        replayed = newest if last_id is not None else 0
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
        lambda db, after, upto: replay_dataset(db, dataset_id, after, upto),
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
        lambda db, after, upto: replay_user(db, user_id, after, upto),
        _last_id(request, last_event_id),
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers=HEADERS)
