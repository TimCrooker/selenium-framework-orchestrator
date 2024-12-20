from typing import Any, Optional
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
import httpx

from bson.objectid import ObjectId
from pymongo.errors import PyMongoError

from app.models import CreateBot, SerializedBot, SerializedRun, UpdateBot, UpdateRun
from app.services.agent_service import find_available_agent
from app.services.run_service import serialize_run, update_run
from app.database import bots_collection, runs_collection
from app.utils.socket_manager import sio

def serialize_bot(bot: dict[str, Any]) -> SerializedBot:
    return SerializedBot(**bot)

async def create_bot(data: CreateBot) -> Optional[SerializedBot]:
    try:
        payload = data.dict()
        result = await bots_collection.insert_one(payload)
        bot = await bots_collection.find_one({"_id": result.inserted_id})

        if not bot:
            raise Exception("Error creating bot")

        serialized_bot = serialize_bot(bot)
        await emit_bot_created(serialized_bot)
        return serialized_bot
    except Exception as e:
        print(f"Error creating bot: {e}")
        return None

async def get_bot_by_id(bot_id: str) -> SerializedBot:
    bot = await bots_collection.find_one({"_id": ObjectId(bot_id)})
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return serialize_bot(bot)

async def list_bots() -> list[SerializedBot]:
    bots_cursor = bots_collection.find()
    bots = await bots_cursor.to_list(length=None)
    return [serialize_bot(bot) for bot in bots]

async def update_bot(bot_id: str, bot_data: UpdateBot) -> Optional[SerializedBot]:
    try:
        payload = bot_data.dict(exclude_unset=True)
        await bots_collection.update_one({"_id": ObjectId(bot_id)}, {"$set": payload})
        bot = await bots_collection.find_one({"_id": ObjectId(bot_id)})

        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")

        serialized_bot = serialize_bot(bot)
        await emit_bot_updated(serialized_bot)
        return serialized_bot
    except Exception as e:
        print(f"Error updating bot: {e}")
        return None

async def delete_bot(bot_id: str) -> bool:
    try:
        result = await bots_collection.delete_one({"_id": ObjectId(bot_id)})
        if result.deleted_count > 0:
            await emit_bot_deleted(bot_id)
            return True
        else:
            print(f"Bot {bot_id} not found for deletion")
            return False
    except PyMongoError as e:
        print(f"Error deleting bot {bot_id}: {e}")
        return False

async def start_bot_run(bot_id: str, run_id: str) -> bool:
    bot = await bots_collection.find_one({"_id": ObjectId(bot_id)})
    if not bot:
        print(f"Bot {bot_id} not found")
        return False

    bot_script = bot.get("script")

    # find an available agent
    agent = await find_available_agent()
    if not agent:
        print(f"No available agent to run bot {bot_id}")
        return False

    agent_public_url = agent.public_url
    if not agent_public_url:
        return False

    agent_id = agent.agent_id

    payload = {
        "bot_id": bot_id,
        "bot_script": bot_script,
        "run_id": run_id
    }

    # Assign the run to the agent (it may not take it right away)
    await update_run(run_id, UpdateRun(agent_id=agent_id))

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{agent_public_url}/run", json=payload)
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            print(f"HTTP error {e.response.status_code} while starting bot on agent {agent_id}: {e.response.text}")
            return False
        except httpx.RequestError as e:
            print(f"Failed to start bot on agent {agent_id}: {e}")
            return False

async def get_bot_runs(bot_id: str) -> list[SerializedRun]:
    runs_cursor = runs_collection.find({"bot_id": bot_id})
    runs = await runs_cursor.to_list(length=None)
    return [serialize_run(run) for run in runs]

# EVENT EMITTERS

async def emit_bot_created(bot: SerializedBot) -> None:
    data = jsonable_encoder(bot)
    await sio.emit('bot_created', data, namespace='/ui')

async def emit_bot_deleted(bot_id: str) -> None:
    await sio.emit('bot_deleted', {"bot_id": bot_id}, namespace='/ui')

async def emit_bot_updated(bot: SerializedBot) -> None:
    data = jsonable_encoder(bot)
    await sio.emit('bot_updated', data, namespace='/ui')

