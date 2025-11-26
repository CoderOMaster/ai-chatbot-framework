"""Integration schemas for CRUD operations.

This module provides Pydantic models for integration management,
supporting ORM compatibility through from_attributes configuration.
"""

from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict


class IntegrationBase(BaseModel):
    """Base integration model with common attributes."""

    id: str
    name: str
    description: str
    status: bool = False
    settings: Optional[Dict] = None

    model_config = ConfigDict(from_attributes=True)


class IntegrationCreate(IntegrationBase):
    """Schema for creating a new integration."""

    pass


class IntegrationUpdate(IntegrationBase):
    """Schema for updating an existing integration."""

    pass


class Integration(IntegrationBase):
    """Complete integration model for read operations."""

    pass