"""
iOS Integration Layer for Nexus Core.

This module provides the foundation for secure iOS device integration,
including communication protocols, API wrappers, synchronization, and security.
All components are disabled by default and can be activated via enable_ios.sh.

Features:
- WebSocket/MQTT secure communication (WSS/MQTT over TLS)
- iOS API wrappers (Shortcuts, File Provider, Core ML)
- Bidirectional data synchronization (iCloud/NAS)
- Security sandboxing with App Attest/DeviceCheck verification
- ChaCha20-Poly1305 end-to-end encryption
- X.509 certificate-based mutual authentication
"""

__version__ = "1.0.0"
__author__ = "Nexus Core Team"

# iOS integration is disabled by default
IOS_ENABLED = False
