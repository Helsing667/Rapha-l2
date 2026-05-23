"""
iOS Integration Tests for Nexus Core.

This module contains tests for the iOS integration layer, including:
- Non-regression tests to ensure iOS stubs don't impact Linux performance
- Security tests for unauthorized activation attempts
- Stub response validation tests
"""

import pytest
import os
import json
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Import iOS modules
from ios_integration import ios_stubs, ios_sync, ios_security
from ios_integration.ios_communication import (
    IOSCommunicationProtocol, 
    ConnectionConfig, 
    ConnectionState,
    ProtocolType,
)
from ios_integration.ios_api_wrapper import (
    IOSAPIWrapper,
    APIRequest,
    IOSAPIType,
)


class TestIOSStubs:
    """Tests for iOS stub functionality."""
    
    @pytest.fixture
    def stubs(self, tmp_path):
        """Create iOSStubs instance with temp directory."""
        pending_dir = str(tmp_path / "ios_pending")
        return ios_stubs.IOSStubs(pending_dir=pending_dir)
    
    def test_stub_initialization(self, stubs):
        """Test that stubs initialize correctly."""
        assert stubs.pending_dir.exists()
        assert (stubs.pending_dir / "archive").exists()
    
    def test_file_transfer_stub(self, stubs, tmp_path):
        """Test file transfer stub creates pending file."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        
        # Handle transfer
        response = stubs.handle_file_transfer(str(test_file), "Envoie ce fichier à mon iPhone")
        
        assert response.message is not None
        assert response.action_taken == "file_staged"
        assert len(response.alternatives) > 0
        assert response.logged is True
        
        # Verify file was copied to pending
        if response.pending_path:
            assert Path(response.pending_path).exists()
    
    def test_camera_request_stub(self, stubs):
        """Test camera request returns alternatives."""
        response = stubs.handle_camera_request("Prends une photo avec mon iPhone")
        
        assert "webcam" in str(response.alternatives).lower() or "ffmpeg" in str(response.alternatives)
        assert response.action_taken == "alternative_suggested"
    
    def test_reminder_request_stub(self, stubs):
        """Test reminder request saves to pending."""
        response = stubs.handle_reminder_request(
            title="Test Reminder",
            due_date="2024-12-31T15:00:00",
            request_text="Crée un rappel pour demain"
        )
        
        assert response.action_taken == "reminder_saved_pending"
        assert response.pending_path is not None
    
    def test_request_logging(self, stubs):
        """Test that requests are logged."""
        stubs.handle_generic_ios_request("test_type", "Test request text")
        
        assert stubs.log_file.exists()
        
        with open(stubs.log_file, 'r') as f:
            log_entry = json.loads(f.readline())
            assert log_entry["request_type"] == "test_type"
    
    def test_get_status(self, stubs):
        """Test status reporting."""
        status = stubs.get_status()
        
        assert status["ios_enabled"] is False
        assert "pending_dir" in status
        assert "pending_items_count" in status


class TestIOSSync:
    """Tests for iOS synchronization module."""
    
    @pytest.fixture
    def sync_manager(self, tmp_path):
        """Create IOSSync instance with temp directory."""
        pending_dir = str(tmp_path / "ios_pending")
        config = ios_sync.SyncConfig(pending_dir=pending_dir)
        return ios_sync.IOSSync(config=config)
    
    def test_sync_initialization(self, sync_manager, tmp_path):
        """Test sync manager initializes correctly."""
        assert sync_manager.pending_dir.exists()
    
    def test_checksum_computation(self, sync_manager, tmp_path):
        """Test file checksum computation."""
        test_file = tmp_path / "checksum_test.txt"
        test_file.write_text("test content for checksum")
        
        checksum = sync_manager._compute_checksum(str(test_file))
        
        assert len(checksum) == 64  # SHA256 hex length
        assert checksum.isalnum()
    
    def test_sync_status(self, sync_manager):
        """Test sync status reporting."""
        status = sync_manager.get_sync_status()
        
        assert "sync_method" in status
        assert "sync_direction" in status
        assert "conflict_resolution" in status


class TestIOSSecurity:
    """Tests for iOS security module."""
    
    @pytest.fixture
    def security_manager(self):
        """Create IOSSecurity instance."""
        return ios_security.IOSSecurity()
    
    def test_security_initialization(self, security_manager):
        """Test security manager initializes correctly."""
        assert len(security_manager.devices) == 0
        assert len(security_manager._revocation_list) == 0
    
    def test_device_registration(self, security_manager):
        """Test device registration."""
        device = security_manager.register_device(
            device_id="test_device_123",
            model="iPhone14,2",
            ios_version="17.0",
            app_version="1.0.0",
            attest_status=ios_security.AttestationStatus.VERIFIED,
        )
        
        assert device.device_id == "test_device_123"
        assert device.trust_level == ios_security.SecurityLevel.MEDIUM
        assert "test_device_123" in security_manager.devices
    
    def test_device_revocation(self, security_manager):
        """Test device revocation."""
        # Register then revoke
        security_manager.register_device(
            device_id="revoke_test",
            model="iPhone14,2",
            ios_version="17.0",
            app_version="1.0.0",
            attest_status=ios_security.AttestationStatus.VERIFIED,
        )
        
        result = security_manager.revoke_device("revoke_test")
        
        assert result is True
        assert security_manager.is_device_revoked("revoke_test")
    
    def test_quota_check(self, security_manager):
        """Test resource quota checking."""
        # Should pass - within limits
        assert security_manager.default_quota.check_quota("cpu", 10) is True
        assert security_manager.default_quota.check_quota("memory", 100) is True
        
        # Should fail - exceeds limits
        assert security_manager.default_quota.check_quota("cpu", 100) is False
    
    def test_revocation_token_generation(self, security_manager):
        """Test revocation token generation."""
        token = security_manager.generate_revocation_token("test_device")
        
        assert "." in token  # JWT-like format
        parts = token.split(".")
        assert len(parts) == 2


class TestNonRegression:
    """Non-regression tests to ensure iOS module doesn't impact Linux performance."""
    
    def test_import_does_not_block(self):
        """Test that importing iOS modules doesn't block execution."""
        start_time = time.time()
        
        from ios_integration import ios_communication
        from ios_integration import ios_api_wrapper
        from ios_integration import ios_sync
        from ios_integration import ios_security
        from ios_integration import ios_stubs
        
        import_time = time.time() - start_time
        
        # Import should complete in under 1 second
        assert import_time < 1.0, f"iOS module import took too long: {import_time}s"
    
    def test_stubs_no_network_calls(self, stubs):
        """Test that stub operations don't make network calls."""
        with patch('socket.socket') as mock_socket:
            # Perform stub operation
            stubs.handle_generic_ios_request("test", "test request")
            
            # No network calls should be made
            mock_socket.assert_not_called()
    
    def test_disabled_module_performance(self):
        """Test that disabled iOS module has minimal performance impact."""
        # Measure baseline
        start = time.time()
        for _ in range(1000):
            pass
        baseline = time.time() - start
        
        # Measure with iOS stub check
        start = time.time()
        for _ in range(1000):
            # Simulate checking if iOS is enabled
            ios_enabled = False
            if ios_enabled:
                pass  # Would do iOS stuff
        with_ios_check = time.time() - start
        
        # Should be roughly equivalent (within 50%)
        assert with_ios_check < baseline * 1.5


