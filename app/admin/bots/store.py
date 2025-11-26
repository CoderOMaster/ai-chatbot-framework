from typing import Any, AsyncIterator, Dict, List, Optional

from app.admin.bots.schemas import Bot, NLUConfiguration
from app.admin.entities.store import EntityRepository, get_default_repository as get_default_entity_repository
from app.admin.intents.store import IntentRepository, MongoIntentRepository
from app.database import get_collection


class BotRepository:
    """Repository managing bot configuration while composing intent and entity repositories.

    This repository depends on abstract IntentRepository and EntityRepository
    interfaces and a collection-like object for bot documents. This allows the
    admin service and other consumers (e.g. dialogue-manager) to inject test
    doubles or alternative storage backends.
    """

    def __init__(
        self,
        collection: Any,
        intent_repo: IntentRepository,
        entity_repo: EntityRepository,
    ) -> None:
        self.collection = collection
        self.intent_repo = intent_repo
        self.entity_repo = entity_repo

    async def get_bot(self, name: str) -> Bot:
        """Return the Bot with the given name.

        Raises whatever the underlying collection raises if the document is
        missing or malformed.
        """
        bot = await self.collection.find_one({"name": name})
        return Bot.model_validate(bot)

    async def get_nlu_config(self, name: str) -> NLUConfiguration:
        """Return the NLU configuration for the named bot."""
        bot = await self.get_bot(name)
        return bot.nlu_config

    async def update_nlu_config(self, name: str, nlu_config: dict) -> None:
        """Update the NLU configuration for the named bot."""
        await self.collection.update_one({"name": name}, {"$set": {"nlu_config": nlu_config}})

    async def export_bot(self, name: str) -> Dict[str, List[Dict[str, Any]]]:
        """Export intents and entities for the given bot.

        This convenience method is kept for backwards compatibility and will
        aggregate intents and entities into a single dictionary. For large
        datasets prefer using export_bot_stream which yields items incrementally.
        """
        intents = await self.intent_repo.list_intents()
        entities = await self.entity_repo.list_entities()

        entities_out = [entity.model_dump(exclude={"id"}) for entity in entities]
        intents_out = [
            intent.model_dump(exclude={"id": True, "parameters": {"__all__": {"id"}}})
            for intent in intents
        ]

        return {"intents": intents_out, "entities": entities_out}

    async def export_bot_stream(self, name: str) -> AsyncIterator[Dict[str, Any]]:
        """Stream exported items for large datasets.

        Yields dicts with shape {"type": "intent"|"entity", "item": {...}} so
        callers can process or serialize items incrementally.
        """
        # Stream entities first
        entities = await self.entity_repo.list_entities()
        for entity in entities:
            yield {"type": "entity", "item": entity.model_dump(exclude={"id"})}

        # Then intents
        intents = await self.intent_repo.list_intents()
        for intent in intents:
            yield {
                "type": "intent",
                "item": intent.model_dump(exclude={"id": True, "parameters": {"__all__": {"id"}}}),
            }

    async def import_bot(self, name: str, data: Dict[str, Any]) -> Dict[str, int]:
        """Import intents and entities from an in-memory payload.

        Returns a summary of how many records were created.
        """
        intents = data.get("intents", [])
        entities = data.get("entities", [])

        created_intents = await self.intent_repo.bulk_import_intents(intents)
        created_entities = await self.entity_repo.bulk_import_entities(entities)

        return {
            "num_intents_created": len(created_intents),
            "num_entities_created": len(created_entities),
        }

    async def import_bot_stream(self, name: str, items: AsyncIterator[Dict[str, Any]]) -> Dict[str, int]:
        """Stream-import items where each yielded dict has {'type': 'intent'|'entity', 'item': {...}}.

        This allows importing very large exports without holding the entire
        payload in memory. The implementation buffers per-type lists and calls
        the underlying bulk import methods once per type.
        """
        intent_batch: List[Dict[str, Any]] = []
        entity_batch: List[Dict[str, Any]] = []

        async for entry in items:
            t = entry.get("type")
            it = entry.get("item")
            if t == "intent":
                intent_batch.append(it)
            elif t == "entity":
                entity_batch.append(it)

        created_intents = await self.intent_repo.bulk_import_intents(intent_batch)
        created_entities = await self.entity_repo.bulk_import_entities(entity_batch)

        return {
            "num_intents_created": len(created_intents),
            "num_entities_created": len(created_entities),
        }


# Backwards-compatible default repository factory and module-level helpers
_default_repo: Optional[BotRepository] = None


def get_default_repository() -> BotRepository:
    """Return a BotRepository composed of default (Mongo-backed) sub-repositories.

    This keeps backwards compatibility for callers that import module-level
    functions; prefer constructing BotRepository explicitly and injecting
    repositories in new code.
    """
    global _default_repo
    if _default_repo is not None:
        return _default_repo

    bot_collection = get_collection("bot")

    # Construct default sub-repositories. The concrete MongoIntentRepository is
    # used here only for a convenient default; application code should inject
    # abstract IntentRepository and EntityRepository implementations.
    intent_repo = MongoIntentRepository(get_collection("intent"))
    entity_repo = get_default_entity_repository()

    _default_repo = BotRepository(bot_collection, intent_repo, entity_repo)
    return _default_repo


# Module-level convenience functions for backward compatibility
async def get_bot(name: str) -> Bot:
    return await get_default_repository().get_bot(name)


async def get_nlu_config(name: str) -> NLUConfiguration:
    return await get_default_repository().get_nlu_config(name)


async def update_nlu_config(name: str, nlu_config: dict) -> None:
    await get_default_repository().update_nlu_config(name, nlu_config)


async def export_bot(name: str) -> Dict[str, List[Dict[str, Any]]]:
    return await get_default_repository().export_bot(name)


async def import_bot(name: str, data: Dict[str, Any]) -> Dict[str, int]:
    return await get_default_repository().import_bot(name, data)