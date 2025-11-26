"""
Entity repository layer for CRUD and bulk import operations.

This module provides async repository methods for managing entities in MongoDB.
All operations return Pydantic DTOs (Entity, EntityValue) instead of raw dicts,
enabling easier migration to a dedicated microservice.

The repository interface is designed to be database-agnostic, allowing future
swapping of persistence layers without affecting consumers.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from bson import ObjectId

from app.admin.entities.schemas import Entity, EntityValue
from app.database import get_collection


class EntityRepository(ABC):
    """
    Abstract repository interface for entity persistence operations.
    
    Defines the contract for entity storage operations, enabling dependency
    injection and easier testing. All methods return Pydantic DTOs.
    """

    @abstractmethod
    async def create(self, entity_data: Dict) -> Entity:
        """
        Create a new entity.
        
        Args:
            entity_data: Dictionary containing entity fields
            
        Returns:
            Entity: The created entity as a Pydantic model
        """
        pass

    @abstractmethod
    async def get_by_id(self, entity_id: str) -> Optional[Entity]:
        """
        Retrieve an entity by ID.
        
        Args:
            entity_id: MongoDB ObjectId as string
            
        Returns:
            Entity: The entity if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_all(self) -> List[Entity]:
        """
        Retrieve all entities.
        
        Returns:
            List[Entity]: List of all entities as Pydantic models
        """
        pass

    @abstractmethod
    async def update(self, entity_id: str, entity_data: Dict) -> Entity:
        """
        Update an existing entity.
        
        Args:
            entity_id: MongoDB ObjectId as string
            entity_data: Dictionary of fields to update
            
        Returns:
            Entity: The updated entity as a Pydantic model
        """
        pass

    @abstractmethod
    async def delete(self, entity_id: str) -> None:
        """
        Delete an entity.
        
        Args:
            entity_id: MongoDB ObjectId as string
        """
        pass

    @abstractmethod
    async def bulk_import(self, entities: List[Dict]) -> List[str]:
        """
        Bulk import or upsert entities by name.
        
        Args:
            entities: List of entity dictionaries to import
            
        Returns:
            List[str]: List of created entity IDs (upserted_id values)
        """
        pass

    @abstractmethod
    async def list_synonyms(self) -> Dict[str, str]:
        """
        List all synonyms across all entities.
        
        Returns:
            Dict[str, str]: Mapping of synonym to canonical value
        """
        pass


class MongoEntityRepository(EntityRepository):
    """
    MongoDB implementation of EntityRepository.
    
    Provides async CRUD operations and bulk import functionality for entities
    stored in MongoDB. All operations return Pydantic DTOs for type safety.
    """

    def __init__(self):
        """Initialize repository with entity collection reference."""
        self._collection = get_collection("entity")

    async def create(self, entity_data: Dict) -> Entity:
        """
        Create a new entity in MongoDB.
        
        Args:
            entity_data: Dictionary containing entity fields
            
        Returns:
            Entity: The created entity with generated ID
        """
        result = await self._collection.insert_one(entity_data)
        return await self.get_by_id(str(result.inserted_id))

    async def get_by_id(self, entity_id: str) -> Optional[Entity]:
        """
        Retrieve an entity by ID from MongoDB.
        
        Args:
            entity_id: MongoDB ObjectId as string
            
        Returns:
            Entity: The entity if found, None otherwise
        """
        entity = await self._collection.find_one({"_id": ObjectId(entity_id)})
        if entity is None:
            return None
        return Entity.model_validate(entity)

    async def list_all(self) -> List[Entity]:
        """
        Retrieve all entities from MongoDB.
        
        Returns:
            List[Entity]: List of all entities as Pydantic models
        """
        entities = await self._collection.find().to_list(None)
        return [Entity.model_validate(entity) for entity in entities]

    async def update(self, entity_id: str, entity_data: Dict) -> Entity:
        """
        Update an existing entity in MongoDB.
        
        Args:
            entity_id: MongoDB ObjectId as string
            entity_data: Dictionary of fields to update
            
        Returns:
            Entity: The updated entity as a Pydantic model
        """
        await self._collection.update_one(
            {"_id": ObjectId(entity_id)}, {"$set": entity_data}
        )
        return await self.get_by_id(entity_id)

    async def delete(self, entity_id: str) -> None:
        """
        Delete an entity from MongoDB.
        
        Args:
            entity_id: MongoDB ObjectId as string
        """
        await self._collection.delete_one({"_id": ObjectId(entity_id)})

    async def bulk_import(self, entities: List[Dict]) -> List[str]:
        """
        Bulk import or upsert entities by name.
        
        For each entity in the list, performs an upsert operation using the
        entity's name as the unique key. Returns IDs of newly created entities.
        
        Args:
            entities: List of entity dictionaries to import
            
        Returns:
            List[str]: List of created entity IDs (upserted_id values)
        """
        created_entities = []
        if entities:
            for entity in entities:
                result = await self._collection.update_one(
                    {"name": entity.get("name")}, {"$set": entity}, upsert=True
                )
                if result.upserted_id:
                    created_entities.append(str(result.upserted_id))
        return created_entities

    async def list_synonyms(self) -> Dict[str, str]:
        """
        List all synonyms across all entities.
        
        Iterates through all entities and their values to build a mapping
        of each synonym to its canonical value.
        
        Returns:
            Dict[str, str]: Mapping of synonym to canonical value
        """
        synonyms = {}
        entities = await self.list_all()
        for entity in entities:
            for value in entity.entity_values:
                for synonym in value.synonyms:
                    synonyms[synonym] = value.value
        return synonyms


