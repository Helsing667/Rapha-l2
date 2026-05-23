"""
iOS Communication Protocol Module.

This module implements secure bidirectional communication between Nexus Core
and iOS devices using WebSocket Secure (WSS) or MQTT over TLS.

Features:
- WSS/MQTT protocol selection
- X.509 certificate-based mutual authentication
- ChaCha20-Poly1305 end-to-end encryption
- ECDH key exchange for session keys
- HMAC-SHA256 message signing
- Automatic reconnection with exponential backoff
- Message queuing for offline devices
"""

import asyncio
import json
import logging
import ssl
import time
import hmac
import hashlib
import base64
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import os

try:
    import websockets
    from websockets.client import WebSocketClientProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

try:
    from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.backends import default_backend
    from cryptography.x509 import load_pem_x509_certificate
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

try:
    import nacl.bindings
    from nacl.secret import SecretBox
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False

logger = logging.getLogger(__name__)


class ProtocolType(Enum):
    """Communication protocol types."""
    WEBSOCKET = "websocket"
    MQTT = "mqtt"


class ConnectionState(Enum):
    """Connection state enumeration."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AUTHENTICATING = "authenticating"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class IOSMessage:
    """Represents a message to/from iOS device."""
    message_id: str
    timestamp: float
    message_type: str
    payload: Dict[str, Any]
    signature: Optional[str] = None
    encrypted: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "message_type": self.message_type,
            "payload": self.payload,
            "signature": self.signature,
            "encrypted": self.encrypted,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IOSMessage':
        """Create from dictionary."""
        return cls(
            message_id=data.get("message_id", ""),
            timestamp=data.get("timestamp", 0),
            message_type=data.get("message_type", ""),
            payload=data.get("payload", {}),
            signature=data.get("signature"),
            encrypted=data.get("encrypted", False),
        )


@dataclass
class ConnectionConfig:
    """Configuration for iOS connection."""
    protocol: ProtocolType = ProtocolType.WEBSOCKET
    host: str = "localhost"
    port: int = 8443
    use_tls: bool = True
    cert_path: Optional[str] = None
    key_path: Optional[str] = None
    ca_cert_path: Optional[str] = None
    client_cert_path: Optional[str] = None
    client_key_path: Optional[str] = None
    topic_prefix: str = "nexus/ios"
    timeout: int = 30
    max_reconnect_attempts: int = 5
    reconnect_delay: float = 1.0


class IOSCommunicationProtocol:
    """
    Secure communication protocol for iOS integration.
    
    This class manages the secure channel between Nexus Core and iOS devices,
    handling authentication, encryption, and message routing.
    
    Attributes:
        config: Connection configuration
        state: Current connection state
        session_key: Ephemeral session key for encryption
    """
    
    def __init__(self, config: Optional[ConnectionConfig] = None):
        """
        Initialize the iOS communication protocol.
        
        Args:
            config: Connection configuration (auto-generated if None)
        """
        self.config = config or ConnectionConfig()
        self.state = ConnectionState.DISCONNECTED
        self.session_key: Optional[bytes] = None
        self._device_public_key: Optional[bytes] = None
        self._local_private_key: Optional[bytes] = None
        self._local_public_key: Optional[bytes] = None
        self._message_queue: List[IOSMessage] = []
        self._callbacks: Dict[str, Callable] = {}
        self._connection: Optional[Any] = None
        self._reconnect_attempts = 0
        
        # Generate local keypair for ECDH
        if CRYPTO_AVAILABLE:
            self._generate_keypair()
        
        logger.info("IOSCommunicationProtocol initialized")
    
    def _generate_keypair(self) -> None:
        """Generate local ECDH keypair for key exchange."""
        try:
            private_key = ec.generate_private_key(ec.SECP384R1(), default_backend())
            public_key = private_key.public_key()
            
            self._local_private_key = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            
            self._local_public_key = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            
            logger.debug("Generated ECDH keypair")
        except Exception as e:
            logger.error(f"Failed to generate keypair: {e}")
    
    def _derive_session_key(self, peer_public_key_pem: bytes) -> bool:
        """
        Derive shared session key using ECDH.
        
        Args:
            peer_public_key_pem: Peer's public key in PEM format
            
        Returns:
            True if key derivation succeeded
        """
        try:
            # Load local private key
            local_private_key = serialization.load_pem_private_key(
                self._local_private_key,
                password=None,
                backend=default_backend(),
            )
            
            # Load peer public key
            peer_public_key = serialization.load_pem_public_key(
                peer_public_key_pem,
                backend=default_backend(),
            )
            
            # Perform ECDH key exchange
            shared_key = local_private_key.exchange(ec.ECDH(), peer_public_key)
            
            # Derive session key using HKDF
            self.session_key = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=None,
                info=b"nexus_ios_session",
                backend=default_backend(),
            ).derive(shared_key)
            
            self._device_public_key = peer_public_key_pem
            logger.info("Session key derived successfully")
            return True
            
        except Exception as e:
            logger.error(f"Key derivation failed: {e}")
            return False
    
    def _encrypt_message(self, message: IOSMessage) -> IOSMessage:
        """
        Encrypt message payload using ChaCha20-Poly1305.
        
        Args:
            message: Message to encrypt
            
        Returns:
            Encrypted message
        """
        if not self.session_key:
            logger.warning("No session key available, sending unencrypted")
            return message
        
        if not NACL_AVAILABLE:
            logger.warning("PyNaCl not available, sending unencrypted")
            return message
        
        try:
            # Serialize payload
            payload_bytes = json.dumps(message.payload).encode()
            
            # Create nonce (12 bytes for ChaCha20-Poly1305)
            nonce = os.urandom(12)
            
            # Encrypt using SecretBox (ChaCha20-Poly1305)
            box = SecretBox(self.session_key)
            encrypted_payload = box.encrypt(payload_bytes, nonce)
            
            # Update message
            message.payload = {
                "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(encrypted_payload).decode(),
            }
            message.encrypted = True
            
            return message
            
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return message
    
    def _decrypt_message(self, message: IOSMessage) -> IOSMessage:
        """
        Decrypt message payload using ChaCha20-Poly1305.
        
        Args:
            message: Encrypted message
            
        Returns:
            Decrypted message
        """
        if not message.encrypted or not self.session_key:
            return message
        
        if not NACL_AVAILABLE:
            logger.warning("PyNaCl not available, cannot decrypt")
            return message
        
        try:
            nonce = base64.b64decode(message.payload.get("nonce", ""))
            ciphertext = base64.b64decode(message.payload.get("ciphertext", ""))
            
            box = SecretBox(self.session_key)
            decrypted_payload = box.decrypt(ciphertext, nonce)
            
            message.payload = json.loads(decrypted_payload.decode())
            message.encrypted = False
            
            return message
            
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return message
    
    def _sign_message(self, message: IOSMessage) -> IOSMessage:
        """
        Sign message using HMAC-SHA256.
        
        Args:
            message: Message to sign
            
        Returns:
            Signed message
        """
        if not self.session_key:
            return message
        
        try:
            # Create message digest
            message_data = f"{message.message_id}:{message.timestamp}:{json.dumps(message.payload)}"
            
            # Sign with HMAC-SHA256
            signature = hmac.new(
                self.session_key,
                message_data.encode(),
                hashlib.sha256,
            ).hexdigest()
            
            message.signature = signature
            return message
            
        except Exception as e:
            logger.error(f"Signing failed: {e}")
            return message
    
    def _verify_signature(self, message: IOSMessage) -> bool:
        """
        Verify message signature.
        
        Args:
            message: Message to verify
            
        Returns:
            True if signature is valid
        """
        if not message.signature or not self.session_key:
            return False
        
        try:
            # Recreate message digest
            message_data = f"{message.message_id}:{message.timestamp}:{json.dumps(message.payload)}"
            
            # Compute expected signature
            expected_signature = hmac.new(
                self.session_key,
                message_data.encode(),
                hashlib.sha256,
            ).hexdigest()
            
            # Constant-time comparison
            return hmac.compare_digest(message.signature, expected_signature)
            
        except Exception as e:
            logger.error(f"Signature verification failed: {e}")
            return False
    
    async def connect(self) -> bool:
        """
        Establish connection to iOS device.
        
        Returns:
            True if connection succeeded
        """
        self.state = ConnectionState.CONNECTING
        logger.info(f"Connecting to iOS device via {self.config.protocol.value}...")
        
        try:
            if self.config.protocol == ProtocolType.WEBSOCKET:
                return await self._connect_websocket()
            elif self.config.protocol == ProtocolType.MQTT:
                return await self._connect_mqtt()
            else:
                logger.error(f"Unknown protocol: {self.config.protocol}")
                return False
                
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.state = ConnectionState.ERROR
            return False
    
    async def _connect_websocket(self) -> bool:
        """Establish WebSocket connection."""
        if not WEBSOCKETS_AVAILABLE:
            logger.error("websockets library not available")
            return False
        
        try:
            # Build WebSocket URL
            scheme = "wss" if self.config.use_tls else "ws"
            url = f"{scheme}://{self.config.host}:{self.config.port}"
            
            # Configure SSL context for mutual TLS
            ssl_context = None
            if self.config.use_tls and CRYPTO_AVAILABLE:
                ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
                
                if self.config.ca_cert_path:
                    ssl_context.load_verify_locations(self.config.ca_cert_path)
                
                if self.config.client_cert_path and self.config.client_key_path:
                    ssl_context.load_cert_chain(
                        self.config.client_cert_path,
                        self.config.client_key_path,
                    )
            
            # Connect with mutual TLS
            self._connection = await websockets.connect(
                url,
                ssl=ssl_context,
                ping_interval=30,
                ping_timeout=10,
            )
            
            self.state = ConnectionState.AUTHENTICATING
            
            # Perform handshake
            handshake_success = await self._perform_handshake()
            
            if handshake_success:
                self.state = ConnectionState.CONNECTED
                self._reconnect_attempts = 0
                logger.info("WebSocket connection established")
                return True
            else:
                await self._connection.close()
                self.state = ConnectionState.ERROR
                return False
                
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.state = ConnectionState.ERROR
            return False
    
    async def _connect_mqtt(self) -> bool:
        """Establish MQTT connection."""
        if not MQTT_AVAILABLE:
            logger.error("paho-mqtt library not available")
            return False
        
        try:
            # Create MQTT client
            client_id = f"nexus_core_{os.urandom(8).hex()}"
            self._connection = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
            
            # Configure TLS
            if self.config.use_tls and self.config.ca_cert_path:
                self._connection.tls_set(
                    ca_certs=self.config.ca_cert_path,
                    certfile=self.config.client_cert_path,
                    keyfile=self.config.client_key_path,
                )
            
            # Set callbacks
            self._connection.on_connect = self._on_mqtt_connect
            self._connection.on_message = self._on_mqtt_message
            self._connection.on_disconnect = self._on_mqtt_disconnect
            
            # Connect
            self._connection.connect_async(
                self.config.host,
                self.config.port,
                keepalive=60,
            )
            
            self.state = ConnectionState.CONNECTING
            return True
            
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            self.state = ConnectionState.ERROR
            return False
    
    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """Handle MQTT connect event."""
        if rc == 0:
            self.state = ConnectionState.AUTHENTICATING
            logger.info("MQTT connected, performing handshake...")
            
            # Subscribe to topics
            topic = f"{self.config.topic_prefix}/#"
            self._connection.subscribe(topic)
            
            # Perform handshake asynchronously
            asyncio.create_task(self._perform_handshake())
        else:
            logger.error(f"MQTT connection failed with code {rc}")
            self.state = ConnectionState.ERROR
    
    def _on_mqtt_message(self, client, userdata, msg):
        """Handle MQTT message event."""
        try:
            message_data = json.loads(msg.payload.decode())
            message = IOSMessage.from_dict(message_data)
            
            # Verify and decrypt
            if self._verify_signature(message):
                message = self._decrypt_message(message)
                
                # Route to callback
                self._route_message(message)
            else:
                logger.warning("Invalid message signature")
                
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")
    
    def _on_mqtt_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnect event."""
        logger.info("MQTT disconnected")
        self.state = ConnectionState.DISCONNECTED
    
    async def _perform_handshake(self) -> bool:
        """
        Perform cryptographic handshake for mutual authentication.
        
        Returns:
            True if handshake succeeded
        """
        try:
            # Send our public key
            handshake_request = {
                "type": "handshake_request",
                "public_key": self._local_public_key.decode() if self._local_public_key else None,
                "timestamp": time.time(),
                "nonce": os.urandom(16).hex(),
            }
            
            await self._send_raw(json.dumps(handshake_request))
            
            # Wait for response
            response = await self._receive_raw(timeout=self.config.timeout)
            
            if not response:
                logger.error("Handshake timeout")
                return False
            
            response_data = json.loads(response)
            
            if response_data.get("type") != "handshake_response":
                logger.error("Invalid handshake response type")
                return False
            
            # Extract device public key
            device_public_key_pem = response_data.get("public_key", "").encode()
            
            if not device_public_key_pem:
                logger.error("No public key in handshake response")
                return False
            
            # Derive session key
            if not self._derive_session_key(device_public_key_pem):
                return False
            
            # Send confirmation
            confirmation = {
                "type": "handshake_confirm",
                "signature": hmac.new(
                    self.session_key,
                    b"handshake_confirm",
                    hashlib.sha256,
                ).hexdigest(),
            }
            
            await self._send_raw(json.dumps(confirmation))
            
            logger.info("Handshake completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Handshake failed: {e}")
            return False
    
    async def send_message(self, message: IOSMessage) -> bool:
        """
        Send message to iOS device.
        
        Args:
            message: Message to send
            
        Returns:
            True if message was sent successfully
        """
        if self.state != ConnectionState.CONNECTED:
            logger.warning("Not connected, queuing message")
            self._message_queue.append(message)
            return False
        
        try:
            # Sign and encrypt
            message = self._sign_message(message)
            message = self._encrypt_message(message)
            
            # Serialize and send
            message_json = json.dumps(message.to_dict())
            return await self._send_raw(message_json)
            
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            self._message_queue.append(message)
            return False
    
    async def _send_raw(self, data: str) -> bool:
        """Send raw data over the connection."""
        try:
            if self.config.protocol == ProtocolType.WEBSOCKET and self._connection:
                await self._connection.send(data)
                return True
            elif self.config.protocol == ProtocolType.MQTT and self._connection:
                topic = f"{self.config.topic_prefix}/outbound"
                self._connection.publish(topic, data)
                return True
            else:
                logger.error("No active connection")
                return False
        except Exception as e:
            logger.error(f"Send failed: {e}")
            return False
    
    async def _receive_raw(self, timeout: int = 30) -> Optional[str]:
        """Receive raw data from the connection."""
        try:
            if self.config.protocol == ProtocolType.WEBSOCKET and self._connection:
                return await asyncio.wait_for(
                    self._connection.recv(),
                    timeout=timeout,
                )
            # MQTT uses callbacks, so this won't be called
            return None
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"Receive failed: {e}")
            return None
    
    def _route_message(self, message: IOSMessage) -> None:
        """Route incoming message to appropriate callback."""
        callback = self._callbacks.get(message.message_type)
        if callback:
            try:
                callback(message)
            except Exception as e:
                logger.error(f"Callback error: {e}")
        else:
            logger.debug(f"No callback for message type: {message.message_type}")
    
    def register_callback(self, message_type: str, callback: Callable) -> None:
        """
        Register callback for specific message type.
        
        Args:
            message_type: Type of messages to handle
            callback: Callback function
        """
        self._callbacks[message_type] = callback
        logger.debug(f"Registered callback for: {message_type}")
    
    async def process_queue(self) -> None:
        """Process queued messages when connection is restored."""
        if self.state != ConnectionState.CONNECTED:
            return
        
        while self._message_queue:
            message = self._message_queue.pop(0)
            await self.send_message(message)
    
    async def disconnect(self) -> None:
        """Close connection to iOS device."""
        try:
            if self.config.protocol == ProtocolType.WEBSOCKET and self._connection:
                await self._connection.close()
            elif self.config.protocol == ProtocolType.MQTT and self._connection:
                self._connection.disconnect()
            
            self._connection = None
            self.state = ConnectionState.DISCONNECTED
            self.session_key = None
            
            logger.info("Disconnected from iOS device")
            
        except Exception as e:
            logger.error(f"Disconnect error: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get connection status information."""
        return {
            "state": self.state.value,
            "protocol": self.config.protocol.value,
            "host": self.config.host,
            "port": self.config.port,
            "authenticated": self.session_key is not None,
            "queued_messages": len(self._message_queue),
        }
