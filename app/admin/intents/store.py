"""Intent store module with versioning, validation, and advanced querying capabilities."""
from typing import List, Dict, Optional, Any
from datetime import datetime
from bson import ObjectId
from app.admin.intents.schemas import Intent
from app.database import database

intent_collection = database.get_collection("intent")
intent_history_collection = database.get_collection("intent_history")


class IntentValidationError(Exception):
    """Raised when intent data validation fails."""
    pass


class IntentNotFoundError(Exception):
    """Raised when intent is not found."""
    pass


class IntentVersionError(Exception):
    """Raised when versioning operation fails."""
    pass


async def _validate_intent_data(intent_data: dict) -> None:
    """Validate intent data before storage.

    Args:
        intent_data: Intent data to validate

    Raises:
        IntentValidationError: If validation fails
    """
    required_fields = {"name", "intentId", "speechResponse"}
    missing_fields = required_fields - set(intent_data.keys())
    if missing_fields:
        raise IntentValidationError(f"Missing required fields: {missing_fields}")

    if not isinstance(intent_data.get("name"), str) or not intent_data["name"].strip():
        raise IntentValidationError("Intent name must be a non-empty string")

    if not isinstance(intent_data.get("intentId"), str) or not intent_data["intentId"].strip():
        raise IntentValidationError("Intent ID must be a non-empty string")

    if not isinstance(intent_data.get("speechResponse"), str) or not intent_data["speechResponse"].strip():
        raise IntentValidationError("Speech response must be a non-empty string")

    if "parameters" in intent_data and not isinstance(intent_data["parameters"], list):
        raise IntentValidationError("Parameters must be a list")

    if "labeledSentences" in intent_data and not isinstance(intent_data["labeledSentences"], list):
        raise IntentValidationError("Labeled sentences must be a list")


async def _create_version(intent_id: str, intent_data: dict, action: str) -> str:
    """Create a version record for intent history tracking.

    Args:
        intent_id: ID of the intent
        intent_data: Intent data being versioned
        action: Action performed (create, update, delete)

    Returns:
        Version ID as string
    """
    version_record = {
        "intent_id": ObjectId(intent_id),
        "action": action,
        "data": intent_data,
        "timestamp": datetime.utcnow(),
        "version_number": await _get_next_version_number(intent_id),
    }
    result = await intent_history_collection.insert_one(version_record)
    return str(result.inserted_id)


async def _get_next_version_number(intent_id: str) -> int:
    """Get the next version number for an intent.

    Args:
        intent_id: ID of the intent

    Returns:
        Next version number
    """
    latest = await intent_history_collection.find_one(
        {"intent_id": ObjectId(intent_id)},
        sort=[("version_number", -1)]
    )
    return (latest["version_number"] + 1) if latest else 1


async def add_intent(intent_data: dict) -> Intent:
    """Add a new intent with validation and versioning.

    Args:
        intent_data: Intent data to add

    Returns:
        Created Intent object

    Raises:
        IntentValidationError: If intent data is invalid
    """
    await _validate_intent_data(intent_data)
    intent_data["created_at"] = datetime.utcnow()
    intent_data["updated_at"] = datetime.utcnow()
    intent_data["version"] = 1

    result = await intent_collection.insert_one(intent_data)
    intent_id = str(result.inserted_id)

    await _create_version(intent_id, intent_data, "create")
    return await get_intent(intent_id)


async def get_intent(id: str) -> Intent:
    """Retrieve an intent by ID.

    Args:
        id: Intent ID

    Returns:
        Intent object

    Raises:
        IntentNotFoundError: If intent is not found
    """
    try:
        intent = await intent_collection.find_one({"_id": ObjectId(id)})
    except Exception as e:
        raise IntentNotFoundError(f"Invalid intent ID format: {id}") from e

    if not intent:
        raise IntentNotFoundError(f"Intent with ID {id} not found")

    return Intent.model_validate(intent)


async def list_intents(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> tuple[List[Intent], int]:
    """List intents with pagination, search, and filtering.

    Args:
        skip: Number of intents to skip
        limit: Maximum number of intents to return
        search: Search term for intent name or intentId
        filters: Additional filters to apply

    Returns:
        Tuple of (list of Intent objects, total count)
    """
    query = {}

    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"intentId": {"$regex": search, "$options": "i"}},
        ]

    if filters:
        for key, value in filters.items():
            if key in {"userDefined", "apiTrigger"}:
                query[key] = value
            elif key == "created_after":
                query["created_at"] = {"$gte": value}
            elif key == "created_before":
                query["created_at"] = {"$lte": value}

    total_count = await intent_collection.count_documents(query)
    intents = await intent_collection.find(query).skip(skip).limit(limit).to_list()

    return [Intent.model_validate(intent) for intent in intents], total_count


async def edit_intent(intent_id: str, intent_data: dict) -> Intent:
    """Update an intent with validation and versioning.

    Args:
        intent_id: ID of the intent to update
        intent_data: Updated intent data

    Returns:
        Updated Intent object

    Raises:
        IntentValidationError: If intent data is invalid
        IntentNotFoundError: If intent is not found
    """
    await _validate_intent_data(intent_data)

    existing_intent = await get_intent(intent_id)
    intent_data["updated_at"] = datetime.utcnow()
    intent_data["version"] = existing_intent.version + 1 if hasattr(existing_intent, "version") else 2

    result = await intent_collection.update_one(
        {"_id": ObjectId(intent_id)},
        {"$set": intent_data}
    )

    if result.matched_count == 0:
        raise IntentNotFoundError(f"Intent with ID {intent_id} not found")

    await _create_version(intent_id, intent_data, "update")
    return await get_intent(intent_id)


