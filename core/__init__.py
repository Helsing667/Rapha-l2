"""
Core module initialization for Nexus Core.

This package contains the four main layers of the Nexus Core architecture:
- Intent Parser: Natural language understanding
- Task Orchestrator: DAG-based task decomposition
- Execution Engine: Parallel task execution with rollback
- Security Layer: Security policies and anomaly detection
"""

from core.intent_parser import IntentParser
from core.task_orchestrator import TaskOrchestrator
from core.execution_engine import ExecutionEngine
from core.security_layer import SecurityLayer

__all__ = [
    "IntentParser",
    "TaskOrchestrator",
    "ExecutionEngine",
    "SecurityLayer",
]

__version__ = "1.0.0"
