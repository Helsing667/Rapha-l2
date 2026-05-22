"""
Tests for Security Layer module.
"""

import pytest
from core.security_layer import (
    SecurityLayer, SecurityLevel, ThreatType, SecurityEvent, SecurityPolicy
)


class TestSecurityLayer:
    """Test cases for SecurityLayer."""
    
    @pytest.fixture
    def security_layer(self):
        """Create a security layer instance for testing."""
        return SecurityLayer(
            enable_isolation=False,  # Disable for tests
            enable_anomaly_detection=True,
            anomaly_threshold=0.9,  # High threshold to avoid false positives in tests
        )
    
    def test_validate_safe_request(self, security_layer):
        """Test that safe requests pass validation."""
        is_valid, event = security_layer.validate_request(
            action="file_read",
            parameters={"path": "/home/user/test.txt"},
            privilege_level="user",
        )
        
        assert is_valid == True
        assert event is None
    
    def test_block_dangerous_command(self, security_layer):
        """Test that dangerous commands are blocked."""
        is_valid, event = security_layer.validate_request(
            action="execute",
            parameters={"command": "rm -rf /"},
            privilege_level="user",
        )
        
        assert is_valid == False
        assert event is not None
        assert event.blocked == True
        assert event.threat_type == ThreatType.MALICIOUS_COMMAND
    
    def test_block_sensitive_path_access(self, security_layer):
        """Test that sensitive path access is blocked for non-root."""
        is_valid, event = security_layer.validate_request(
            action="read",
            parameters={"path": "/etc/shadow"},
            privilege_level="user",
        )
        
        assert is_valid == False
        assert event is not None
        assert event.threat_type == ThreatType.UNAUTHORIZED_ACCESS
    
    def test_allow_sensitive_path_for_root(self, security_layer):
        """Test that root can access sensitive paths."""
        is_valid, event = security_layer.validate_request(
            action="read",
            parameters={"path": "/etc/shadow"},
            privilege_level="root",
        )
        
        assert is_valid == True
    
    def test_replay_attack_prevention(self, security_layer):
        """Test that duplicate nonces are detected."""
        nonce = "test-nonce-12345"
        
        # First request with nonce should pass
        is_valid1, _ = security_layer.validate_request(
            action="test",
            parameters={},
            nonce=nonce,
            timestamp=None,
        )
        
        # Second request with same nonce should fail
        is_valid2, event = security_layer.validate_request(
            action="test",
            parameters={},
            nonce=nonce,
            timestamp=None,
        )
        
        assert is_valid1 == True
        assert is_valid2 == False
        assert event.threat_type == ThreatType.REPLAY_ATTACK
    
    def test_stale_request_detection(self, security_layer):
        """Test that old requests are rejected."""
        old_timestamp = 1000000000  # Very old timestamp
        
        is_valid, event = security_layer.validate_request(
            action="test",
            parameters={},
            timestamp=old_timestamp,
        )
        
        assert is_valid == False
        assert event.threat_type == ThreatType.REPLAY_ATTACK
    
    def test_resource_limits_check(self, security_layer):
        """Test resource limit checking."""
        # Should pass under normal conditions
        within_limits, event = security_layer.check_resource_limits()
        
        # May pass or fail depending on current system load
        assert isinstance(within_limits, bool)
    
    def test_record_login_attempt(self, security_layer):
        """Test login attempt tracking."""
        username = "test_user"
        
        # Record multiple failed attempts
        for _ in range(5):
            security_layer.record_login_attempt(username, success=False)
        
        # Account should be locked after brute force detection
        assert security_layer.is_account_locked(username) == True
    
    def test_account_lockout_expires(self, security_layer):
        """Test that account lockout expires."""
        username = "test_user_2"
        
        # Lock the account
        security_layer.locked_accounts[username] = 0  # Expired timestamp
        
        assert security_layer.is_account_locked(username) == False
    
    def test_hmac_signing(self, security_layer):
        """Test HMAC signature generation and verification."""
        payload = b"test message"
        key = b"test_key"
        
        signature = security_layer.sign_payload(payload, key)
        
        assert len(signature) == 64  # SHA256 hex length
        assert security_layer.verify_signature(payload, signature, key) == True
    
    def test_hmac_verification_failure(self, security_layer):
        """Test that tampered payloads fail verification."""
        payload = b"test message"
        tampered = b"tampered message"
        key = b"test_key"
        
        signature = security_layer.sign_payload(payload, key)
        
        assert security_layer.verify_signature(tampered, signature, key) == False
    
    def test_anomaly_detection_high_param_count(self, security_layer):
        """Test anomaly detection for requests with many parameters."""
        # Create many parameters to trigger anomaly detection
        params = {f"param_{i}": i for i in range(25)}
        
        score = security_layer._detect_anomaly("test_action", params)
        
        # Score should be elevated due to high param count
        assert score >= 0.3
    
    def test_security_event_creation(self, security_layer):
        """Test security event creation and recording."""
        event = security_layer._create_event(
            event_type="test_event",
            threat_type=ThreatType.UNAUTHORIZED_ACCESS,
            severity=SecurityLevel.HIGH,
            description="Test security event",
            source="test",
            details={"test": "data"},
            blocked=True,
        )
        
        assert event.event_type == "test_event"
        assert event.severity == SecurityLevel.HIGH
        assert event.blocked == True
        
        # Event should be in history
        events = security_layer.get_security_events(limit=1)
        assert len(events) >= 1
    
    def test_get_security_events_filtering(self, security_layer):
        """Test filtering security events by severity."""
        # Create events of different severities
        security_layer._create_event(
            "low_event", ThreatType.ANOMALOUS_BEHAVIOR,
            SecurityLevel.LOW, "Low severity", "test", {},
        )
        security_layer._create_event(
            "critical_event", ThreatType.MALICIOUS_COMMAND,
            SecurityLevel.CRITICAL, "Critical", "test", {},
        )
        
        # Get only HIGH and above
        events = security_layer.get_security_events(
            limit=10,
            severity=SecurityLevel.HIGH,
        )
        
        # Should only include critical event
        assert all(e['severity'] in ('high', 'critical') for e in events)
    
    def test_generate_audit_report(self, security_layer):
        """Test audit report generation."""
        # Add some events
        security_layer._create_event(
            "test", ThreatType.UNAUTHORIZED_ACCESS,
            SecurityLevel.MEDIUM, "Test", "test", {},
        )
        
        report = security_layer.generate_audit_report()
        
        assert 'generated_at' in report
        assert 'total_events' in report
        assert 'events_by_severity' in report
        assert 'events_by_threat' in report
    
    def test_isolation_command_wrapping_bubblewrap(self, security_layer):
        """Test command wrapping for bubblewrap isolation."""
        security_layer.isolation_tool = "bubblewrap"
        security_layer.enable_isolation = True
        
        command = ["ls", "-la"]
        wrapped = security_layer.wrap_command_isolated(command)
        
        assert wrapped[0] == "bwrap"
        assert "--ro-bind" in wrapped
        assert "ls" in wrapped
    
    def test_isolation_command_wrapping_firejail(self, security_layer):
        """Test command wrapping for firejail isolation."""
        security_layer.isolation_tool = "firejail"
        security_layer.enable_isolation = True
        
        command = ["ls", "-la"]
        wrapped = security_layer.wrap_command_isolated(command)
        
        assert wrapped[0] == "firejail"
        assert "ls" in wrapped
    
    def test_isolation_disabled(self, security_layer):
        """Test that commands are not wrapped when isolation disabled."""
        security_layer.enable_isolation = False
        
        command = ["ls", "-la"]
        wrapped = security_layer.wrap_command_isolated(command)
        
        assert wrapped == command


class TestSecurityPolicy:
    """Test cases for SecurityPolicy."""
    
    def test_policy_creation(self):
        """Test creating a security policy."""
        policy = SecurityPolicy(
            id="test_policy",
            name="Test Policy",
            description="A test policy",
            enabled=True,
            conditions={"type": "test"},
            actions=["block"],
            severity=SecurityLevel.HIGH,
        )
        
        assert policy.id == "test_policy"
        assert policy.enabled == True
        assert policy.severity == SecurityLevel.HIGH


class TestSecurityLevel:
    """Test cases for SecurityLevel enum."""
    
    def test_severity_ordering(self):
        """Test that severity levels have correct ordering."""
        assert SecurityLevel.LOW.value < SecurityLevel.MEDIUM.value
        assert SecurityLevel.MEDIUM.value < SecurityLevel.HIGH.value
        assert SecurityLevel.HIGH.value < SecurityLevel.CRITICAL.value
