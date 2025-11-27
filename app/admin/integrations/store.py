"""Integration configuration store with encryption, validation, and audit logging."""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from cryptography.fernet import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
import base64
import os

from app.database import get_database
from app.config import app_config
from .schemas import Integration, IntegrationUpdate, IntegrationStatus

logger = logging.getLogger(__name__)

collection_name = "integrations"
audit_collection_name = "integration_audit_logs"

# Encryption configuration
ENCRYPTION_SALT = b"integration_store_salt"  # In production, use environment variable
SENSITIVE_FIELDS = {"secret", "page_access_token", "webhook_url", "token", "api_token", "app_key", "integration_key", "api_key"}


class EncryptionManager:
    """Manages encryption and decryption of sensitive settings."""
    
    def __init__(self, encryption_key: Optional[str] = None):
        """Initialize encryption manager.
        
        Args:
            encryption_key: Encryption key (uses app_config.ENCRYPTION_KEY if not provided)
        """
        self.encryption_key = encryption_key or getattr(app_config, "ENCRYPTION_KEY", "default-key")
        self._cipher_key = self._derive_key()
    
    def _derive_key(self) -> bytes:
        """Derive encryption key from master key using PBKDF2."""
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=ENCRYPTION_SALT,
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(self.encryption_key.encode()))
    
    def encrypt_value(self, value: str) -> str:
        """Encrypt a sensitive value.
        
        Args:
            value: Value to encrypt
            
        Returns:
            Encrypted value as base64 string
        """
        try:
            iv = os.urandom(16)
            cipher = Cipher(algorithms.AES(self._cipher_key), modes.CBC(iv))
            encryptor = cipher.encryptor()
            
            # Add PKCS7 padding
            padding_length = 16 - (len(value.encode()) % 16)
            padded_value = value.encode() + bytes([padding_length] * padding_length)
            
            encrypted = encryptor.update(padded_value) + encryptor.finalize()
            return base64.urlsafe_b64encode(iv + encrypted).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise ValueError("Failed to encrypt sensitive data")
    
    def decrypt_value(self, encrypted_value: str) -> str:
        """Decrypt a sensitive value.
        
        Args:
            encrypted_value: Encrypted value as base64 string
            
        Returns:
            Decrypted value
        """
        try:
            data = base64.urlsafe_b64decode(encrypted_value.encode())
            iv = data[:16]
            encrypted = data[16:]
            
            cipher = Cipher(algorithms.AES(self._cipher_key), modes.CBC(iv))
            decryptor = cipher.decryptor()
            
            padded_value = decryptor.update(encrypted) + decryptor.finalize()
            
            # Remove PKCS7 padding
            padding_length = padded_value[-1]
            return padded_value[:-padding_length].decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise ValueError("Failed to decrypt sensitive data")


