"""
Tests for Task Orchestrator module.
"""

import pytest
from core.task_orchestrator import (
    TaskOrchestrator, Task, TaskGraph, TaskStatus, TaskPriority
)


class TestTaskOrchestrator:
    """Test cases for TaskOrchestrator."""
    
    @pytest.fixture
    def orchestrator(self):
        """Create an orchestrator instance for testing."""
        return TaskOrchestrator(max_parallel_tasks=5, default_timeout=60)
    
    def test_decompose_message_send_intent(self, orchestrator):
        """Test decomposing a message send intent into tasks."""
        parsed_intent = {
            'intent_type': 'message_send',
            'parameters': {
                'recipient': 'Jean',
                'message_text': 'Hello',
            },
            'privilege_level': 'user',
        }
        
        graph = orchestrator.decompose_intent(parsed_intent)
        
        assert graph.id is not None
        assert len(graph.tasks) > 0
        assert graph.status == TaskStatus.PENDING
    
    def test_decompose_file_operation_intent(self, orchestrator):
        """Test decomposing a file operation intent."""
        parsed_intent = {
            'intent_type': 'file_operation',
            'parameters': {'path': '/tmp/test.txt', 'action': 'read'},
            'privilege_level': 'user',
        }
        
        graph = orchestrator.decompose_intent(parsed_intent)
        
        assert len(graph.tasks) > 0
    
    def test_task_dependencies(self, orchestrator):
        """Test that task dependencies are correctly set."""
        parsed_intent = {
            'intent_type': 'message_send',
            'parameters': {},
            'privilege_level': 'user',
        }
        
        graph = orchestrator.decompose_intent(parsed_intent)
        
        # First task should have no dependencies
        first_task_id = graph.execution_order[0] if graph.execution_order else list(graph.tasks.keys())[0]
        first_task = graph.tasks.get(first_task_id)
        
        if first_task:
            assert len(first_task.dependencies) == 0
    
    def test_get_ready_tasks(self, orchestrator):
        """Test getting tasks ready for execution."""
        parsed_intent = {
            'intent_type': 'file_operation',
            'parameters': {},
            'privilege_level': 'user',
        }
        
        graph = orchestrator.decompose_intent(parsed_intent)
        ready = graph.get_ready_tasks()
        
        # At least the first task should be ready
        assert len(ready) >= 1
    
    def test_mark_task_completed(self, orchestrator):
        """Test marking tasks as completed."""
        parsed_intent = {
            'intent_type': 'file_operation',
            'parameters': {},
            'privilege_level': 'user',
        }
        
        graph = orchestrator.decompose_intent(parsed_intent)
        task_id = list(graph.tasks.keys())[0]
        
        orchestrator.mark_task_completed(graph.id, task_id, result={'test': 'data'})
        
        assert graph.tasks[task_id].status == TaskStatus.COMPLETED
        assert graph.tasks[task_id].result == {'test': 'data'}
    
    def test_mark_task_failed(self, orchestrator):
        """Test marking tasks as failed."""
        parsed_intent = {
            'intent_type': 'file_operation',
            'parameters': {},
            'privilege_level': 'user',
        }
        
        graph = orchestrator.decompose_intent(parsed_intent)
        task_id = list(graph.tasks.keys())[0]
        
        orchestrator.mark_task_failed(graph.id, task_id, error="Test error")
        
        assert graph.tasks[task_id].status == TaskStatus.FAILED
        assert graph.tasks[task_id].error == "Test error"
        assert graph.status == TaskStatus.FAILED
    
    def test_get_graph_status(self, orchestrator):
        """Test getting graph status."""
        parsed_intent = {
            'intent_type': 'file_operation',
            'parameters': {},
            'privilege_level': 'user',
        }
        
        graph = orchestrator.decompose_intent(parsed_intent)
        status = orchestrator.get_graph_status(graph.id)
        
        assert 'graph_id' in status
        assert 'status' in status
        assert 'total_tasks' in status
        assert 'progress' in status
    
    def test_rollback_sequence_generation(self, orchestrator):
        """Test generating rollback sequence for failed graph."""
        parsed_intent = {
            'intent_type': 'file_operation',
            'parameters': {'path': '/tmp/test.txt'},
            'privilege_level': 'user',
        }
        
        graph = orchestrator.decompose_intent(parsed_intent)
        
        # Complete some tasks
        for task_id in list(graph.tasks.keys())[:2]:
            orchestrator.mark_task_completed(graph.id, task_id)
        
        rollback_tasks = orchestrator.get_rollback_sequence(graph.id)
        
        # Should have rollback tasks for tasks with rollback_action
        # (depends on which tasks have rollback defined)
        assert isinstance(rollback_tasks, list)
    
    def test_finalize_graph_success(self, orchestrator):
        """Test finalizing a successful graph."""
        parsed_intent = {
            'intent_type': 'file_operation',
            'parameters': {},
            'privilege_level': 'user',
        }
        
        graph = orchestrator.decompose_intent(parsed_intent)
        
        # Complete all tasks
        for task_id in graph.tasks.keys():
            orchestrator.mark_task_completed(graph.id, task_id)
        
        success = orchestrator.finalize_graph(graph.id)
        
        assert success == True
        assert graph.id not in orchestrator.active_graphs
        assert graph.id in orchestrator.completed_graphs
    
    def test_finalize_graph_failure(self, orchestrator):
        """Test finalizing a failed graph."""
        parsed_intent = {
            'intent_type': 'file_operation',
            'parameters': {},
            'privilege_level': 'user',
        }
        
        graph = orchestrator.decompose_intent(parsed_intent)
        
        # Fail one task
        task_id = list(graph.tasks.keys())[0]
        orchestrator.mark_task_failed(graph.id, task_id, "Error")
        
        # Complete rest
        for tid in list(graph.tasks.keys())[1:]:
            orchestrator.mark_task_completed(graph.id, tid)
        
        success = orchestrator.finalize_graph(graph.id)
        
        assert success == False
    
    def test_task_to_dict(self):
        """Test converting Task to dictionary."""
        task = Task(
            id="test-123",
            name="Test Task",
            action="test_action",
            parameters={'key': 'value'},
            priority=TaskPriority.HIGH,
        )
        
        result = task.to_dict()
        
        assert result['id'] == "test-123"
        assert result['name'] == "Test Task"
        assert result['priority'] == 2  # HIGH value


