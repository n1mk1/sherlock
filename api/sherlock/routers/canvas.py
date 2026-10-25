"""The Flow canvas (TRD §4.7): read it with its etag, save it with the etag it was read at."""

import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from sherlock.canvas import service as canvas
from sherlock.db.connection import get_db
from sherlock.ownership import owned_dataset

router = APIRouter(tags=["canvas"])


class CanvasPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canvas: dict
    etag: str


@router.get("/datasets/{dataset_id}/canvas")
def get_canvas(dataset: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)) -> dict:
    doc, etag = canvas.read(db, dataset["id"])
    return {"canvas": doc, "etag": etag}


@router.put("/datasets/{dataset_id}/canvas")
def put_canvas(body: CanvasPut, request: Request, dataset: sqlite3.Row = Depends(owned_dataset),
               db: sqlite3.Connection = Depends(get_db)) -> dict:
    return {"etag": canvas.write(db, request.app.state.bus, dataset, body.canvas, body.etag)}
