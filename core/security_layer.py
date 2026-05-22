"""
Security Layer Module for Nexus Core.

This module provides comprehensive security monitoring, policy enforcement,
and anomaly detection for all operations in Nexus Core.

Features:
- Security policy enforcement
- Anomaly detection with ML
- Resource limit monitoring
- Audit logging
- Isolation management (bubblewrap/firejail)
"""

import os
import time
import hashlib
import hmac
import json
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging
import subprocess
import threading
from collections import deque

import psutil

logger = logging.getLogger(__name__)


class SecurityLevel(Enum):
    """Security levels for operations."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ThreatType(Enum):
    """Types of security threats."""
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    MALICIOUS_COMMAND = "malicious_command"
    DATA_EXFILTRATION = "data_exfiltration"
    REPLAY_ATTACK = "replay_attack"
    ANOMALOUS_BEHAVIOR = "anomalous_behavior"


@dataclass
class SecurityEvent:
    """Represents a security-related event."""
    timestamp: datetime
    event_type: str
    threat_type: Optional[ThreatType]
    severity: SecurityLevel
    description: str
    source: str
    details: Dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "threat_type": self.threat_type.value if self.threat_type else None,
            "severity": self.severity.value,
            "description": self.description,
            "source": self.source,
            "details": self.details,
            "blocked": self.blocked,
        }


@dataclass
class SecurityPolicy:
    """Defines a security policy rule."""
    id: str
    name: str
    description: str
    enabled: bool = True
    conditions: Dict[str, Any] = field(default_factory=dict)
    actions: List[str] = field(default_factory=list)
    severity: SecurityLevel = SecurityLevel.MEDIUM


class SecurityLayer:
    """
    Central security layer for Nexus Core.
    
    This class enforces security policies, monitors for anomalies,
    manages isolation, and maintains audit logs.
    
    Attributes:
        enable_isolation: Whether to use container isolation
        enable_anomaly_detection: Whether to run anomaly detection
        anomaly_threshold: Threshold for anomaly scoring
        resource_limits: Dictionary of resource limits
    """
    
    # Dangerous command patterns to block
    DANGEROUS_PATTERNS = [
        'rm -rf /',
        'rm -rf /*',
        'mkfs',
        'dd if=/dev/zero',
        ':(){:|:&};:',  # Fork bomb
        'chmod -R 777 /',
        'chown -R root:root /',
        'wget.*\\|.*sh',
        'curl.*\\|.*bash',
    ]
    
    # Sensitive paths that require extra protection
    SENSITIVE_PATHS = [
        '/etc/passwd',
        '/etc/shadow',
        '/etc/sudoers',
        '/root',
        '/boot',
        '/proc',
        '/sys',
    ]
    
    def __init__(
        self,
        enable_isolation: bool = True,
        enable_anomaly_detection: bool = True,
        anomaly_threshold: float = 0.85,
        isolation_tool: str = "bubblewrap",
        resource_limits: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the Security Layer.
        
        Args:
            enable_isolation: Enable container isolation
            enable_anomaly_detection: Enable ML-based anomaly detection
            anomaly_threshold: Threshold for flagging anomalies
            isolation_tool: Tool to use for isolation (bubblewrap/firejail)
            resource_limits: Resource limit configuration
        """
        self.enable_isolation = enable_isolation
        self.enable_anomaly_detection = enable_anomaly_detection
        self.anomaly_threshold = anomaly_threshold
        self.isolation_tool = isolation_tool
        
        self.resource_limits = resource_limits or {
            'max_cpu_percent': 80,
            'max_memory_mb': 4096,
            'max_processes': 50,
            'max_open_files': 1024,
        }
        
        # Security state
        self.policies: Dict[str, SecurityPolicy] = {}
        self.events: deque = deque(maxlen=10000)
        self.blocked_hashes: Set[str] = set()
        self.request_nonces: Set[str] = set()
        self.login_attempts: Dict[str, List[float]] = {}
        self.locked_accounts: Dict[str, float] = {}
        
        # Anomaly detection state
        self.behavior_history: deque = deque(maxlen=1000)
        self.baseline_metrics: Dict[str, float] = {}
        
        # Thread lock for thread-safe operations
        self._lock = threading.RLock()
        
        # Initialize default policies
        self._init_default_policies()
        
        logger.info(
            f"SecurityLayer initialized (isolation={enable_isolation}, "
            f"anomaly_detection={enable_anomaly_detection})"
        )
    
    def _init_default_policies(self) -> None:
        """Initialize default security policies."""
        default_policies = [
            SecurityPolicy(
                id="policy_001",
                name="Block Dangerous Commands",
                description="Prevent execution of known dangerous commands",
                conditions={"pattern_match": self.DANGEROUS_PATTERNS},
                actions=["block", "alert"],
                severity=SecurityLevel.CRITICAL,
            ),
            SecurityPolicy(
                id="policy_002",
                name="Protect Sensitive Paths",
                description="Require elevated approval for sensitive path access",
                conditions={"paths": self.SENSITIVE_PATHS},
                actions=["require_confirmation", "audit"],
                severity=SecurityLevel.HIGH,
            ),
            SecurityPolicy(
                id="policy_003",
                name="Resource Limit Enforcement",
                description="Enforce resource usage limits",
                conditions={"type": "resource"},
                actions=["throttle", "alert"],
                severity=SecurityLevel.MEDIUM,
            ),
            SecurityPolicy(
                id="policy_004",
                name="Replay Attack Prevention",
                description="Detect and block replay attacks using nonces",
                conditions={"type": "nonce_check"},
                actions=["block", "alert"],
                severity=SecurityLevel.HIGH,
            ),
        ]
        
        for policy in default_policies:
            self.policies[policy.id] = policy
    
    def validate_request(
        self,
        action: str,
        parameters: Dict[str, Any],
        privilege_level: str = "user",
        nonce: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> tuple[bool, Optional[SecurityEvent]]:
        """
        Validate a request against security policies.
        
        Args:
            action: The action being requested
            parameters: Action parameters
            privilege_level: Requested privilege level
            nonce: Unique nonce for replay prevention
            timestamp: Request timestamp
            
        Returns:
            Tuple of (is_valid, security_event)
        """
        with self._lock:
            # Check for replay attack
            if nonce:
                if nonce in self.request_nonces:
                    event = self._create_event(
                        "replay_attack_detected",
                        ThreatType.REPLAY_ATTACK,
                        SecurityLevel.HIGH,
                        f"Duplicate nonce detected: {nonce[:16]}...",
                        "request_validation",
                        {"nonce": nonce[:32]},
                        blocked=True,
                    )
                    return False, event
                
                self.request_nonces.add(nonce)
                # Clean old nonces periodically
                if len(self.request_nonces) > 10000:
                    self.request_nonces.clear()
            
            # Check timestamp for freshness
            if timestamp:
                age = time.time() - timestamp
                if age > 300:  # 5 minutes
                    event = self._create_event(
                        "stale_request",
                        ThreatType.REPLAY_ATTACK,
                        SecurityLevel.MEDIUM,
                        f"Request too old: {age:.0f}s",
                        "request_validation",
                        {"age_seconds": age},
                        blocked=True,
                    )
                    return False, event
            
            # Check against dangerous patterns
            command = parameters.get('command', '') or parameters.get('path', '')
            if command:
                for pattern in self.DANGEROUS_PATTERNS:
                    if pattern.lower() in command.lower():
                        event = self._create_event(
                            "dangerous_command_blocked",
                            ThreatType.MALICIOUS_COMMAND,
                            SecurityLevel.CRITICAL,
                            f"Dangerous pattern detected: {pattern}",
                            "command_validation",
                            {"command": command[:100], "pattern": pattern},
                            blocked=True,
                        )
                        return False, event
            
            # Check sensitive paths
            path = parameters.get('path', '')
            if path:
                for sensitive_path in self.SENSITIVE_PATHS:
                    if path.startswith(sensitive_path):
                        event = self._create_event(
                            "sensitive_path_access",
                            ThreatType.UNAUTHORIZED_ACCESS,
                            SecurityLevel.HIGH,
                            f"Access to sensitive path: {path}",
                            "path_validation",
                            {"path": path, "privilege_level": privilege_level},
                            blocked=(privilege_level != "root"),
                        )
                        if privilege_level != "root":
                            return False, event
            
            # Run anomaly detection
            if self.enable_anomaly_detection:
                anomaly_score = self._detect_anomaly(action, parameters)
                if anomaly_score > self.anomaly_threshold:
                    event = self._create_event(
                        "anomalous_behavior",
                        ThreatType.ANOMALOUS_BEHAVIOR,
                        SecurityLevel.HIGH,
                        f"Anomaly score {anomaly_score:.2f} exceeds threshold",
                        "anomaly_detection",
                        {"score": anomaly_score, "action": action},
                        blocked=True,
                    )
                    return False, event
            
            # All checks passed
            return True, None
    
    def check_resource_limits(self) -> tuple[bool, Optional[SecurityEvent]]:
        """
        Check if current resource usage is within limits.
        
        Returns:
            Tuple of (within_limits, security_event)
        """
        process = psutil.Process(os.getpid())
        
        # Check CPU usage
        cpu_percent = process.cpu_percent()
        if cpu_percent > self.resource_limits['max_cpu_percent']:
            event = self._create_event(
                "cpu_limit_exceeded",
                ThreatType.RESOURCE_EXHAUSTION,
                SecurityLevel.MEDIUM,
                f"CPU usage {cpu_percent:.1f}% exceeds limit",
                "resource_monitor",
                {"cpu_percent": cpu_percent, "limit": self.resource_limits['max_cpu_percent']},
            )
            return False, event
        
        # Check memory usage
        memory_mb = process.memory_info().rss / 1024 / 1024
        if memory_mb > self.resource_limits['max_memory_mb']:
            event = self._create_event(
                "memory_limit_exceeded",
                ThreatType.RESOURCE_EXHAUSTION,
                SecurityLevel.MEDIUM,
                f"Memory usage {memory_mb:.0f}MB exceeds limit",
                "resource_monitor",
                {"memory_mb": memory_mb, "limit": self.resource_limits['max_memory_mb']},
            )
            return False, event
        
        # Check process count
        num_threads = process.num_threads()
        if num_threads > self.resource_limits['max_processes']:
            event = self._create_event(
                "process_limit_exceeded",
                ThreatType.RESOURCE_EXHAUSTION,
                SecurityLevel.MEDIUM,
                f"Thread count {num_threads} exceeds limit",
                "resource_monitor",
                {"threads": num_threads, "limit": self.resource_limits['max_processes']},
            )
            return False, event
        
        return True, None
    
    def wrap_command_isolated(self, command: List[str]) -> List[str]:
        """
        Wrap a command for isolated execution.
        
        Args:
            command: Command and arguments as list
            
        Returns:
            Wrapped command for isolated execution
        """
        if not self.enable_isolation:
            return command
        
        if self.isolation_tool == "bubblewrap":
            # bubblewrap command for isolation
            wrapped = [
                "bwrap",
                "--ro-bind", "/", "/",
                "--dev", "/dev",
                "--proc", "/proc",
                "--unshare-pid",
                "--unshare-net",
                "--new-session",
            ] + command
            return wrapped
        
        elif self.isolation_tool == "firejail":
            wrapped = ["firejail", "--quiet"] + command
            return wrapped
        
        return command
    
    def record_login_attempt(self, username: str, success: bool) -> None:
        """
        Record a login attempt for rate limiting.
        
        Args:
            username: Username attempted
            success: Whether login was successful
        """
        with self._lock:
            now = time.time()
            
            if username not in self.login_attempts:
                self.login_attempts[username] = []
            
            self.login_attempts[username].append(now)
            
            # Keep only last hour of attempts
            cutoff = now - 3600
            self.login_attempts[username] = [
                t for t in self.login_attempts[username] if t > cutoff
            ]
            
            # Check for brute force
            recent_attempts = self.login_attempts[username][-5:]
            if len(recent_attempts) >= 5:
                time_span = recent_attempts[-1] - recent_attempts[0]
                if time_span < 300:  # 5 attempts in 5 minutes
                    self.locked_accounts[username] = now + 900  # Lock for 15 minutes
                    self._create_event(
                        "brute_force_detected",
                        ThreatType.UNAUTHORIZED_ACCESS,
                        SecurityLevel.HIGH,
                        f"Brute force detected for user: {username}",
                        "login_monitor",
                        {"attempts": len(recent_attempts), "time_span": time_span},
                        blocked=True,
                    )
    
    def is_account_locked(self, username: str) -> bool:
        """
        Check if an account is locked.
        
        Args:
            username: Username to check
            
        Returns:
            True if account is locked
        """
        with self._lock:
            if username not in self.locked_accounts:
                return False
            
            if time.time() > self.locked_accounts[username]:
                del self.locked_accounts[username]
                return False
            
            return True
    
    def sign_payload(self, payload: bytes, key: bytes) -> str:
        """
        Sign a payload with HMAC-SHA256.
        
        Args:
            payload: Data to sign
            key: Signing key
            
        Returns:
            Hex-encoded signature
        """
        signature = hmac.new(key, payload, hashlib.sha256).hexdigest()
        return signature
    
    def verify_signature(self, payload: bytes, signature: str, key: bytes) -> bool:
        """
        Verify an HMAC-SHA256 signature.
        
        Args:
            payload: Original data
            signature: Signature to verify
            key: Verification key
            
        Returns:
            True if signature is valid
        """
        expected = self.sign_payload(payload, key)
        return hmac.compare_digest(expected, signature)
    
    def _detect_anomaly(self, action: str, parameters: Dict[str, Any]) -> float:
        """
        Detect anomalous behavior using simple heuristics.
        
        In production, this would use ML models (scikit-learn, TensorFlow Lite).
        
        Args:
            action: Action being performed
            parameters: Action parameters
            
        Returns:
            Anomaly score between 0.0 and 1.0
        """
        score = 0.0
        
        # Record behavior
        behavior = {
            "action": action,
            "timestamp": time.time(),
            "param_count": len(parameters),
        }
        self.behavior_history.append(behavior)
        
        # Simple heuristic-based anomaly detection
        # High number of parameters might indicate complex attack
        if len(parameters) > 20:
            score += 0.3
        
        # Unusual actions
        unusual_actions = ['delete', 'format', 'destroy', 'wipe']
        if any(a in action.lower() for a in unusual_actions):
            score += 0.2
        
        # Rapid-fire requests
        if len(self.behavior_history) >= 10:
            recent = list(self.behavior_history)[-10:]
            time_span = recent[-1]['timestamp'] - recent[0]['timestamp']
            if time_span < 1.0:  # 10 requests in 1 second
                score += 0.4
        
        return min(score, 1.0)
    
    def _create_event(
        self,
        event_type: str,
        threat_type: ThreatType,
        severity: SecurityLevel,
        description: str,
        source: str,
        details: Dict[str, Any],
        blocked: bool = False,
    ) -> SecurityEvent:
        """Create and record a security event."""
        event = SecurityEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            threat_type=threat_type,
            severity=severity,
            description=description,
            source=source,
            details=details,
            blocked=blocked,
        )
        
        self.events.append(event)
        logger.warning(
            f"Security Event [{severity.value}]: {description} "
            f"(blocked={blocked})"
        )
        
        return event
    
    def get_security_events(
        self,
        limit: int = 100,
        severity: Optional[SecurityLevel] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent security events.
        
        Args:
            limit: Maximum number of events to return
            severity: Filter by minimum severity
            
        Returns:
            List of event dictionaries
        """
        events = list(self.events)[-limit:]
        
        if severity:
            severity_order = {
                SecurityLevel.LOW: 0,
                SecurityLevel.MEDIUM: 1,
                SecurityLevel.HIGH: 2,
                SecurityLevel.CRITICAL: 3,
            }
            min_level = severity_order[severity]
            events = [
                e for e in events
                if severity_order[e.severity] >= min_level
            ]
        
        return [e.to_dict() for e in events]
    
    def generate_audit_report(self) -> Dict[str, Any]:
        """
        Generate a security audit report.
        
        Returns:
            Audit report dictionary
        """
        events_list = list(self.events)
        
        return {
            "generated_at": datetime.now().isoformat(),
            "total_events": len(events_list),
            "events_by_severity": {
                level.value: sum(1 for e in events_list if e.severity == level)
                for level in SecurityLevel
            },
            "events_by_threat": {
                threat.value: sum(1 for e in events_list if e.threat_type == threat)
                for threat in ThreatType
            },
            "blocked_events": sum(1 for e in events_list if e.blocked),
            "locked_accounts": len(self.locked_accounts),
            "active_policies": sum(1 for p in self.policies.values() if p.enabled),
        }
