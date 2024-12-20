from datetime import datetime
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.database import run_events_collection
from app.models import CreateRunEvent, SerializedRunEvent
from app.utils.socket_manager import sio

def serialize_run_event(run_event: dict[str, Any]) -> SerializedRunEvent:
    return SerializedRunEvent(**run_event)

async def create_run_event(data: CreateRunEvent) -> SerializedRunEvent:
    try:
        payload = data.dict()
        payload["timestamp"] = datetime.now()
        result = await run_events_collection.insert_one(payload)
        event = await run_events_collection.find_one({"_id": result.inserted_id})
        if not event:
            raise Exception("Error creating run event")

        serialized_run_event = serialize_run_event(event)
        await emit_run_event(serialized_run_event)
        return serialized_run_event
    except Exception as e:
        # Handle exception
        raise e

async def list_run_events(run_id: str) -> list[SerializedRunEvent]:
    try:
        events_cursor = run_events_collection.find({"run_id": run_id})
        events = await events_cursor.to_list(length=None)
        return [serialize_run_event(event) for event in events]
    except Exception as e:
        print(f"Error listing run events: {e}")
        raise e

# EVENT HANDLERS

@sio.on("run_event", namespace='/agent')
async def handle_run_event(sid: str, data: dict[str, Any]) -> None:
    try:
        event_data = CreateRunEvent(**data)
        await create_run_event(event_data)
    except Exception as e:
        print(f"Error handling run event: {e}")

# EVENT EMITTER

async def emit_run_event(run_event: SerializedRunEvent) -> None:
    data = jsonable_encoder(run_event)
    await sio.emit("run_event", data, namespace='/ui')