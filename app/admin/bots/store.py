from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.admin.bots.schemas import Bot, NLUConfiguration
from app.admin.entities.store import list_entities, bulk_import_entities
from app.admin.intents.store import IntentRepository


def _get_default_database() -> Any:
    """Obtain the application's default AsyncIOMotorDatabase instance.

    This mirrors the pattern used in other store modules and avoids importing
    app.database at module import time in a way that causes side-effects. Callers
    may pass explicit collection objects to functions for testing.
    """
    try:
        db_mod = importlib.import_module("app.database")
        database_obj = getattr(db_mod, "database", None)
        if database_obj is None:
            raise RuntimeError("No default database found; please pass explicit collections")
        return database_obj
    except Exception as exc:
        raise RuntimeError("Unable to obtain default database; please pass explicit collections") from exc


async def ensure_bot_indexes(bot_collection: Optional[Any] = None) -> None:
    """Ensure indexes required by the bot collection (idempotent).

    Creates a unique index on the `name` field to enforce uniqueness at the
    database level and avoid race conditions when creating bots.

    Args:
        bot_collection: Optional Motor collection to use. When omitted the
            application's default collection is used.
    """
    coll = bot_collection or _get_default_database().get_collection("bot")
    await coll.create_index("name", unique=True, name="unique_bot_name_idx")


async def ensure_default_bot(bot_collection: Optional[Any] = None) -> Dict[str, Any]:
    """Ensure a bot named "default" exists and return its serialized document.

    The function is safe to call from application start-up code but is not
    executed on import. It returns a plain dict (serialized Pydantic model)
    to avoid double-validation by higher layers.
    """
    coll = bot_collection or _get_default_database().get_collection("bot")

    default_bot = await coll.find_one({"name": "default"})
    if default_bot is None:
        now = datetime.utcnow()
        default_bot_obj = Bot(name="default")
        default_bot_obj.created_at = now
        default_bot_obj.updated_at = now
        await coll.insert_one(default_bot_obj.model_dump(by_alias=True, exclude={"id"}))
        # Return a serialized representation compatible with the rest of the app
        return default_bot_obj.model_dump(by_alias=True)

    # Validate/normalise the stored document using the Pydantic model then
    # return a plain dict to minimise re-validation by callers.
    bot_obj = Bot.model_validate(default_bot)
    return bot_obj.model_dump(by_alias=True)


async def get_bot(name: str, bot_collection: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a bot by name and return a serialized dict.

    Returns None if no bot with the given name exists.
    """
    coll = bot_collection or _get_default_database().get_collection("bot")
    bot_doc = await coll.find_one({"name": name})
    if bot_doc is None:
        return None
    bot_obj = Bot.model_validate(bot_doc)
    return bot_obj.model_dump(by_alias=True)


async def get_nlu_config(name: str, bot_collection: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Return the NLU configuration for the named bot as a plain dict.

    Returns None if the bot does not exist.
    """
    bot = await get_bot(name, bot_collection=bot_collection)
    if bot is None:
        return None
    # NLUConfiguration is nested; normalise via Pydantic and return serialized form
    nlu = NLUConfiguration.model_validate(bot.get("nlu_config", {}))
    return nlu.model_dump()


async def update_nlu_config(name: str, nlu_config: Dict[str, Any], bot_collection: Optional[Any] = None) -> None:
    """Update the NLU configuration for a bot and touch updated_at."""
    coll = bot_collection or _get_default_database().get_collection("bot")
    await coll.update_one(
        {"name": name}, {"$set": {"nlu_config": nlu_config, "updated_at": datetime.utcnow()}}
    )


async def export_bot(name: str, *,
                     bot_collection: Optional[Any] = None,
                     intent_collection: Optional[Any] = None,
                     entity_collection: Optional[Any] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Export intents and entities for a bot.

    Historically this exported all intents and entities; the `name` argument is
    kept for compatibility but not currently used to scope the export. The
    function returns plain serialised DTOs to avoid double validation.
    """
    # Obtain collections (allow callers to inject alternate collections for tests)
    db = _get_default_database()
    bot_coll = bot_collection or db.get_collection("bot")
    intent_coll = intent_collection or db.get_collection("intent")
    entity_coll = entity_collection or db.get_collection("entity")

    intent_repo = IntentRepository(intent_coll)

    intents = await intent_repo.list_intents()
    entities = await list_entities(collection=entity_coll)

    # The intent repository and entities store already return plain dicts / DTOs.
    return {"intents": intents, "entities": entities}


async def import_bot(name: str, data: Dict[str, Any], *,
                     bot_collection: Optional[Any] = None,
                     intent_collection: Optional[Any] = None,
                     entity_collection: Optional[Any] = None) -> Dict[str, int]:
    """Import intents and entities for a bot atomically when possible.

    Performs bulk upserts for intents and entities inside a MongoDB
    transaction if the underlying client supports sessions. Returns counts of
    created documents.
    """
    db = _get_default_database()
    bot_coll = bot_collection or db.get_collection("bot")
    intent_coll = intent_collection or db.get_collection("intent")
    entity_coll = entity_collection or db.get_collection("entity")

    intent_repo = IntentRepository(intent_coll)

    intents = data.get("intents", [])
    entities = data.get("entities", [])

    created_intents: List[str] = []
    created_entities: List[str] = []

    # Attempt to run both imports inside a transaction when possible
    client = getattr(db, "client", None) or getattr(db, "_client", None)
    if client is not None:
        # Motor clients expose start_session as an async context manager
        async with client.start_session() as session:
            async with session.start_transaction():
                created_intents = await intent_repo.bulk_import_intents(intents)
                created_entities = await bulk_import_entities(entities, collection=entity_coll)
    else:
        # Fallback: perform non-transactional imports
        created_intents = await intent_repo.bulk_import_intents(intents)
        created_entities = await bulk_import_entities(entities, collection=entity_coll)

    return {
        "num_intents_created": len(created_intents),
        "num_entities_created": len(created_entities),
    }