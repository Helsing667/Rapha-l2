"""
Task Orchestrator Module for Nexus Core.

This module decomposes parsed intents into executable task graphs using
a Directed Acyclic Graph (DAG) structure. It handles task prioritization,
dependency resolution, and parallel execution planning.

Features:
- DAG-based task decomposition
- Priority-based scheduling
- Dependency resolution
- Parallel task planning
- Rollback chain generation
"""

import uuid
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import logging
import networkx as nx

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of a task in the execution pipeline."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"


class TaskPriority(Enum):
    """Priority levels for task execution."""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


@dataclass
class Task:
    """
    Represents an executable task in the orchestration graph.
    
    Attributes:
        id: Unique identifier for the task
        name: Human-readable task name
        action: The action to execute
        parameters: Parameters for the action
        privilege_level: Required privilege level
        priority: Task priority
        status: Current task status
        dependencies: IDs of tasks this task depends on
        rollback_action: Action to undo this task if needed
        timeout: Maximum execution time in seconds
        context: Additional context for execution
    """
    id: str
    name: str
    action: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    privilege_level: str = "user"
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    dependencies: List[str] = field(default_factory=list)
    rollback_action: Optional[str] = None
    rollback_parameters: Dict[str, Any] = field(default_factory=dict)
    timeout: int = 300
    context: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "action": self.action,
            "parameters": self.parameters,
            "privilege_level": self.privilege_level,
            "priority": self.priority.value,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "timeout": self.timeout,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class TaskGraph:
    """
    Represents a complete task execution graph.
    
    Attributes:
        id: Unique identifier for the graph
        original_intent: The parsed intent that generated this graph
        tasks: Dictionary of all tasks in the graph
        dag: NetworkX DiGraph representing dependencies
        created_at: Timestamp of graph creation
    """
    id: str
    original_intent: Dict[str, Any]
    tasks: Dict[str, Task] = field(default_factory=dict)
    dag: nx.DiGraph = field(default_factory=nx.DiGraph)
    status: TaskStatus = TaskStatus.PENDING
    execution_order: List[str] = field(default_factory=list)
    
    def add_task(self, task: Task) -> None:
        """Add a task to the graph."""
        self.tasks[task.id] = task
        self.dag.add_node(task.id, task=task)
    
    def add_dependency(self, from_task_id: str, to_task_id: str) -> None:
        """Add a dependency between tasks (from_task must complete before to_task)."""
        self.dag.add_edge(from_task_id, to_task_id)
        if to_task_id in self.tasks:
            self.tasks[to_task_id].dependencies.append(from_task_id)
    
    def get_ready_tasks(self) -> List[Task]:
        """Get all tasks that are ready to execute (all dependencies completed)."""
        ready = []
        for task_id, task in self.tasks.items():
            if task.status != TaskStatus.PENDING:
                continue
            
            # Check if all dependencies are completed
            deps_completed = all(
                self.tasks.get(dep_id, Task(id="", name="", action="")).status == TaskStatus.COMPLETED
                for dep_id in task.dependencies
            )
            
            if deps_completed:
                ready.append(task)
        
        # Sort by priority
        ready.sort(key=lambda t: t.priority.value)
        return ready
    
    def get_execution_order(self) -> List[str]:
        """Get topological sort of tasks for sequential execution."""
        try:
            return list(nx.topological_sort(self.dag))
        except nx.NetworkXUnfeasible:
            logger.error("Cycle detected in task graph!")
            return []