# Global repository instance for backward compatibility
_repository: Optional[EntityRepository] = None


def set_repository(repository: EntityRepository) -> None:
    """
    Set the global entity repository instance.
    
    Enables dependency injection of repository implementations for testing
    and future microservice extraction.
    
    Args:
        repository: EntityRepository implementation to use globally
    """
    global _repository
    _repository = repository


def get_repository() -> EntityRepository:
    """
    Get the global entity repository instance.
    
    Returns:
        EntityRepository: The configured repository instance
        
    Raises:
        RuntimeError: If repository has not been initialized
    """
    if _repository is None:
        raise RuntimeError("Repository not initialized. Call set_repository() first.")
    return _repository


# Module-level convenience functions for backward compatibility
async def add_entity(entity_data: dict) -> Entity:
    """
    Create a new entity.
    
    Args:
        entity_data: Dictionary containing entity fields
        
    Returns:
        Entity: The created entity as a Pydantic model
    """
    repo = get_repository()
    return await repo.create(entity_data)


async def get_entity(entity_id: str) -> Optional[Entity]:
    """
    Retrieve an entity by ID.
    
    Args:
        entity_id: MongoDB ObjectId as string
        
    Returns:
        Entity: The entity if found, None otherwise
    """
    repo = get_repository()
    return await repo.get_by_id(entity_id)


async def list_entities() -> List[Entity]:
    """
    Retrieve all entities.
    
    Returns:
        List[Entity]: List of all entities as Pydantic models
    """
    repo = get_repository()
    return await repo.list_all()


async def edit_entity(entity_id: str, entity_data: dict) -> Entity:
    """
    Update an existing entity.
    
    Args:
        entity_id: MongoDB ObjectId as string
        entity_data: Dictionary of fields to update
        
    Returns:
        Entity: The updated entity as a Pydantic model
    """
    repo = get_repository()
    return await repo.update(entity_id, entity_data)


async def delete_entity(entity_id: str) -> None:
    """
    Delete an entity.
    
    Args:
        entity_id: MongoDB ObjectId as string
    """
    repo = get_repository()
    await repo.delete(entity_id)


async def list_synonyms() -> Dict[str, str]:
    """
    List all synonyms across all entities.
    
    Returns:
        Dict[str, str]: Mapping of synonym to canonical value
    """
    repo = get_repository()
    return await repo.list_synonyms()


async def bulk_import_entities(entities: List[Dict]) -> List[str]:
    """
    Bulk import or upsert entities by name.
    
    Args:
        entities: List of entity dictionaries to import
        
    Returns:
        List[str]: List of created entity IDs
    """
    repo = get_repository()
    return await repo.bulk_import(entities)