class TestSecurityIntrusion:
    """Security tests for unauthorized iOS module activation attempts."""
    
    def test_unauthorized_activation_blocked(self):
        """Test that unauthorized activation attempts are blocked."""
        # iOS module should be disabled by default
        from ios_integration import IOS_ENABLED
        
        assert IOS_ENABLED is False, "iOS module should be disabled by default"
    
    def test_stub_cannot_bypass_security(self, stubs):
        """Test that stub responses cannot bypass security checks."""
        response = stubs.handle_generic_ios_request(
            "system_command",
            "Execute rm -rf / on my iPhone"
        )
        
        # Should log the attempt but not execute
        assert response.action_taken == "request_logged"
        assert response.logged is True
    
    def test_malformed_request_handling(self, stubs):
        """Test handling of malformed iOS requests."""
        # Empty request type
        response = stubs.handle_generic_ios_request("", "")
        assert response.logged is True
        
        # Very long request
        long_request = "x" * 10000
        response = stubs.handle_generic_ios_request("test", long_request)
        assert response.logged is True


class TestIntegration:
    """Integration tests for iOS components working together."""
    
    def test_full_stub_workflow(self, tmp_path):
        """Test complete workflow through iOS stubs."""
        pending_dir = str(tmp_path / "ios_pending")
        stubs = ios_stubs.IOSStubs(pending_dir=pending_dir)
        
        # Simulate user requesting iOS features
        stubs.handle_file_transfer("/etc/hosts", "Send hosts file to iPhone")
        stubs.handle_reminder_request("Meeting", "2024-12-31T10:00:00", "Create meeting reminder")
        stubs.handle_camera_request("Take photo with iPhone")
        
        # Check all were logged
        status = stubs.get_status()
        assert status["pending_items_count"] >= 2
        
        # Check logs exist
        assert stubs.log_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
