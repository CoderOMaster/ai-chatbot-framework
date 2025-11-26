"""
Entity CRUD routes for admin API.

This module provides FastAPI routes for entity management operations.
Designed as a thin stateless layer over the entity store, suitable for
extraction as serverless Lambda functions behind API Gateway.

All routes include proper HTTP error handling (404/400) and type annotations.
"""

from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, status
from bson.errors import InvalidId

from app.admin.entities import store
from app.admin.entities.schemas import Entity


# Module-scope DB initialization for Lambda
def _init_store() -> None:
    """
    Initialize the entity store at module load time.
    
    For Lambda deployments, this ensures the repository is configured
    before any handler is invoked. Called once when the module is imported.
    """
    try:
        if store._repository is None:
            store.set_repository(store.MongoEntityRepository())
    except Exception as e:
        raise RuntimeError(f"Failed to initialize entity store: {e}")


# Initialize store on module import
_init_store()


router = APIRouter(prefix="/entities", tags=["entities"])


@router.post("/", response_model=Entity, status_code=status.HTTP_201_CREATED)
async def create_entity(entity: Entity) -> Entity:
    """
    Create a new entity.
    
    Args:
        entity: Entity data to create (id field ignored)
        
    Returns:
        Entity: The created entity with generated ID
        
    Raises:
        HTTPException: 400 if entity data is invalid
    """
    try:
        entity_dict = entity.model_dump(exclude={"id"})
        created_entity = await store.add_entity(entity_dict)
        return created_entity
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid entity data: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create entity: {str(e)}"
        )


@router.get("/", response_model=List[Entity])
async def read_entities() -> List[Entity]:
    """
    Get all entities.
    
    Returns:
        List[Entity]: List of all entities in the system
        
    Raises:
        HTTPException: 500 if database query fails
    """
    try:
        entities = await store.list_entities()
        return entities
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve entities: {str(e)}"
        )


@router.get("/{entity_id}", response_model=Entity)
async def read_entity(entity_id: str) -> Entity:
    """
    Get a specific entity by ID.
    
    Args:
        entity_id: MongoDB ObjectId as string
        
    Returns:
        Entity: The requested entity
        
    Raises:
        HTTPException: 400 if entity_id is not a valid ObjectId
        HTTPException: 404 if entity not found
    """
    try:
        entity = await store.get_entity(entity_id)
        if entity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entity with id '{entity_id}' not found"
            )
        return entity
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid entity ID format: '{entity_id}'"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve entity: {str(e)}"
        )


@router.put("/{entity_id}", response_model=Dict[str, str])
async def update_entity(entity_id: str, entity: Entity) -> Dict[str, str]:
    """
    Update an entity.
    
    Args:
        entity_id: MongoDB ObjectId as string
        entity: Updated entity data (id field ignored)
        
    Returns:
        Dict[str, str]: Status confirmation
        
    Raises:
        HTTPException: 400 if entity_id is invalid or entity data is invalid
        HTTPException: 404 if entity not found
    """
    try:
        # Verify entity exists first
        existing = await store.get_entity(entity_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entity with id '{entity_id}' not found"
            )
        
        entity_dict = entity.model_dump(exclude={"id"})
        await store.edit_entity(entity_id, entity_dict)
        return {"status": "success"}
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid entity ID format: '{entity_id}'"
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid entity data: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update entity: {str(e)}"
        )


@router.delete("/{entity_id}", response_model=Dict[str, str])
async def delete_entity(entity_id: str) -> Dict[str, str]:
    """
    Delete an entity.
    
    Args:
        entity_id: MongoDB ObjectId as string
        
    Returns:
        Dict[str, str]: Status confirmation
        
    Raises:
        HTTPException: 400 if entity_id is invalid
        HTTPException: 404 if entity not found
    """
    try:
        # Verify entity exists first
        existing = await store.get_entity(entity_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entity with id '{entity_id}' not found"
            )
        
        await store.delete_entity(entity_id)
        return {"status": "success"}
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid entity ID format: '{entity_id}'"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete entity: {str(e)}"
        )