async def delete_intent(intent_id: str) -> None:
    """Delete an intent with versioning.

    Args:
        intent_id: ID of the intent to delete

    Raises:
        IntentNotFoundError: If intent is not found
    """
    existing_intent = await get_intent(intent_id)
    result = await intent_collection.delete_one({"_id": ObjectId(intent_id)})

    if result.deleted_count == 0:
        raise IntentNotFoundError(f"Intent with ID {intent_id} not found")

    await _create_version(intent_id, existing_intent.model_dump(), "delete")


async def bulk_import_intents(intents: List[Dict], batch_size: int = 100) -> Dict[str, Any]:
    """Import multiple intents with batching and validation.

    Args:
        intents: List of intent data to import
        batch_size: Number of intents to process per batch

    Returns:
        Dictionary with import statistics including created, updated, and failed counts

    Raises:
        IntentValidationError: If any intent data is invalid
    """
    if not intents:
        return {"created": [], "updated": [], "failed": [], "total": 0}

    created_intents = []
    updated_intents = []
    failed_intents = []

    for i in range(0, len(intents), batch_size):
        batch = intents[i : i + batch_size]

        for intent in batch:
            try:
                await _validate_intent_data(intent)
                intent["updated_at"] = datetime.utcnow()

                result = await intent_collection.update_one(
                    {"name": intent.get("name")},
                    {"$set": intent},
                    upsert=True
                )

                if result.upserted_id:
                    created_intents.append(str(result.upserted_id))
                    await _create_version(str(result.upserted_id), intent, "create")
                elif result.modified_count > 0:
                    updated_intents.append(intent.get("name"))
                    await _create_version(str(result.upserted_id or intent.get("_id")), intent, "update")

            except IntentValidationError as e:
                failed_intents.append({"intent": intent.get("name"), "error": str(e)})

    return {
        "created": created_intents,
        "updated": updated_intents,
        "failed": failed_intents,
        "total": len(intents),
    }


async def get_intent_history(intent_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve version history for an intent.

    Args:
        intent_id: ID of the intent
        limit: Maximum number of history records to return

    Returns:
        List of version history records
    """
    history = await intent_history_collection.find(
        {"intent_id": ObjectId(intent_id)}
    ).sort("timestamp", -1).limit(limit).to_list()

    return history


async def rollback_intent(intent_id: str, version_number: int) -> Intent:
    """Rollback an intent to a previous version.

    Args:
        intent_id: ID of the intent
        version_number: Version number to rollback to

    Returns:
        Restored Intent object

    Raises:
        IntentVersionError: If version is not found
        IntentNotFoundError: If intent is not found
    """
    version_record = await intent_history_collection.find_one({
        "intent_id": ObjectId(intent_id),
        "version_number": version_number,
    })

    if not version_record:
        raise IntentVersionError(
            f"Version {version_number} not found for intent {intent_id}"
        )

    restored_data = version_record["data"]
    restored_data["updated_at"] = datetime.utcnow()
    restored_data["version"] = version_number

    result = await intent_collection.update_one(
        {"_id": ObjectId(intent_id)},
        {"$set": restored_data}
    )

    if result.matched_count == 0:
        raise IntentNotFoundError(f"Intent with ID {intent_id} not found")

    await _create_version(intent_id, restored_data, "rollback")
    return await get_intent(intent_id)


async def search_intents(
    query: str,
    search_fields: Optional[List[str]] = None,
    limit: int = 50,
) -> List[Intent]:
    """Search intents by query across specified fields.

    Args:
        query: Search query string
        search_fields: Fields to search in (default: name, intentId)
        limit: Maximum number of results to return

    Returns:
        List of matching Intent objects
    """
    if search_fields is None:
        search_fields = ["name", "intentId"]

    search_query = {
        "$or": [
            {field: {"$regex": query, "$options": "i"}} for field in search_fields
        ]
    }

    intents = await intent_collection.find(search_query).limit(limit).to_list()
    return [Intent.model_validate(intent) for intent in intents]


async def filter_intents(
    filters: Dict[str, Any],
    skip: int = 0,
    limit: int = 100,
) -> tuple[List[Intent], int]:
    """Filter intents by multiple criteria.

    Args:
        filters: Dictionary of filter criteria
        skip: Number of intents to skip
        limit: Maximum number of intents to return

    Returns:
        Tuple of (list of Intent objects, total count)
    """
    query = {}

    if "user_defined" in filters:
        query["userDefined"] = filters["user_defined"]

    if "api_trigger" in filters:
        query["apiTrigger"] = filters["api_trigger"]

    if "created_after" in filters:
        query["created_at"] = {"$gte": filters["created_after"]}

    if "created_before" in filters:
        if "created_at" in query:
            query["created_at"]["$lte"] = filters["created_before"]
        else:
            query["created_at"] = {"$lte": filters["created_before"]}

    total_count = await intent_collection.count_documents(query)
    intents = await intent_collection.find(query).skip(skip).limit(limit).to_list()

    return [Intent.model_validate(intent) for intent in intents], total_count