class TaskOrchestrator:
    """
    Orchestrates the decomposition and scheduling of tasks.
    
    This class converts parsed intents into executable task graphs,
    manages task dependencies, and determines optimal execution order.
    
    Attributes:
        max_parallel_tasks: Maximum number of tasks to run in parallel
        default_timeout: Default timeout for tasks
        enable_retry: Whether to enable automatic retry on failure
    """
    
    # Task templates for common operations
    TASK_TEMPLATES = {
        'file_operation': {
            'check_exists': {'action': 'file_check', 'name': 'Check file exists'},
            'check_permissions': {'action': 'permission_check', 'name': 'Check permissions'},
            'execute': {'action': 'file_execute', 'name': 'Execute file operation'},
            'verify': {'action': 'file_verify', 'name': 'Verify operation result'},
        },
        'message_send': {
            'validate_recipient': {'action': 'validate_contact', 'name': 'Validate recipient'},
            'prepare_message': {'action': 'format_message', 'name': 'Prepare message content'},
            'check_attachment': {'action': 'check_file', 'name': 'Check attachment file'},
            'establish_connection': {'action': 'connect_mobile', 'name': 'Establish mobile connection'},
            'send': {'action': 'send_message', 'name': 'Send message'},
            'confirm': {'action': 'verify_delivery', 'name': 'Confirm delivery'},
        },
        'system_command': {
            'validate_command': {'action': 'validate_command', 'name': 'Validate command safety'},
            'check_privileges': {'action': 'check_sudo', 'name': 'Check privileges'},
            'execute': {'action': 'execute_shell', 'name': 'Execute command'},
            'verify_result': {'action': 'verify_output', 'name': 'Verify command result'},
        },
        'mobile_action': {
            'check_connection': {'action': 'check_ssh', 'name': 'Check SSH connection'},
            'authenticate': {'action': 'ssh_auth', 'name': 'Authenticate with mobile'},
            'execute_remote': {'action': 'remote_execute', 'name': 'Execute on mobile'},
            'verify_remote': {'action': 'remote_verify', 'name': 'Verify remote result'},
        },
    }
    
    def __init__(
        self,
        max_parallel_tasks: int = 10,
        default_timeout: int = 300,
        enable_retry: bool = True,
        max_retries: int = 3,
    ):
        """
        Initialize the Task Orchestrator.
        
        Args:
            max_parallel_tasks: Maximum number of parallel tasks
            default_timeout: Default timeout for tasks in seconds
            enable_retry: Enable automatic retry on failure
            max_retries: Maximum number of retry attempts
        """
        self.max_parallel_tasks = max_parallel_tasks
        self.default_timeout = default_timeout
        self.enable_retry = enable_retry
        self.max_retries = max_retries
        
        self.active_graphs: Dict[str, TaskGraph] = {}
        self.completed_graphs: List[str] = []
        
        logger.info(
            f"TaskOrchestrator initialized (max_parallel={max_parallel_tasks}, "
            f"default_timeout={default_timeout}s)"
        )
    
    def decompose_intent(self, parsed_intent: Dict[str, Any]) -> TaskGraph:
        """
        Decompose a parsed intent into a task graph.
        
        Args:
            parsed_intent: Dictionary representation of ParsedIntent
            
        Returns:
            TaskGraph containing all tasks needed to fulfill the intent
        """
        graph_id = str(uuid.uuid4())
        intent_type = parsed_intent.get('intent_type', 'unknown')
        
        logger.info(f"Decomposing intent type '{intent_type}' into task graph {graph_id}")
        
        graph = TaskGraph(
            id=graph_id,
            original_intent=parsed_intent,
        )
        
        # Get task templates based on intent type
        templates = self.TASK_TEMPLATES.get(intent_type, {})
        
        if not templates:
            # Create a generic single task for unknown intent types
            task = self._create_generic_task(parsed_intent)
            graph.add_task(task)
        else:
            # Create tasks from templates
            previous_task_id = None
            for step_name, template in templates.items():
                task = self._create_task_from_template(
                    step_name, template, parsed_intent, graph_id
                )
                
                # Add dependency on previous task
                if previous_task_id:
                    graph.add_dependency(previous_task_id, task.id)
                
                graph.add_task(task)
                previous_task_id = task.id
        
        # Calculate execution order
        graph.execution_order = graph.get_execution_order()
        
        # Store active graph
        self.active_graphs[graph_id] = graph
        
        logger.info(
            f"Created task graph with {len(graph.tasks)} tasks, "
            f"execution order: {graph.execution_order}"
        )
        
        return graph
    
    def _create_task_from_template(
        self,
        step_name: str,
        template: Dict[str, Any],
        parsed_intent: Dict[str, Any],
        graph_id: str,
    ) -> Task:
        """
        Create a task from a template.
        
        Args:
            step_name: Name of the step
            template: Task template dictionary
            parsed_intent: Original parsed intent
            graph_id: ID of the parent graph
            
        Returns:
            Created Task object
        """
        task_id = f"{graph_id}_{step_name}"
        
        # Determine priority based on step
        priority = TaskPriority.NORMAL
        if step_name in ('validate_recipient', 'validate_command', 'check_privileges'):
            priority = TaskPriority.HIGH
        elif step_name in ('check_exists', 'check_connection'):
            priority = TaskPriority.CRITICAL
        
        # Determine privilege level
        privilege_level = parsed_intent.get('privilege_level', 'user')
        
        # Extract relevant parameters
        parameters = parsed_intent.get('parameters', {}).copy()
        parameters['step'] = step_name
        
        # Create rollback action
        rollback_action, rollback_params = self._generate_rollback(step_name, parameters)
        
        task = Task(
            id=task_id,
            name=template.get('name', step_name),
            action=template.get('action', 'generic'),
            parameters=parameters,
            privilege_level=privilege_level,
            priority=priority,
            timeout=self.default_timeout,
            rollback_action=rollback_action,
            rollback_parameters=rollback_params,
        )
        
        return task
    
    def _create_generic_task(self, parsed_intent: Dict[str, Any]) -> Task:
        """Create a generic task for unknown intent types."""
        return Task(
            id=str(uuid.uuid4()),
            name="Generic Task",
            action="execute_generic",
            parameters=parsed_intent.get('parameters', {}),
            privilege_level=parsed_intent.get('privilege_level', 'user'),
            timeout=self.default_timeout,
        )
    
    def _generate_rollback(
        self, step_name: str, parameters: Dict[str, Any]
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Generate rollback action for a task.
        
        Args:
            step_name: Name of the step
            parameters: Task parameters
            
        Returns:
            Tuple of (rollback_action, rollback_parameters)
        """
        rollback_map = {
            'check_exists': (None, {}),
            'check_permissions': (None, {}),
            'file_execute': ('file_restore', {'backup_path': parameters.get('path')}),
            'send_message': ('recall_message', {'message_id': None}),
            'execute_shell': (None, {}),  # Some commands can't be rolled back
            'connect_mobile': ('disconnect', {}),
        }
        
        return rollback_map.get(step_name, (None, {}))
    
    def get_next_executable_tasks(
        self, graph_id: str, limit: Optional[int] = None
    ) -> List[Task]:
        """
        Get the next tasks ready for execution from a graph.
        
        Args:
            graph_id: ID of the task graph
            limit: Maximum number of tasks to return
            
        Returns:
            List of tasks ready to execute
        """
        if graph_id not in self.active_graphs:
            logger.warning(f"Graph {graph_id} not found")
            return []
        
        graph = self.active_graphs[graph_id]
        ready_tasks = graph.get_ready_tasks()
        
        if limit:
            ready_tasks = ready_tasks[:limit]
        
        return ready_tasks
    
    def mark_task_completed(
        self, graph_id: str, task_id: str, result: Any = None
    ) -> None:
        """
        Mark a task as completed.
        
        Args:
            graph_id: ID of the task graph
            task_id: ID of the completed task
            result: Optional result data
        """
        if graph_id not in self.active_graphs:
            return
        
        graph = self.active_graphs[graph_id]
        if task_id in graph.tasks:
            graph.tasks[task_id].status = TaskStatus.COMPLETED
            graph.tasks[task_id].result = result
            logger.debug(f"Task {task_id} marked as completed")
    
    def mark_task_failed(
        self, graph_id: str, task_id: str, error: str
    ) -> None:
        """
        Mark a task as failed.
        
        Args:
            graph_id: ID of the task graph
            task_id: ID of the failed task
            error: Error message
        """
        if graph_id not in self.active_graphs:
            return
        
        graph = self.active_graphs[graph_id]
        if task_id in graph.tasks:
            graph.tasks[task_id].status = TaskStatus.FAILED
            graph.tasks[task_id].error = error
            graph.status = TaskStatus.FAILED
            logger.error(f"Task {task_id} failed: {error}")
    
    def get_rollback_sequence(self, graph_id: str) -> List[Task]:
        """
        Get the sequence of rollback tasks for failed graph.
        
        Args:
            graph_id: ID of the task graph
            
        Returns:
            List of rollback tasks in reverse execution order
        """
        if graph_id not in self.active_graphs:
            return []
        
        graph = self.active_graphs[graph_id]
        rollback_tasks = []
        
        # Get completed tasks in reverse order
        completed = [
            task for task in graph.tasks.values()
            if task.status == TaskStatus.COMPLETED and task.rollback_action
        ]
        
        # Reverse order for rollback
        completed.reverse()
        
        for task in completed:
            rollback_task = Task(
                id=f"{task.id}_rollback",
                name=f"Rollback: {task.name}",
                action=task.rollback_action or 'noop',
                parameters=task.rollback_parameters,
                privilege_level=task.privilege_level,
                priority=TaskPriority.CRITICAL,
            )
            rollback_tasks.append(rollback_task)
        
        return rollback_tasks
    
    def finalize_graph(self, graph_id: str) -> bool:
        """
        Finalize a task graph (all tasks completed or failed).
        
        Args:
            graph_id: ID of the task graph
            
        Returns:
            True if graph completed successfully
        """
        if graph_id not in self.active_graphs:
            return False
        
        graph = self.active_graphs[graph_id]
        
        # Check if all tasks are in terminal state
        all_done = all(
            task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            for task in graph.tasks.values()
        )
        
        if all_done:
            # Check if any task failed
            any_failed = any(
                task.status == TaskStatus.FAILED
                for task in graph.tasks.values()
            )
            
            graph.status = TaskStatus.FAILED if any_failed else TaskStatus.COMPLETED
            self.completed_graphs.append(graph_id)
            del self.active_graphs[graph_id]
            
            logger.info(
                f"Graph {graph_id} finalized: {'SUCCESS' if not any_failed else 'FAILED'}"
            )
            
            return not any_failed
        
        return False
    
    def get_graph_status(self, graph_id: str) -> Dict[str, Any]:
        """
        Get the current status of a task graph.
        
        Args:
            graph_id: ID of the task graph
            
        Returns:
            Dictionary with graph status information
        """
        if graph_id not in self.active_graphs:
            # Check completed graphs
            return {"error": "Graph not found or already completed"}
        
        graph = self.active_graphs[graph_id]
        
        status_counts = defaultdict(int)
        for task in graph.tasks.values():
            status_counts[task.status.value] += 1
        
        return {
            "graph_id": graph_id,
            "status": graph.status.value,
            "total_tasks": len(graph.tasks),
            "tasks_by_status": dict(status_counts),
            "execution_order": graph.execution_order,
            "progress": sum(
                1 for t in graph.tasks.values()
                if t.status == TaskStatus.COMPLETED
            ) / len(graph.tasks) * 100 if graph.tasks else 0,
        }
