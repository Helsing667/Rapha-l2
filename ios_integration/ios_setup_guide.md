# iOS Integration Setup Guide for Nexus Core

This guide explains how to activate and configure the iOS integration module for Nexus Core, enabling secure communication and functionality between your Linux computer and iPhone.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Architecture](#architecture)
4. [Activation Steps](#activation-steps)
5. [Certificate Generation](#certificate-generation)
6. [iOS App Configuration](#ios-app-configuration)
7. [Testing & Validation](#testing--validation)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The iOS integration layer provides:
- **Secure Communication**: WebSocket Secure (WSS) or MQTT over TLS with mutual authentication
- **iOS API Access**: Shortcuts, File Provider, Core ML, Camera, Reminders, Photos
- **Data Synchronization**: Bidirectional sync via iCloud Drive or NAS
- **Security Features**: App Attest verification, DeviceCheck, sandboxing, emergency revocation

**Important**: The iOS module is **disabled by default** to avoid impacting Linux performance or security.

---

## Prerequisites

### On Linux (Nexus Core Host)

```bash
# Required Python packages
pip install websockets paho-mqtt cryptography pynacl

# Optional: For better isolation
sudo apt install bubblewrap  # or firejail
```

### On iPhone

- iOS 15 or later
- Xcode (for building the iOS app)
- Apple Developer Account (for App Store distribution or TestFlight)

### Network Requirements

- Both devices on the same network (for local connection), OR
- Configured port forwarding for remote access
- TLS certificates for secure communication

---

## Architecture

```
┌─────────────────┐                    ┌─────────────────┐
│   Linux Host    │                    │     iPhone      │
│  (Nexus Core)   │◄──── WSS/MQTT ───►│  (Nexus iOS)    │
│                 │     TLS + ECDH     │                 │
├─────────────────┤                    ├─────────────────┤
│ - Intent Parser │                    │ - Shortcuts     │
│ - Orchestrator  │                    │ - File Provider │
│ - Exec Engine   │                    │ - Core ML       │
│ - iOS Comm      │                    │ - Camera        │
│ - iOS Security  │                    │ - Reminders     │
└─────────────────┘                    └─────────────────┘
         │                                      │
         └────────── iCloud / NAS ──────────────┘
              (Sync Intermediary)
```

---

## Activation Steps

### Step 1: Run the Enable Script

```bash
cd /workspace
./enable_ios.sh
```

This script will:
- Verify prerequisites
- Generate RSA 4096-bit keypair
- Create self-signed certificates
- Update configuration files
- Start the iOS communication service

### Step 2: Configure Connection Settings

Edit `config.yaml`:

```yaml
ios:
  enabled: true
  protocol: "websocket"  # or "mqtt"
  host: "0.0.0.0"
  port: 8443
  use_tls: true
  cert_path: "/path/to/server.crt"
  key_path: "/path/to/server.key"
  ca_cert_path: "/path/to/ca.crt"
  pending_dir: "~/nexus_core/ios_pending"
```

### Step 3: Start the iOS Service

```bash
python -m ios_integration.server
```

---

## Certificate Generation

### Option A: Using the Enable Script (Recommended)

```bash
./enable_ios.sh --generate-certs
```

### Option B: Manual Generation

```bash
# Generate CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 365 -out ca.crt

# Generate Server Certificate
openssl genrsa -out server.key 4096
openssl req -new -key server.key -out server.csr
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365 -sha256

# Generate Client Certificate (for iOS app)
openssl genrsa -out client.key 4096
openssl req -new -key client.key -out client.csr
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365 -sha256
```

### Certificate Distribution

Copy `ca.crt` and `client.crt`/`client.key` to your iOS device securely:

```bash
# Via secure SCP (replace IP)
scp ca.crt client.crt client.key user@iphone_ip:/tmp/
```

---

## iOS App Configuration

### Building the iOS App

1. Open `ios_app/NexusCore.xcodeproj` in Xcode
2. Configure signing with your Apple Developer account
3. Add required capabilities:
   - Background Modes (for persistent connection)
   - App Groups (for file sharing)
   - Keychain Sharing (for secure storage)

### Required Entitlements

```xml
<!-- entitlements.plist -->
<dict>
    <key>com.apple.developer.applesignin</key>
    <array>
        <string>Default</string>
    </array>
    <key>com.apple.developer.devicecheck.appattest-environment</key>
    <string>production</string>
    <key>com.apple.security.application-groups</key>
    <array>
        <string>group.com.nexuscore.sync</string>
    </array>
</dict>
```

### Configuring the iOS App

In the iOS app settings:
1. Enter the Linux host IP address
2. Import the CA certificate
3. Import the client certificate
4. Test connection

---

## Testing & Validation

### Connection Test

```bash
# From Linux
python -c "from ios_integration import ios_communication; print('iOS module loaded')"

# Check status
python -c "from ios_integration.ios_stubs import get_ios_stubs; print(get_ios_stubs().get_status())"
```

### End-to-End Test

1. **File Transfer Test**:
   ```bash
   # Place a test file
   echo "test" > ~/nexus_core/ios_pending/test.txt
   
   # On iOS app, check if file appears in sync folder
   ```

2. **Command Test**:
   ```bash
   # Send a test command
   python -c "from ios_integration.ios_sync import IOSSync; sync = IOSSync(); import asyncio; asyncio.run(sync.sync_command('test', {}))"
   ```

3. **Security Test**:
   ```bash
   # Verify certificates
   openssl verify -CAfile ca.crt server.crt
   openssl verify -CAfile ca.crt client.crt
   ```

### Running the Test Suite

```bash
cd /workspace
python -m pytest tests/test_ios_integration.py -v
```

---

## Troubleshooting

### Common Issues

#### 1. Connection Refused

**Symptoms**: iOS app cannot connect to Linux host

**Solutions**:
- Check firewall: `sudo ufw allow 8443/tcp`
- Verify host is listening: `netstat -tlnp | grep 8443`
- Ensure TLS certificates are valid

#### 2. Certificate Errors

**Symptoms**: "Certificate not trusted" errors

**Solutions**:
- Reinstall CA certificate on iOS device
- Check certificate expiration: `openssl x509 -in cert.crt -text -noout`
- Regenerate certificates if needed

#### 3. Sync Not Working

**Symptoms**: Files not appearing on other device

**Solutions**:
- Check pending directory permissions: `ls -la ~/nexus_core/ios_pending/`
- Verify sync method configuration (iCloud vs NAS)
- Check logs: `tail -f ~/nexus_core/ios_pending/ios_requests.log`

#### 4. App Attest Fails

**Symptoms**: Device verification fails

**Solutions**:
- Ensure iOS app has App Attest capability enabled
- Check Apple Developer portal for proper provisioning
- Verify device is not revoked

### Logs Location

- **iOS Requests Log**: `~/nexus_core/ios_pending/ios_requests.log`
- **Nexus Core Logs**: `/var/log/nexus/operations.log`
- **Security Events**: `/var/log/nexus/audit.log`

### Getting Help

If issues persist:
1. Check the GitHub issues page
2. Review the full documentation at `docs/ios_integration.md`
3. Contact support with logs attached

---

## Security Considerations

### Before Production Use

- [ ] Replace self-signed certificates with CA-signed certificates
- [ ] Enable certificate pinning in iOS app
- [ ] Configure proper firewall rules
- [ ] Set up certificate rotation schedule
- [ ] Test emergency revocation procedure

### Best Practices

1. **Never commit private keys** to version control
2. **Rotate certificates** every 90 days
3. **Monitor logs** for suspicious activity
4. **Use strong passwords** for key encryption
5. **Keep iOS app updated** with latest security patches

---

## Appendix: Configuration Reference

### Full iOS Configuration (config.yaml)

```yaml
ios:
  # Module activation
  enabled: false  # Set to true after setup
  
  # Communication settings
  protocol: "websocket"  # websocket or mqtt
  host: "0.0.0.0"
  port: 8443
  use_tls: true
  
  # TLS certificates
  cert_path: "~/.nexus_core/certs/server.crt"
  key_path: "~/.nexus_core/certs/server.key"
  ca_cert_path: "~/.nexus_core/certs/ca.crt"
  client_cert_path: "~/.nexus_core/certs/client.crt"
  client_key_path: "~/.nexus_core/certs/client.key"
  
  # MQTT specific (if using MQTT)
  mqtt_topic_prefix: "nexus/ios"
  
  # Synchronization
  sync_method: "nas"  # nas, icloud, or direct
  sync_direction: "bidirectional"
  conflict_resolution: "newest_wins"
  nas_path: "/mnt/nas/nexus_sync"
  icloud_path: "~/Library/Mobile Documents/com~apple~CloudDocs/nexus_sync"
  
  # Pending transfers
  pending_dir: "~/nexus_core/ios_pending"
  
  # Security
  enable_attestation: true
  enable_device_check: true
  enable_sandboxing: true
  max_reconnect_attempts: 5
  session_timeout_minutes: 60
  
  # Resource quotas
  quotas:
    max_cpu_percent: 50
    max_memory_mb: 512
    max_network_kb_per_min: 10240
```

---

*Last updated: 2024*
*Nexus Core iOS Integration v1.0.0*
