from typing import Any, AsyncIterator, Dict, List, Optional
import importlib
from bson import ObjectId


def _get_default_collection():
    """Obtain the default Mongo collection used by the application.

    This function tries to access a `database` attribute on the `app.database`
    module (keeps backwards compatibility with code that injects a global
    database object). If no default is available an informative RuntimeError
    is raised and callers are expected to pass an explicit collection for
    easier testing and dependency injection.
    """
    try:
        db_mod = importlib.import_module("app.database")
        database_obj = getattr(db_mod, "database", None)
        if database_obj is None:
            raise RuntimeError(
                "No default database found; please pass a collection instance"
            )
        return database_obj.get_collection("entity")
    except Exception as exc:
        raise RuntimeError(
            "Unable to obtain default collection; please pass a collection instance"
        ) from exc


async def ensure_entity_indexes(collection: Optional[Any] = None) -> None:
    """Ensure indexes required by the entity collection.

    Creates a unique index on the `name` field which enforces uniqueness
    at the database level and avoids race conditions when creating entities.
    """
    coll = collection or _get_default_collection()
    # Idempotent - creating an index with the same specification is fine.
    await coll.create_index("name", unique=True, name="unique_entity_name_idx")


async def add_entity(entity_data: Dict[str, Any], collection: Optional[Any] = None) -> Dict[str, Any]:
    """Insert a new entity and return the stored entity as a plain dict.

    The returned dict uses stringified `_id` and surfaces an optimistic
    concurrency `_version` field. If the caller supplies a collection it
    will be used (helps testing); otherwise the function will attempt to
    use the application's default collection.
    """
    coll = collection or _get_default_collection()

    # Avoid mutating caller's dict
    to_insert = dict(entity_data)
    to_insert.setdefault("_version", 1)

    result = await coll.insert_one(to_insert)
    return await get_entity(str(result.inserted_id), collection=coll)


async def get_entity(id: str, collection: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a single entity by id and return a plain dict with
    predictable payload (stringified _id and _version present).
    """
    coll = collection or _get_default_collection()
    entity = await coll.find_one({"_id": ObjectId(id)})
    if not entity:
        return None

    entity["_id"] = str(entity["_id"])  # make payload size predictable
    entity.setdefault("_version", 1)
    return entity


async def list_entities(collection: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Return all entities as a list of plain dicts.

    This helper converts ObjectId to string and ensures an explicit
    `_version` field is present for optimistic concurrency tracking.
    """
    coll = collection or _get_default_collection()
    cursor = coll.find()

    entities: List[Dict[str, Any]] = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"]) if doc.get("_id") is not None else None
        doc.setdefault("_version", 1)
        entities.append(doc)

    return entities


async def edit_entity(
    entity_id: str,
    entity_data: Dict[str, Any],
    collection: Optional[Any] = None,
    expected_version: Optional[int] = None,
) -> None:
    """Update an entity with optimistic concurrency support.

    If `expected_version` is provided the update will only succeed when the
    stored document's `_version` matches that value; in that case a version
    mismatch results in a RuntimeError. When omitted the function behaves
    like the legacy implementation but still increments `_version`.
    """
    coll = collection or _get_default_collection()

    filter_doc: Dict[str, Any] = {"_id": ObjectId(entity_id)}
    if expected_version is not None:
        filter_doc["_version"] = expected_version

    update_doc = {"$set": entity_data, "$inc": {"_version": 1}}

    result = await coll.update_one(filter_doc, update_doc)

    if expected_version is not None and result.matched_count == 0:
        # Nothing matched: either not found or version conflict
        raise RuntimeError("Optimistic concurrency failed: version mismatch or not found")


async def delete_entity(entity_id: str, collection: Optional[Any] = None) -> None:
    """Delete an entity by id."""
    coll = collection or _get_default_collection()
    await coll.delete_one({"_id": ObjectId(entity_id)})


async def stream_synonyms(collection: Optional[Any] = None, batch_size: int = 1000) -> AsyncIterator[Dict[str, Any]]:
    """Stream synonyms as individual mapping items.

    This async generator yields dicts of the shape:
        {"synonym": <synonym>, "value": <canonical_value>, "entity_id": <id>}

    Using a cursor with a configurable batch size avoids loading all entities
    into memory for large exports.
    """
    coll = collection or _get_default_collection()
    cursor = coll.find({}, {"entity_values": 1}).batch_size(batch_size)

    async for doc in cursor:
        entity_id = str(doc.get("_id")) if doc.get("_id") is not None else None
        for ev in doc.get("entity_values", []):
            value = ev.get("value")
            for syn in ev.get("synonyms", []):
                yield {"synonym": syn, "value": value, "entity_id": entity_id}


async def list_synonyms(collection: Optional[Any] = None) -> Dict[str, str]:
    """List all synonyms across entities as a plain dict mapping synonym->value.

    For large datasets prefer `stream_synonyms` to avoid high memory usage.
    """
    synonyms: Dict[str, str] = {}

    async for item in stream_synonyms(collection=collection):
        synonyms[item["synonym"]] = item["value"]

    return synonyms


async def bulk_import_entities(entities: List[Dict[str, Any]], collection: Optional[Any] = None) -> List[str]:
    """Bulk import entities; returns list of created entity ids as strings.

    On upsert the `_version` will be set to 1 for newly created documents.
    """
    coll = collection or _get_default_collection()

    created_entities: List[str] = []
    if not entities:
        return created_entities

    for entity in entities:
        filter_doc = {"name": entity.get("name")}
        update_doc = {"$set": entity, "$setOnInsert": {"_version": 1}}
        result = await coll.update_one(filter_doc, update_doc, upsert=True)
        if getattr(result, "upserted_id", None):
            created_entities.append(str(result.upserted_id))

    return created_entities