class TestTaskGraph:
    """Test cases for TaskGraph."""
    
    def test_add_task(self):
        """Test adding tasks to graph."""
        graph = TaskGraph(id="test", original_intent={})
        task = Task(id="t1", name="Task 1", action="test")
        
        graph.add_task(task)
        
        assert "t1" in graph.tasks
        assert graph.dag.has_node("t1")
    
    def test_add_dependency(self):
        """Test adding dependencies between tasks."""
        graph = TaskGraph(id="test", original_intent={})
        task1 = Task(id="t1", name="Task 1", action="test")
        task2 = Task(id="t2", name="Task 2", action="test")
        
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_dependency("t1", "t2")
        
        assert graph.dag.has_edge("t1", "t2")
        assert "t1" in task2.dependencies
    
    def test_execution_order_topological(self):
        """Test that execution order respects dependencies."""
        graph = TaskGraph(id="test", original_intent={})
        
        # Create tasks with dependencies: t1 -> t2 -> t3
        for i in range(1, 4):
            task = Task(id=f"t{i}", name=f"Task {i}", action="test")
            graph.add_task(task)
            if i > 1:
                graph.add_dependency(f"t{i-1}", f"t{i}")
        
        order = graph.get_execution_order()
        
        # Verify order respects dependencies
        assert order.index("t1") < order.index("t2")
        assert order.index("t2") < order.index("t3")