# Lambda handler shims for serverless deployment
async def _lambda_handler(event: Dict[str, Any], context: Any, handler_func) -> Dict[str, Any]:
    """
    Generic Lambda handler wrapper for API Gateway events.
    
    Converts API Gateway proxy events to FastAPI-compatible format and
    invokes the appropriate route handler.
    
    Args:
        event: API Gateway Lambda proxy event
        context: Lambda context object
        handler_func: Async route handler function to invoke
        
    Returns:
        Dict[str, Any]: Lambda proxy response format
    """
    try:
        # Extract path parameters and query string from event
        path_params = event.get("pathParameters", {}) or {}
        query_params = event.get("queryStringParameters", {}) or {}
        
        # Invoke handler with extracted parameters
        result = await handler_func(**path_params, **query_params)
        
        return {
            "statusCode": 200,
            "body": result,
        }
    except HTTPException as e:
        return {
            "statusCode": e.status_code,
            "body": {"detail": e.detail},
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": {"detail": f"Internal server error: {str(e)}"},
        }


async def lambda_create_entity(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for POST /admin/entities.
    
    Args:
        event: API Gateway Lambda proxy event with entity data in body
        context: Lambda context object
        
    Returns:
        Dict[str, Any]: Lambda proxy response
    """
    import json
    try:
        body = json.loads(event.get("body", "{}"))
        entity = Entity(**body)
        result = await create_entity(entity)
        return {
            "statusCode": 201,
            "body": result.model_dump(mode="json"),
        }
    except HTTPException as e:
        return {
            "statusCode": e.status_code,
            "body": {"detail": e.detail},
        }
    except Exception as e:
        return {
            "statusCode": 400,
            "body": {"detail": f"Invalid request: {str(e)}"},
        }


async def lambda_read_entities(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for GET /admin/entities.
    
    Args:
        event: API Gateway Lambda proxy event
        context: Lambda context object
        
    Returns:
        Dict[str, Any]: Lambda proxy response with entities list
    """
    try:
        result = await read_entities()
        return {
            "statusCode": 200,
            "body": [entity.model_dump(mode="json") for entity in result],
        }
    except HTTPException as e:
        return {
            "statusCode": e.status_code,
            "body": {"detail": e.detail},
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": {"detail": f"Internal server error: {str(e)}"},
        }


async def lambda_read_entity(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for GET /admin/entities/{entity_id}.
    
    Args:
        event: API Gateway Lambda proxy event with entity_id in path
        context: Lambda context object
        
    Returns:
        Dict[str, Any]: Lambda proxy response with entity data
    """
    try:
        entity_id = event.get("pathParameters", {}).get("entity_id")
        if not entity_id:
            return {
                "statusCode": 400,
                "body": {"detail": "Missing entity_id path parameter"},
            }
        result = await read_entity(entity_id)
        return {
            "statusCode": 200,
            "body": result.model_dump(mode="json"),
        }
    except HTTPException as e:
        return {
            "statusCode": e.status_code,
            "body": {"detail": e.detail},
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": {"detail": f"Internal server error: {str(e)}"},
        }


async def lambda_update_entity(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for PUT /admin/entities/{entity_id}.
    
    Args:
        event: API Gateway Lambda proxy event with entity_id in path and data in body
        context: Lambda context object
        
    Returns:
        Dict[str, Any]: Lambda proxy response with status
    """
    import json
    try:
        entity_id = event.get("pathParameters", {}).get("entity_id")
        if not entity_id:
            return {
                "statusCode": 400,
                "body": {"detail": "Missing entity_id path parameter"},
            }
        body = json.loads(event.get("body", "{}"))
        entity = Entity(**body)
        result = await update_entity(entity_id, entity)
        return {
            "statusCode": 200,
            "body": result,
        }
    except HTTPException as e:
        return {
            "statusCode": e.status_code,
            "body": {"detail": e.detail},
        }
    except Exception as e:
        return {
            "statusCode": 400,
            "body": {"detail": f"Invalid request: {str(e)}"},
        }


async def lambda_delete_entity(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for DELETE /admin/entities/{entity_id}.
    
    Args:
        event: API Gateway Lambda proxy event with entity_id in path
        context: Lambda context object
        
    Returns:
        Dict[str, Any]: Lambda proxy response with status
    """
    try:
        entity_id = event.get("pathParameters", {}).get("entity_id")
        if not entity_id:
            return {
                "statusCode": 400,
                "body": {"detail": "Missing entity_id path parameter"},
            }
        result = await delete_entity(entity_id)
        return {
            "statusCode": 200,
            "body": result,
        }
    except HTTPException as e:
        return {
            "statusCode": e.status_code,
            "body": {"detail": e.detail},
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": {"detail": f"Internal server error: {str(e)}"},
        }