"""
iOS Security Module.

This module provides security features specific to iOS integration,
including sandboxing, integrity verification, and device attestation.

Features:
- App Attest verification for iOS app authenticity
- DeviceCheck for device identification
- Security sandboxing with resource quotas
- Secure key storage integration
- Anomaly detection for iOS-specific threats
"""

import os
import json
import logging
import hashlib
import hmac
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
from pathlib import Path
import time
import subprocess

try:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger(__name__)


class SecurityLevel(Enum):
    """Security levels for iOS operations."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AttestationStatus(Enum):
    """App attestation status."""
    VERIFIED = "verified"
    FAILED = "failed"
    PENDING = "pending"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class DeviceInfo:
    """Information about an iOS device."""
    device_id: str
    model: str
    ios_version: str
    app_version: str
    attest_status: AttestationStatus
    last_seen: float
    trust_level: SecurityLevel = SecurityLevel.MEDIUM
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "device_id": self.device_id,
            "model": self.model,
            "ios_version": self.ios_version,
            "app_version": self.app_version,
            "attest_status": self.attest_status.value,
            "last_seen": self.last_seen,
            "trust_level": self.trust_level.value,
        }


@dataclass
class SecurityQuota:
    """Resource quota for iOS tasks."""
    max_cpu_percent: float = 50.0
    max_memory_mb: int = 512
    max_network_kb_per_min: int = 10240
    max_file_operations_per_min: int = 100
    max_api_calls_per_min: int = 60
    current_cpu: float = 0.0
    current_memory: int = 0
    current_network: int = 0
    current_file_ops: int = 0
    current_api_calls: int = 0
    window_start: float = field(default_factory=time.time)
    
    def reset_if_needed(self) -> None:
        """Reset counters if time window has passed."""
        now = time.time()
        if now - self.window_start >= 60:  # 1 minute window
            self.current_network = 0
            self.current_file_ops = 0
            self.current_api_calls = 0
            self.window_start = now
    
    def check_quota(self, resource: str, amount: int) -> bool:
        """
        Check if a resource request is within quota.
        
        Args:
            resource: Resource type (cpu, memory, network, file_ops, api_calls)
            amount: Amount requested
            
        Returns:
            True if within quota
        """
        self.reset_if_needed()
        
        limits = {
            "cpu": self.max_cpu_percent,
            "memory": self.max_memory_mb,
            "network": self.max_network_kb_per_min,
            "file_ops": self.max_file_operations_per_min,
            "api_calls": self.max_api_calls_per_min,
        }
        
        currents = {
            "cpu": self.current_cpu,
            "memory": self.current_memory,
            "network": self.current_network,
            "file_ops": self.current_file_ops,
            "api_calls": self.current_api_calls,
        }
        
        limit = limits.get(resource, 0)
        current = currents.get(resource, 0)
        
        return (current + amount) <= limit
    
    def consume(self, resource: str, amount: int) -> bool:
        """
        Consume resource from quota.
        
        Args:
            resource: Resource type
            amount: Amount to consume
            
        Returns:
            True if consumption succeeded
        """
        if not self.check_quota(resource, amount):
            logger.warning(f"Quota exceeded for {resource}")
            return False
        
        if resource == "cpu":
            self.current_cpu = amount
        elif resource == "memory":
            self.current_memory = amount
        elif resource == "network":
            self.current_network += amount
        elif resource == "file_ops":
            self.current_file_ops += amount
        elif resource == "api_calls":
            self.current_api_calls += amount
        
        return True


class IOSSecurity:
    """
    iOS Security Manager.
    
    This class handles security features specific to iOS integration,
    including device attestation, sandboxing, and quota management.
    
    Attributes:
        devices: Dictionary of known/trusted devices
        default_quota: Default resource quota for iOS tasks
    """
    
    def __init__(self):
        """Initialize the iOS security manager."""
        self.devices: Dict[str, DeviceInfo] = {}
        self.default_quota = SecurityQuota()
        self._revocation_list: List[str] = []
        self._attestation_cache: Dict[str, Tuple[AttestationStatus, float]] = {}
        
        logger.info("IOSSecurity initialized")
    
    async def verify_app_attest(self, device_id: str, attestation_data: Dict[str, Any]) -> AttestationStatus:
        """
        Verify iOS App Attest attestation.
        
        Args:
            device_id: Device identifier
            attestation_data: Attestation response from iOS app
            
        Returns:
            Attestation status
        """
        # Check cache first (5 minute validity)
        if device_id in self._attestation_cache:
            status, timestamp = self._attestation_cache[device_id]
            if time.time() - timestamp < 300:  # 5 minutes
                logger.debug(f"Using cached attestation for {device_id}")
                return status
        
        if not CRYPTO_AVAILABLE:
            logger.warning("Cryptography library not available, skipping attestation")
            return AttestationStatus.PENDING
        
        try:
            # In production, this would verify the App Attest assertion:
            # 1. Verify the attestation object signature using Apple's root CA
            # 2. Extract the public key from the attestation
            # 3. Verify the challenge response was signed by that key
            # 4. Check that the device hasn't been revoked
            
            # Stub implementation for now
            logger.info(f"App Attest verification stub for device: {device_id}")
            
            # Simulate successful verification
            status = AttestationStatus.VERIFIED
            
            # Cache the result
            self._attestation_cache[device_id] = (status, time.time())
            
            return status
            
        except Exception as e:
            logger.error(f"App Attest verification failed: {e}")
            return AttestationStatus.FAILED
    
    async def verify_device_check(self, device_id: str, token: str) -> bool:
        """
        Verify device using Apple DeviceCheck.
        
        Args:
            device_id: Device identifier
            token: DeviceCheck token
            
        Returns:
            True if device is verified
        """
        if not CRYPTO_AVAILABLE:
            return False
        
        try:
            # In production, this would:
            # 1. Send the token to Apple's DeviceCheck API
            # 2. Verify the response indicates a valid device
            # 3. Check that the device hasn't been flagged
            
            logger.info(f"DeviceCheck verification stub for device: {device_id}")
            
            # For stub, assume valid
            return True
            
        except Exception as e:
            logger.error(f"DeviceCheck verification failed: {e}")
            return False
    
    def register_device(
        self,
        device_id: str,
        model: str,
        ios_version: str,
        app_version: str,
        attest_status: AttestationStatus,
    ) -> DeviceInfo:
        """
        Register a new iOS device.
        
        Args:
            device_id: Unique device identifier
            model: Device model (e.g., "iPhone14,2")
            ios_version: iOS version string
            app_version: Nexus Core iOS app version
            attest_status: Initial attestation status
            
        Returns:
            Registered device info
        """
        device = DeviceInfo(
            device_id=device_id,
            model=model,
            ios_version=ios_version,
            app_version=app_version,
            attest_status=attest_status,
            last_seen=time.time(),
            trust_level=SecurityLevel.LOW if attest_status != AttestationStatus.VERIFIED else SecurityLevel.MEDIUM,
        )
        
        self.devices[device_id] = device
        logger.info(f"Device registered: {device_id} ({model})")
        
        return device
    
    def update_device_trust(self, device_id: str, trust_level: SecurityLevel) -> bool:
        """
        Update trust level for a device.
        
        Args:
            device_id: Device identifier
            trust_level: New trust level
            
        Returns:
            True if update succeeded
        """
        if device_id not in self.devices:
            return False
        
        self.devices[device_id].trust_level = trust_level
        logger.info(f"Device {device_id} trust updated to {trust_level.value}")
        
        return True
    
    def revoke_device(self, device_id: str) -> bool:
        """
        Revoke a device's access (emergency revocation).
        
        Args:
            device_id: Device identifier to revoke
            
        Returns:
            True if revocation succeeded
        """
        # Add to revocation list
        if device_id not in self._revocation_list:
            self._revocation_list.append(device_id)
        
        # Update device status if registered
        if device_id in self.devices:
            self.devices[device_id].attest_status = AttestationStatus.REVOKED
            self.devices[device_id].trust_level = SecurityLevel.LOW
        
        # Clear attestation cache
        if device_id in self._attestation_cache:
            del self._attestation_cache[device_id]
        
        logger.warning(f"Device revoked: {device_id}")
        
        return True
    
    def is_device_revoked(self, device_id: str) -> bool:
        """
        Check if a device is revoked.
        
        Args:
            device_id: Device identifier
            
        Returns:
            True if device is revoked
        """
        return device_id in self._revocation_list
    
    def check_sandbox_quota(self, device_id: str, resource: str, amount: int) -> bool:
        """
        Check if a resource request is within sandbox quota.
        
        Args:
            device_id: Device identifier
            resource: Resource type
            amount: Amount requested
            
        Returns:
            True if within quota
        """
        # Get device-specific quota or use default
        quota = self.default_quota
        
        if device_id in self.devices:
            # Could have device-specific quotas based on trust level
            trust = self.devices[device_id].trust_level
            if trust == SecurityLevel.HIGH:
                # Higher limits for trusted devices
                quota = SecurityQuota(
                    max_cpu_percent=80.0,
                    max_memory_mb=1024,
                    max_network_kb_per_min=51200,
                )
        
        return quota.check_quota(resource, amount)
    
    def consume_sandbox_quota(self, device_id: str, resource: str, amount: int) -> bool:
        """
        Consume resource from sandbox quota.
        
        Args:
            device_id: Device identifier
            resource: Resource type
            amount: Amount to consume
            
        Returns:
            True if consumption succeeded
        """
        return self.default_quota.consume(resource, amount)
    
    def get_security_status(self) -> Dict[str, Any]:
        """Get current security status."""
        return {
            "registered_devices": len(self.devices),
            "revoked_devices": len(self._revocation_list),
            "cached_attestations": len(self._attestation_cache),
            "devices": [d.to_dict() for d in self.devices.values()],
            "quota": {
                "cpu_percent": self.default_quota.current_cpu,
                "memory_mb": self.default_quota.current_memory,
                "network_kb": self.default_quota.current_network,
                "file_ops": self.default_quota.current_file_ops,
                "api_calls": self.default_quota.current_api_calls,
            },
        }
    
    def generate_revocation_token(self, device_id: str) -> str:
        """
        Generate a revocation token for emergency device revocation.
        
        Args:
            device_id: Device identifier
            
        Returns:
            Revocation token (JWT-like format)
        """
        timestamp = int(time.time())
        payload = {
            "device_id": device_id,
            "action": "revoke",
            "timestamp": timestamp,
        }
        
        # Create HMAC signature
        secret = os.urandom(32)  # In production, use stored secret key
        payload_json = json.dumps(payload, sort_keys=True)
        signature = hmac.new(secret, payload_json.encode(), hashlib.sha256).hexdigest()
        
        # Encode as base64
        import base64
        token_data = base64.b64encode(payload_json.encode()).decode()
        token_sig = base64.b64encode(signature.encode()).decode()
        
        return f"{token_data}.{token_sig}"
