from __future__ import annotations

from typing import Any, Sequence

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument

from app.admin.integrations.schemas import Integration, IntegrationUpdate
from app.config import app_config
from app.database import CollectionGetter, create_collection_getter_from_config


DEFAULT_COLLECTION_NAME = "integrations"
DEFAULT_INTEGRATIONS: Sequence[dict[str, Any]] = [
    {
        "id": "facebook",
        "name": "Facebook Messenger",
        "description": "Connect with Facebook Messenger",
        "status": False,
        "settings": {
            "verify": "ai-chatbot-framework",
            "secret": "",
            "page_access_token": "",
        },
    },
    {
        "id": "chat_widget",
        "name": "Chat Widget",
        "description": "Add a chat widget to your website",
        "status": True,
        "settings": {},
    },
]


class IntegrationRepository:
    """Repository responsible for persisting integration metadata."""

    def __init__(self, collection_getter: CollectionGetter, collection_name: str = DEFAULT_COLLECTION_NAME) -> None:
        self._collection_getter = collection_getter
        self._collection_name = collection_name

    @property
    def _collection(self) -> AsyncIOMotorCollection:
        return self._collection_getter(self._collection_name)

    async def list_integrations(self) -> list[Integration]:
        """Return all persisted integrations."""
        cursor = self._collection.find()
        documents = await cursor.to_list(length=None)
        return [Integration(**document) for document in documents]

    async def get_integration(self, id: str) -> Integration | None:
        """Load a single integration by its identifier."""
        document = await self._collection.find_one({"id": id})
        if document:
            return Integration(**document)
        return None

    async def update_integration(self, id: str, integration: IntegrationUpdate) -> Integration | None:
        """Update integration data and return the refreshed document."""
        update_data = integration.model_dump(exclude_unset=True)
        if not update_data:
            return await self.get_integration(id)

        document = await self._collection.find_one_and_update(
            {"id": id},
            {"$set": update_data},
            return_document=ReturnDocument.AFTER,
        )

        if document is None:
            return None
        return Integration(**document)

    async def ensure_default_integrations(self) -> None:
        """Ensure the stock integration definitions exist in the datastore."""
        for integration in DEFAULT_INTEGRATIONS:
            await self._collection.update_one(
                {"id": integration["id"]},
                {"$setOnInsert": integration},
                upsert=True,
            )


_default_repository: IntegrationRepository = IntegrationRepository(
    create_collection_getter_from_config(app_config)
)


async def list_integrations(repository: IntegrationRepository | None = None) -> list[Integration]:
    """Return every integration via the provided repository."""
    repo = repository or _default_repository
    return await repo.list_integrations()


async def get_integration(id: str, repository: IntegrationRepository | None = None) -> Integration | None:
    """Fetch a single integration record by ID."""
    repo = repository or _default_repository
    return await repo.get_integration(id)


async def update_integration(
    id: str, integration: IntegrationUpdate, repository: IntegrationRepository | None = None
) -> Integration | None:
    """Update the provided integration and return the stored version."""
    repo = repository or _default_repository
    return await repo.update_integration(id, integration)


async def ensure_default_integrations(repository: IntegrationRepository | None = None) -> None:
    """Bootstrap the default integration records."""
    repo = repository or _default_repository
    await repo.ensure_default_integrations()