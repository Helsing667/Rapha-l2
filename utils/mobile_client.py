"""
Mobile Client for Nexus Core.

This module provides SSH-based communication with mobile devices
(Termux or equivalent) for remote command execution.

Features:
- SSH connection management
- JSON-RPC over SSH
- HMAC message signing
- Kill switch functionality
- Auto-reconnect
"""

import json
import time
import hashlib
import hmac
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
import logging
import threading
import socket

try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class MobileConnectionConfig:
    """Configuration for mobile connection."""
    host: str
    port: int = 22
    username: str = "u0_a123"
    key_path: Optional[str] = None
    password: Optional[str] = None
    timeout: int = 30
    keepalive_interval: int = 60
    compression: bool = True


@dataclass
class CommandResult:
    """Result of a remote command execution."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    return_code: int = -1
    error: Optional[str] = None


class MobileClient:
    """
    Client for communicating with mobile devices via SSH.
    
    This class manages SSH connections to mobile devices (Termux),
    executes commands remotely, and handles reconnection logic.
    
    Attributes:
        config: Connection configuration
        kill_switch_enabled: Whether kill switch is active
    """
    
    def __init__(
        self,
        config: MobileConnectionConfig,
        hmac_key: Optional[bytes] = None,
    ):
        """
        Initialize the Mobile Client.
        
        Args:
            config: Connection configuration
            hmac_key: Key for HMAC message signing
        """
        self.config = config
        self.hmac_key = hmac_key or b"default_key_change_me"
        
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None
        self.connected = False
        self.kill_switch_enabled = False
        
        self._lock = threading.Lock()
        self._reconnect_thread: Optional[threading.Thread] = None
        self._stop_reconnect = threading.Event()
        
        if not PARAMIKO_AVAILABLE:
            logger.warning("paramiko not available, SSH features disabled")
        
        logger.info(f"MobileClient initialized (host={config.host})")
    
    def connect(self) -> bool:
        """
        Establish SSH connection to mobile device.
        
        Returns:
            True if connection successful
        """
        if not PARAMIKO_AVAILABLE:
            logger.error("paramiko not available")
            return False
        
        if self.connected:
            return True
        
        with self._lock:
            try:
                self.client = paramiko.SSHClient()
                self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Connect with key or password
                if self.config.key_path:
                    self.client.connect(
                        hostname=self.config.host,
                        port=self.config.port,
                        username=self.config.username,
                        key_filename=self.config.key_path,
                        timeout=self.config.timeout,
                        compress=self.config.compression,
                    )
                elif self.config.password:
                    self.client.connect(
                        hostname=self.config.host,
                        port=self.config.port,
                        username=self.config.username,
                        password=self.config.password,
                        timeout=self.config.timeout,
                        compress=self.config.compression,
                    )
                else:
                    raise ValueError("No authentication method provided")
                
                # Set keepalive
                transport = self.client.get_transport()
                if transport:
                    transport.set_keepalive(self.config.keepalive_interval)
                
                # Initialize SFTP
                self.sftp = self.client.open_sftp()
                
                self.connected = True
                logger.info(f"Connected to mobile device: {self.config.host}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to connect to mobile: {e}")
                self.connected = False
                return False
    
    def disconnect(self) -> None:
        """Close the SSH connection."""
        with self._lock:
            if self.sftp:
                try:
                    self.sftp.close()
                except Exception:
                    pass
                self.sftp = None
            
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
                self.client = None
            
            self.connected = False
            logger.info("Disconnected from mobile device")
    
    def execute_command(
        self,
        command: str,
        timeout: Optional[int] = None,
    ) -> CommandResult:
        """
        Execute a command on the remote mobile device.
        
        Args:
            command: Command to execute
            timeout: Command timeout in seconds
            
        Returns:
            CommandResult with output
        """
        if self.kill_switch_enabled:
            return CommandResult(
                success=False,
                error="Kill switch activated - commands blocked",
            )
        
        if not self.connected:
            if not self.connect():
                return CommandResult(
                    success=False,
                    error="Not connected to mobile device",
                )
        
        try:
            stdin, stdout, stderr = self.client.exec_command(
                command,
                timeout=timeout or self.config.timeout,
            )
            
            output = stdout.read().decode('utf-8', errors='replace')
            error_output = stderr.read().decode('utf-8', errors='replace')
            return_code = stdout.channel.recv_exit_status()
            
            return CommandResult(
                success=return_code == 0,
                stdout=output,
                stderr=error_output,
                return_code=return_code,
            )
            
        except Exception as e:
            logger.exception(f"Command execution failed: {e}")
            return CommandResult(
                success=False,
                error=str(e),
            )
    
    def send_json_rpc(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a JSON-RPC request to the mobile device.
        
        Args:
            method: RPC method name
            params: Method parameters
            request_id: Request identifier
            
        Returns:
            RPC response dictionary
        """
        import uuid
        
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id or str(uuid.uuid4()),
        }
        
        # Sign the request
        payload = json.dumps(request, sort_keys=True)
        signature = self._sign_message(payload.encode())
        
        # Send via shell command (assuming a JSON-RPC server on mobile)
        rpc_command = f'echo "{payload}" | nc localhost 8080'
        result = self.execute_command(rpc_command)
        
        if not result.success:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": result.error},
                "id": request["id"],
            }
        
        try:
            response = json.loads(result.stdout)
            
            # Verify signature if present
            if 'signature' in response:
                received_sig = response.pop('signature')
                response_payload = json.dumps(response, sort_keys=True).encode()
                if not self._verify_signature(response_payload, received_sig):
                    return {
                        "jsonrpc": "2.0",
                        "error": {"code": -32001, "message": "Invalid signature"},
                        "id": request["id"],
                    }
            
            return response
            
        except json.JSONDecodeError:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": request["id"],
            }
    
    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """
        Upload a file to the mobile device.
        
        Args:
            local_path: Local file path
            remote_path: Remote destination path
            
        Returns:
            True if upload successful
        """
        if not self.connected:
            if not self.connect():
                return False
        
        try:
            self.sftp.put(local_path, remote_path)
            logger.info(f"Uploaded file: {local_path} -> {remote_path}")
            return True
        except Exception as e:
            logger.error(f"File upload failed: {e}")
            return False
    
    def download_file(self, remote_path: str, local_path: str) -> bool:
        """
        Download a file from the mobile device.
        
        Args:
            remote_path: Remote file path
            local_path: Local destination path
            
        Returns:
            True if download successful
        """
        if not self.connected:
            if not self.connect():
                return False
        
        try:
            self.sftp.get(remote_path, local_path)
            logger.info(f"Downloaded file: {remote_path} -> {local_path}")
            return True
        except Exception as e:
            logger.error(f"File download failed: {e}")
            return False
    
    def activate_kill_switch(self) -> None:
        """Activate the kill switch to block all commands."""
        self.kill_switch_enabled = True
        logger.critical("KILL SWITCH ACTIVATED - All commands blocked")
    
    def deactivate_kill_switch(self) -> None:
        """Deactivate the kill switch."""
        self.kill_switch_enabled = False
        logger.info("Kill switch deactivated")
    
    def _sign_message(self, message: bytes) -> str:
        """Sign a message with HMAC-SHA256."""
        return hmac.new(self.hmac_key, message, hashlib.sha256).hexdigest()
    
    def _verify_signature(self, message: bytes, signature: str) -> bool:
        """Verify an HMAC signature."""
        expected = self._sign_message(message)
        return hmac.compare_digest(expected, signature)
    
    def start_auto_reconnect(self, interval: int = 30) -> None:
        """
        Start automatic reconnection thread.
        
        Args:
            interval: Reconnection check interval in seconds
        """
        self._stop_reconnect.clear()
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop,
            args=(interval,),
            daemon=True,
        )
        self._reconnect_thread.start()
        logger.info(f"Auto-reconnect started (interval={interval}s)")
    
    def stop_auto_reconnect(self) -> None:
        """Stop the auto-reconnection thread."""
        self._stop_reconnect.set()
        if self._reconnect_thread:
            self._reconnect_thread.join(timeout=5)
            self._reconnect_thread = None
        logger.info("Auto-reconnect stopped")
    
    def _reconnect_loop(self, interval: int) -> None:
        """Background reconnection loop."""
        while not self._stop_reconnect.is_set():
            if not self.connected:
                logger.info("Attempting auto-reconnect...")
                self.connect()
            
            self._stop_reconnect.wait(interval)
    
    def get_device_info(self) -> Dict[str, Any]:
        """
        Get information about the connected mobile device.
        
        Returns:
            Device information dictionary
        """
        if not self.connected:
            return {"error": "Not connected"}
        
        info = {}
        
        # Get hostname
        result = self.execute_command("hostname")
        if result.success:
            info["hostname"] = result.stdout.strip()
        
        # Get Android version
        result = self.execute_command("getprop ro.build.version.release")
        if result.success:
            info["android_version"] = result.stdout.strip()
        
        # Get Termux info
        result = self.execute_command("echo $TERMUX_VERSION")
        if result.success:
            info["termux_version"] = result.stdout.strip()
        
        # Get uptime
        result = self.execute_command("uptime")
        if result.success:
            info["uptime"] = result.stdout.strip()
        
        return info
    
    def __enter__(self) -> "MobileClient":
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.disconnect()