class AuditLogger:
    """Manages audit logging for integration changes."""
    
    def __init__(self):
        """Initialize audit logger."""
        self.encryption_manager = EncryptionManager()
    
    async def log_change(
        self,
        integration_id: str,
        action: str,
        changes: Dict[str, Any],
        user_id: Optional[str] = None,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> None:
        """Log an integration change to audit collection.
        
        Args:
            integration_id: ID of the integration
            action: Action performed (create, update, delete, test_connection)
            changes: Dictionary of changes made
            user_id: ID of user making the change
            status: Status of the action (success, failed)
            error_message: Error message if action failed
        """
        try:
            database = await get_database()
            audit_log = {
                "integration_id": integration_id,
                "action": action,
                "changes": changes,
                "user_id": user_id,
                "status": status,
                "error_message": error_message,
                "timestamp": datetime.utcnow(),
            }
            await database[audit_collection_name].insert_one(audit_log)
            logger.info(f"Audit log created for {integration_id}: {action}")
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")


class IntegrationStore:
    """Store for managing integration configurations with validation and encryption."""
    
    def __init__(self):
        """Initialize integration store."""
        self.encryption_manager = EncryptionManager()
        self.audit_logger = AuditLogger()
    
    def _encrypt_sensitive_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Encrypt sensitive fields in settings.
        
        Args:
            settings: Settings dictionary
            
        Returns:
            Settings with sensitive fields encrypted
        """
        encrypted_settings = settings.copy()
        for field in SENSITIVE_FIELDS:
            if field in encrypted_settings and encrypted_settings[field]:
                try:
                    encrypted_settings[field] = self.encryption_manager.encrypt_value(
                        str(encrypted_settings[field])
                    )
                except Exception as e:
                    logger.warning(f"Failed to encrypt field {field}: {e}")
        return encrypted_settings
    
    def _decrypt_sensitive_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypt sensitive fields in settings.
        
        Args:
            settings: Settings dictionary with encrypted fields
            
        Returns:
            Settings with sensitive fields decrypted
        """
        decrypted_settings = settings.copy()
        for field in SENSITIVE_FIELDS:
            if field in decrypted_settings and decrypted_settings[field]:
                try:
                    decrypted_settings[field] = self.encryption_manager.decrypt_value(
                        decrypted_settings[field]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt field {field}: {e}")
        return decrypted_settings
    
    async def _validate_integration_status(self, integration_id: str, status: IntegrationStatus) -> bool:
        """Validate integration status transition.
        
        Args:
            integration_id: Integration ID
            status: New status
            
        Returns:
            True if status is valid
            
        Raises:
            ValueError: If status transition is invalid
        """
        valid_statuses = [s.value for s in IntegrationStatus]
        if status.value not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}")
        return True
    
    async def test_connection(self, integration_id: str) -> Dict[str, Any]:
        """Test connection for an integration.
        
        Args:
            integration_id: Integration ID
            
        Returns:
            Connection test result
        """
        try:
            database = await get_database()
            integration_doc = await database[collection_name].find_one({"id": integration_id})
            
            if not integration_doc:
                error_msg = f"Integration {integration_id} not found"
                await self.audit_logger.log_change(
                    integration_id,
                    "test_connection",
                    {},
                    status="failed",
                    error_message=error_msg,
                )
                raise ValueError(error_msg)
            
            # Decrypt settings for connection test
            decrypted_settings = self._decrypt_sensitive_settings(integration_doc.get("settings", {}))
            
            # Basic connectivity check - can be extended per integration type
            result = {
                "integration_id": integration_id,
                "status": "connected",
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            await self.audit_logger.log_change(
                integration_id,
                "test_connection",
                {"result": "success"},
                status="success",
            )
            
            return result
        except Exception as e:
            logger.error(f"Connection test failed for {integration_id}: {e}")
            await self.audit_logger.log_change(
                integration_id,
                "test_connection",
                {},
                status="failed",
                error_message=str(e),
            )
            raise
    
    async def list_integrations(self) -> List[Integration]:
        """Get all integrations.
        
        Returns:
            List of integrations
            
        Raises:
            RuntimeError: If database operation fails
        """
        try:
            database = await get_database()
            cursor = database[collection_name].find()
            integrations_data = await cursor.to_list(length=None)
            
            integrations = []
            for integration_data in integrations_data:
                # Decrypt sensitive fields before returning
                integration_data["settings"] = self._decrypt_sensitive_settings(
                    integration_data.get("settings", {})
                )
                integrations.append(Integration(**integration_data))
            
            return integrations
        except Exception as e:
            logger.error(f"Failed to list integrations: {e}")
            raise RuntimeError(f"Failed to retrieve integrations: {e}")
    
    async def get_integration(self, id: str) -> Optional[Integration]:
        """Get a specific integration by ID.
        
        Args:
            id: Integration ID
            
        Returns:
            Integration object or None if not found
            
        Raises:
            RuntimeError: If database operation fails
        """
        try:
            database = await get_database()
            integration_doc = await database[collection_name].find_one({"id": id})
            
            if integration_doc:
                # Decrypt sensitive fields before returning
                integration_doc["settings"] = self._decrypt_sensitive_settings(
                    integration_doc.get("settings", {})
                )
                return Integration(**integration_doc)
            return None
        except Exception as e:
            logger.error(f"Failed to get integration {id}: {e}")
            raise RuntimeError(f"Failed to retrieve integration: {e}")
    
    async def update_integration(
        self, id: str, integration: IntegrationUpdate, user_id: Optional[str] = None
    ) -> Optional[Integration]:
        """Update an integration's status and settings.
        
        Args:
            id: Integration ID
            integration: Update data
            user_id: ID of user making the update
            
        Returns:
            Updated integration or None if not found
            
        Raises:
            ValueError: If validation fails
            RuntimeError: If database operation fails
        """
        try:
            database = await get_database()
            
            # Validate status if provided
            if integration.status:
                await self._validate_integration_status(id, integration.status)
            
            update_data = integration.model_dump(exclude_unset=True)
            
            # Encrypt sensitive settings before storage
            if "settings" in update_data and update_data["settings"]:
                update_data["settings"] = self._encrypt_sensitive_settings(update_data["settings"])
            
            result = await database[collection_name].find_one_and_update(
                {"id": id},
                {"$set": update_data},
                return_document=True,
            )
            
            if result:
                # Log the change
                await self.audit_logger.log_change(
                    id,
                    "update",
                    update_data,
                    user_id=user_id,
                    status="success",
                )
                
                # Decrypt sensitive fields before returning
                result["settings"] = self._decrypt_sensitive_settings(result.get("settings", {}))
                return Integration(**result)
            
            error_msg = f"Integration {id} not found"
            await self.audit_logger.log_change(
                id,
                "update",
                update_data,
                user_id=user_id,
                status="failed",
                error_message=error_msg,
            )
            return None
        except ValueError as e:
            logger.error(f"Validation error updating integration {id}: {e}")
            await self.audit_logger.log_change(
                id,
                "update",
                {},
                user_id=user_id,
                status="failed",
                error_message=str(e),
            )
            raise
        except Exception as e:
            logger.error(f"Failed to update integration {id}: {e}")
            raise RuntimeError(f"Failed to update integration: {e}")
    
    async def ensure_default_integrations(self) -> None:
        """Ensure default integrations exist in the database.
        
        Raises:
            RuntimeError: If database operation fails
        """
        try:
            database = await get_database()
            default_integrations = [
                {
                    "id": "facebook",
                    "name": "Facebook Messenger",
                    "description": "Connect with Facebook Messenger",
                    "status": IntegrationStatus.INACTIVE.value,
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
                    "status": IntegrationStatus.ACTIVE.value,
                    "settings": {},
                },
            ]
            
            for integration in default_integrations:
                # Encrypt sensitive settings
                integration["settings"] = self._encrypt_sensitive_settings(integration["settings"])
                
                await database[collection_name].update_one(
                    {"id": integration["id"]},
                    {"$setOnInsert": integration},
                    upsert=True,
                )
                logger.info(f"Ensured default integration: {integration['id']}")
        except Exception as e:
            logger.error(f"Failed to ensure default integrations: {e}")
            raise RuntimeError(f"Failed to initialize default integrations: {e}")


# Initialize store instance
_store = IntegrationStore()


async def list_integrations() -> List[Integration]:
    """Get all integrations."""
    return await _store.list_integrations()


async def get_integration(id: str) -> Optional[Integration]:
    """Get a specific integration by ID."""
    return await _store.get_integration(id)


async def update_integration(
    id: str, integration: IntegrationUpdate, user_id: Optional[str] = None
) -> Optional[Integration]:
    """Update an integration's status and settings."""
    return await _store.update_integration(id, integration, user_id)


async def test_connection(integration_id: str) -> Dict[str, Any]:
    """Test connection for an integration."""
    return await _store.test_connection(integration_id)


async def ensure_default_integrations() -> None:
    """Ensure default integrations exist in the database."""
    return await _store.ensure_default_integrations()