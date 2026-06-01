"""FastAPI app — single endpoint: POST /assess → text/event-stream."""

import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app import orchestrator
from app.models import CompanyQuery

app = FastAPI(title="Company Risk Assessment API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/assess")
async def assess_endpoint(query: CompanyQuery) -> EventSourceResponse:
    async def event_gen():
        async for event in orchestrator.assess(query):
            yield {"event": event.type, "data": event.model_dump_json()}

    return EventSourceResponse(event_gen())
