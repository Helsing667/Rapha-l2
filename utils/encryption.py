"""
Encryption utilities for Nexus Core.

This module provides encryption and decryption capabilities using PyNaCl
(libsodium) for securing sensitive data such as API keys, tokens, and logs.

Features:
- Symmetric encryption with Fernet
- Key derivation with PBKDF2
- Secure key storage integration
- Encrypted file operations
"""

import os
import base64
from typing import Optional, Dict, Any
from pathlib import Path
import logging
import json

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

logger = logging.getLogger(__name__)


class EncryptionManager:
    """
    Manages encryption and decryption of sensitive data.
    
    This class handles key management, encryption/decryption operations,
    and secure storage integration.
    
    Attributes:
        service_name: Name for keyring service
        key_name: Name for the encryption key in keyring
    """
    
    def __init__(
        self,
        service_name: str = "nexus_core",
        key_name: str = "encryption_key",
    ):
        """
        Initialize the Encryption Manager.
        
        Args:
            service_name: Service name for keyring
            key_name: Key name for storing encryption key
        """
        self.service_name = service_name
        self.key_name = key_name
        self._fernet: Optional[Fernet] = None
        self._key: Optional[bytes] = None
        
        if not CRYPTO_AVAILABLE:
            logger.warning("cryptography library not available, encryption disabled")
        
        logger.info(f"EncryptionManager initialized (service={service_name})")
    
    def generate_key(self) -> str:
        """
        Generate a new encryption key.
        
        Returns:
            Base64-encoded encryption key
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library not available")
        
        key = Fernet.generate_key()
        return key.decode()
    
    def derive_key_from_password(self, password: str, salt: bytes) -> bytes:
        """
        Derive an encryption key from a password.
        
        Args:
            password: User password
            salt: Random salt for key derivation
            
        Returns:
            Derived key bytes
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library not available")
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend(),
        )
        
        return kdf.derive(password.encode())
    
    def get_or_create_key(self) -> Fernet:
        """
        Get existing key from storage or create a new one.
        
        Returns:
            Fernet instance for encryption/decryption
        """
        if self._fernet:
            return self._fernet
        
        # Try to get key from keyring
        if KEYRING_AVAILABLE:
            stored_key = keyring.get_password(self.service_name, self.key_name)
            
            if stored_key:
                self._key = stored_key.encode()
                self._fernet = Fernet(self._key)
                logger.debug("Loaded existing encryption key")
                return self._fernet
        
        # Generate new key
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library not available")
        
        new_key = Fernet.generate_key()
        self._key = new_key
        
        # Store in keyring if available
        if KEYRING_AVAILABLE:
            try:
                keyring.set_password(
                    self.service_name,
                    self.key_name,
                    new_key.decode(),
                )
                logger.debug("Stored new encryption key in keyring")
            except Exception as e:
                logger.warning(f"Failed to store key in keyring: {e}")
        
        self._fernet = Fernet(new_key)
        return self._fernet
    
    def encrypt(self, data: bytes) -> bytes:
        """
        Encrypt data.
        
        Args:
            data: Data to encrypt
            
        Returns:
            Encrypted data
        """
        fernet = self.get_or_create_key()
        return fernet.encrypt(data)
    
    def decrypt(self, encrypted_data: bytes) -> bytes:
        """
        Decrypt data.
        
        Args:
            encrypted_data: Encrypted data
            
        Returns:
            Decrypted data
        """
        fernet = self.get_or_create_key()
        return fernet.decrypt(encrypted_data)
    
    def encrypt_string(self, text: str) -> str:
        """
        Encrypt a string.
        
        Args:
            text: Text to encrypt
            
        Returns:
            Base64-encoded encrypted string
        """
        encrypted = self.encrypt(text.encode())
        return base64.b64encode(encrypted).decode()
    
    def decrypt_string(self, encrypted_text: str) -> str:
        """
        Decrypt a string.
        
        Args:
            encrypted_text: Base64-encoded encrypted string
            
        Returns:
            Decrypted text
        """
        encrypted = base64.b64decode(encrypted_text.encode())
        decrypted = self.decrypt(encrypted)
        return decrypted.decode()
    
    def encrypt_dict(self, data: Dict[str, Any]) -> str:
        """
        Encrypt a dictionary as JSON.
        
        Args:
            data: Dictionary to encrypt
            
        Returns:
            Base64-encoded encrypted JSON
        """
        json_data = json.dumps(data).encode()
        encrypted = self.encrypt(json_data)
        return base64.b64encode(encrypted).decode()
    
    def decrypt_dict(self, encrypted_text: str) -> Dict[str, Any]:
        """
        Decrypt a dictionary from JSON.
        
        Args:
            encrypted_text: Base64-encoded encrypted JSON
            
        Returns:
            Decrypted dictionary
        """
        encrypted = base64.b64decode(encrypted_text.encode())
        decrypted = self.decrypt(encrypted)
        return json.loads(decrypted.decode())
    
    def encrypt_file(self, input_path: str, output_path: Optional[str] = None) -> str:
        """
        Encrypt a file.
        
        Args:
            input_path: Path to input file
            output_path: Path for encrypted output (default: input.enc)
            
        Returns:
            Path to encrypted file
        """
        if output_path is None:
            output_path = f"{input_path}.enc"
        
        with open(input_path, 'rb') as f:
            data = f.read()
        
        encrypted = self.encrypt(data)
        
        with open(output_path, 'wb') as f:
            f.write(encrypted)
        
        logger.info(f"Encrypted file: {input_path} -> {output_path}")
        return output_path
    
    def decrypt_file(self, input_path: str, output_path: Optional[str] = None) -> str:
        """
        Decrypt a file.
        
        Args:
            input_path: Path to encrypted file
            output_path: Path for decrypted output (default: input without .enc)
            
        Returns:
            Path to decrypted file
        """
        if output_path is None:
            output_path = input_path.replace('.enc', '')
        
        with open(input_path, 'rb') as f:
            encrypted = f.read()
        
        decrypted = self.decrypt(encrypted)
        
        with open(output_path, 'wb') as f:
            f.write(decrypted)
        
        logger.info(f"Decrypted file: {input_path} -> {output_path}")
        return output_path
    
    def store_secret(self, name: str, value: str) -> bool:
        """
        Store a secret in keyring.
        
        Args:
            name: Secret name
            value: Secret value
            
        Returns:
            True if successful
        """
        if not KEYRING_AVAILABLE:
            logger.error("keyring not available")
            return False
        
        try:
            keyring.set_password(self.service_name, name, value)
            logger.debug(f"Stored secret: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to store secret {name}: {e}")
            return False
    
    def retrieve_secret(self, name: str) -> Optional[str]:
        """
        Retrieve a secret from keyring.
        
        Args:
            name: Secret name
            
        Returns:
            Secret value or None
        """
        if not KEYRING_AVAILABLE:
            return None
        
        try:
            value = keyring.get_password(self.service_name, name)
            return value
        except Exception as e:
            logger.error(f"Failed to retrieve secret {name}: {e}")
            return None
    
    def delete_secret(self, name: str) -> bool:
        """
        Delete a secret from keyring.
        
        Args:
            name: Secret name
            
        Returns:
            True if successful
        """
        if not KEYRING_AVAILABLE:
            return False
        
        try:
            keyring.delete_password(self.service_name, name)
            logger.debug(f"Deleted secret: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete secret {name}: {e}")
            return False
    
    def cleanup(self) -> None:
        """Clean up sensitive data from memory."""
        self._key = None
        self._fernet = None
        logger.debug("EncryptionManager cleaned up")
