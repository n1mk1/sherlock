# Feedback: Nebius Token Factory, NVIDIA Nemotron, Nebius hosting

Running notes, written the moment something happens (Implementation Plan §1) and finalized on Oct 29 for the feedback field (§7).

Each entry covers: what we used it for · what worked · the problem, with steps to reproduce and its effect on the build · a concrete, buildable suggestion and who it would help.

## Token Factory

_No entries yet._

## Nemotron models

### Nemotron 3 Ultra (`large`)

_No entries yet._

### Nemotron 3 Super (`medium`)

_No entries yet._

### Nemotron 3 Nano (`small`)

_No entries yet._

### NVIDIA embedding model (`embed`)

_No entries yet._

## Nebius hosting (Serverless Endpoint / AI Cloud VM)

_No entries yet._

## Tooling notes from the build

- 2026-10-24 · Scaffold: Starlette's TestClient now warns that it is deprecated with `httpx` and asks for `httpx2`, so the API's dev dependencies use `httpx2`. This isn't a Nebius issue; it's kept here so the build log is complete.
