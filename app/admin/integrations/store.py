from typing import Any, List, Optional

from pymongo import ReturnDocument

from .schemas import Integration, IntegrationUpdate

collection_name = "integrations"


class IntegrationRepository:
    """Repository that encapsulates data access for integration objects.

    This class depends on an injected database-like object that supports
    __getitem__(collection_name) to obtain a collection with async Motor-like
    methods (find, find_one, find_one_and_update, update_one). By using a
    repository we avoid leaking raw DB documents to callers and make it easy
    to swap the persistence backend for tests or future datastore changes.
    """

    def __init__(self, db: Any, collection: str = collection_name) -> None:
        self._collection = db[collection]

    async def list_integrations(self) -> List[Integration]:
        """Return all integrations as Integration models."""
        cursor = self._collection.find()
        docs = await cursor.to_list(length=None)
        return [Integration(**doc) for doc in docs]

    async def get_integration(self, id: str) -> Optional[Integration]:
        """Return a single Integration by id, or None if not found."""
        doc = await self._collection.find_one({"id": id})
        if doc:
            return Integration(**doc)
        return None

    async def update_integration(
        self, id: str, integration: IntegrationUpdate
    ) -> Optional[Integration]:
        """Update an integration and return the updated Integration model.

        The repository is responsible for constructing the update document
        and using the appropriate $set semantics so callers only work with
        Integration models.
        """
        update_data = integration.model_dump(exclude_unset=True)

        result = await self._collection.find_one_and_update(
            {"id": id}, {"$set": update_data}, return_document=ReturnDocument.AFTER
        )

        if result:
            return Integration(**result)
        return None

    async def ensure_default_integrations(self) -> None:
        """Ensure default integrations exist in the datastore.

        Uses $setOnInsert to only populate defaults when a document with the
        given id does not already exist.
        """
        default_integrations = [
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

        for integration in default_integrations:
            await self._collection.update_one(
                {"id": integration["id"]}, {"$setOnInsert": integration}, upsert=True
            )


# Module-level default repository to support legacy call sites. Call
# configure_integration_repository(db) at application startup to populate
# this if you want the convenience functions below to work without passing a
# repository instance explicitly.
_default_repo: Optional[IntegrationRepository] = None


def configure_integration_repository(db: Any, collection: str = collection_name) -> None:
    """Configure the module-level IntegrationRepository used by the
    convenience functions. Passing a Motor (or compatible) database object is
    recommended.

    Example:
        from app.database import database
        configure_integration_repository(database)
    """
    global _default_repo
    _default_repo = IntegrationRepository(db, collection)


async def list_integrations(repo: Optional[IntegrationRepository] = None) -> List[Integration]:
    """Convenience wrapper that lists integrations using the provided
    repository or the module-level configured repository.
    """
    repo = repo or _default_repo
    if repo is None:
        raise RuntimeError(
            "IntegrationRepository not configured. Call configure_integration_repository(db) or pass a repository instance."
        )
    return await repo.list_integrations()


async def get_integration(id: str, repo: Optional[IntegrationRepository] = None) -> Optional[Integration]:
    """Convenience wrapper that retrieves a single integration."""
    repo = repo or _default_repo
    if repo is None:
        raise RuntimeError(
            "IntegrationRepository not configured. Call configure_integration_repository(db) or pass a repository instance."
        )
    return await repo.get_integration(id)


async def update_integration(
    id: str, integration: IntegrationUpdate, repo: Optional[IntegrationRepository] = None
) -> Optional[Integration]:
    """Convenience wrapper that updates an integration."""
    repo = repo or _default_repo
    if repo is None:
        raise RuntimeError(
            "IntegrationRepository not configured. Call configure_integration_repository(db) or pass a repository instance."
        )
    return await repo.update_integration(id, integration)


async def ensure_default_integrations(repo: Optional[IntegrationRepository] = None) -> None:
    """Ensure default integrations exist using the provided repository."""
    repo = repo or _default_repo
    if repo is None:
        raise RuntimeError(
            "IntegrationRepository not configured. Call configure_integration_repository(db) or pass a repository instance."
        )
    await repo.ensure_default_integrations()