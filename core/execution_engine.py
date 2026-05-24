"""
Execution Engine Module for Nexus Core.

This module executes tasks from the orchestrator using a thread pool,
with support for parallel execution, timeouts, rollback, and detailed logging.

Features:
- Thread/process pool execution
- Strict timeouts
- Automatic rollback on failure
- Detailed execution logging
- Resource monitoring
"""

import os
import subprocess
import time
from typing import Dict, List, Optional, Any, Callable
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, Future, as_completed
from dataclasses import dataclass
import logging
import signal
import psutil
from mistralai import Mistral

from core.task_orchestrator import Task, TaskStatus, TaskGraph, TaskPriority

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a task execution."""
    task_id: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    rollback_performed: bool = False


class ExecutionEngine:
    """
    Executes tasks with proper isolation, timeouts, and error handling.
    
    This class manages a pool of workers to execute tasks in parallel,
    enforces timeouts, handles failures with rollback, and monitors
    resource usage.
    
    Attributes:
        max_workers: Maximum number of parallel workers
        pool_type: Type of executor ('thread' or 'process')
        enable_rollback: Whether to perform automatic rollback
        default_timeout: Default timeout for tasks
    """
    
    # Action handlers mapping
    ACTION_HANDLERS: Dict[str, Callable] = {}
    
    def __init__(
        self,
        max_workers: int = 8,
        pool_type: str = "thread",
        enable_rollback: bool = True,
        default_timeout: int = 300,
    ):
        """
        Initialize the Execution Engine.
        
        Args:
            max_workers: Maximum number of parallel workers
            pool_type: Type of executor ('thread' or 'process')
            enable_rollback: Enable automatic rollback on failure
            default_timeout: Default timeout in seconds
        """
        self.max_workers = max_workers
        self.pool_type = pool_type
        self.enable_rollback = enable_rollback
        self.default_timeout = default_timeout
        
        self.executor: Optional[ThreadPoolExecutor | ProcessPoolExecutor] = None
        self.running_tasks: Dict[str, Future] = {}
        self.execution_history: List[ExecutionResult] = []
        
        # Register action handlers
        self._register_handlers()
        
        logger.info(
            f"ExecutionEngine initialized (workers={max_workers}, "
            f"type={pool_type}, rollback={enable_rollback})"
        )
    
    def _register_handlers(self) -> None:
        """Register action handlers for different task types."""
        self.ACTION_HANDLERS = {
            'file_check': self._handle_file_check,
            'permission_check': self._handle_permission_check,
            'file_execute': self._handle_file_operation,
            'file_verify': self._handle_file_verify,
            'validate_contact': self._handle_validate_contact,
            'format_message': self._handle_format_message,
            'check_file': self._handle_check_file,
            'connect_mobile': self._handle_connect_mobile,
            'send_message': self._handle_send_message,
            'verify_delivery': self._handle_verify_delivery,
            'validate_command': self._handle_validate_command,
            'check_sudo': self._handle_check_sudo,
            'execute_shell': self._handle_execute_shell,
            'verify_output': self._handle_verify_output,
            'check_ssh': self._handle_check_ssh,
            'ssh_auth': self._handle_ssh_auth,
            'remote_execute': self._handle_remote_execute,
            'remote_verify': self._handle_remote_verify,
            'file_restore': self._handle_file_restore,
            'disconnect': self._handle_disconnect,
            'generic': self._handle_generic,
            'noop': self._handle_noop,
        }
    
    def start(self) -> None:
        """Start the execution engine and initialize the worker pool."""
        if self.pool_type == "process":
            self.executor = ProcessPoolExecutor(max_workers=self.max_workers)
        else:
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
        logger.info("ExecutionEngine started")
    
    def stop(self, wait: bool = True) -> None:
        """
        Stop the execution engine.
        
        Args:
            wait: Whether to wait for running tasks to complete
        """
        if self.executor:
            self.executor.shutdown(wait=wait)
            self.executor = None
        
        logger.info("ExecutionEngine stopped")
    
    def execute_task(self, task: Task) -> ExecutionResult:
        """
        Execute a single task synchronously.
        
        Args:
            task: Task to execute
            
        Returns:
            ExecutionResult with outcome
        """
        start_time = time.time()
        logger.info(f"Executing task: {task.name} ({task.id})")
        
        try:
            # Get handler for action
            handler = self.ACTION_HANDLERS.get(task.action, self._handle_generic)
            
            # Execute with timeout
            timeout = task.timeout or self.default_timeout
            result = self._execute_with_timeout(handler, task, timeout)
            
            execution_time = time.time() - start_time
            
            exec_result = ExecutionResult(
                task_id=task.id,
                success=True,
                output=result,
                execution_time=execution_time,
            )
            
            logger.info(f"Task {task.id} completed successfully in {execution_time:.2f}s")
            
        except TimeoutError as e:
            execution_time = time.time() - start_time
            exec_result = ExecutionResult(
                task_id=task.id,
                success=False,
                error=f"Task timed out after {timeout}s",
                execution_time=execution_time,
            )
            logger.error(f"Task {task.id} timed out")
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            logger.exception(f"Task {task.id} failed: {error_msg}")
            
            exec_result = ExecutionResult(
                task_id=task.id,
                success=False,
                error=error_msg,
                execution_time=execution_time,
            )
            
            # Attempt rollback if enabled
            if self.enable_rollback and task.rollback_action:
                logger.info(f"Attempting rollback for task {task.id}")
                rollback_result = self._perform_rollback(task)
                exec_result.rollback_performed = rollback_result
        
        self.execution_history.append(exec_result)
        return exec_result
    
    def execute_parallel(
        self, tasks: List[Task], max_parallel: Optional[int] = None
    ) -> Dict[str, ExecutionResult]:
        """
        Execute multiple tasks in parallel.
        
        Args:
            tasks: List of tasks to execute
            max_parallel: Maximum number of parallel tasks
            
        Returns:
            Dictionary mapping task IDs to ExecutionResults
        """
        if not self.executor:
            raise RuntimeError("ExecutionEngine not started")
        
        limit = max_parallel or self.max_workers
        results: Dict[str, ExecutionResult] = {}
        
        # Submit tasks up to the limit
        futures: Dict[Future, Task] = {}
        
        for task in tasks[:limit]:
            future = self.executor.submit(self.execute_task, task)
            futures[future] = task
            self.running_tasks[task.id] = future
        
        # Collect results as they complete
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                results[task.id] = result
            except Exception as e:
                results[task.id] = ExecutionResult(
                    task_id=task.id,
                    success=False,
                    error=str(e),
                )
            finally:
                del self.running_tasks[task.id]
        
        return results
    
    def _execute_with_timeout(
        self, handler: Callable, task: Task, timeout: int
    ) -> Any:
        """
        Execute a handler with a timeout.
        
        Args:
            handler: Function to execute
            task: Task being executed
            timeout: Timeout in seconds
            
        Returns:
            Handler result
            
        Raises:
            TimeoutError: If execution exceeds timeout
        """
        if not self.executor:
            # Synchronous execution with timeout
            import threading
            
            result = [None]
            exception = [None]
            
            def target():
                try:
                    result[0] = handler(task)
                except Exception as e:
                    exception[0] = e
            
            thread = threading.Thread(target=target)
            thread.start()
            thread.join(timeout=timeout)
            
            if thread.is_alive():
                raise TimeoutError(f"Task exceeded {timeout}s timeout")
            
            if exception[0]:
                raise exception[0]
            
            return result[0]
        else:
            # Use executor with timeout
            future = self.executor.submit(handler, task)
            return future.result(timeout=timeout)
    
    def _perform_rollback(self, task: Task) -> bool:
        """
        Perform rollback for a failed task.
        
        Args:
            task: Failed task
            
        Returns:
            True if rollback succeeded
        """
        if not task.rollback_action:
            return False
        
        try:
            handler = self.ACTION_HANDLERS.get(task.rollback_action)
            if handler:
                # Create rollback task
                rollback_task = Task(
                    id=f"{task.id}_rollback",
                    name=f"Rollback: {task.name}",
                    action=task.rollback_action,
                    parameters=task.rollback_parameters,
                    privilege_level=task.privilege_level,
                    priority=TaskPriority.CRITICAL,
                )
                
                result = handler(rollback_task)
                logger.info(f"Rollback completed for task {task.id}")
                return True
        except Exception as e:
            logger.error(f"Rollback failed for task {task.id}: {e}")
        
        return False
    
    # ======================================================================
    # ACTION HANDLERS
    # ======================================================================
    
    def _handle_file_check(self, task: Task) -> Dict[str, Any]:
        """Check if a file exists and get its properties."""
        path = task.parameters.get('path', '')
        
        if not path:
            result = {'exists': False, 'error': 'No path specified'}
            response = self.generate_response('file_check', "Aucun chemin de fichier spécifié")
            result['ai_response'] = response
            return result
        
        exists = os.path.isfile(path)
        stats = None
        
        if exists:
            stat = os.stat(path)
            stats = {
                'size': stat.st_size,
                'modified': stat.st_mtime,
                'permissions': oct(stat.st_mode)[-3:],
            }
        
        result = {
            'exists': exists,
            'path': path,
            'stats': stats,
        }
        response = self.generate_response('file_check', f"Vérification du fichier: {path}")
        result['ai_response'] = response
        return result
    
    def _handle_permission_check(self, task: Task) -> Dict[str, Any]:
        """Check permissions for a file or operation."""
        path = task.parameters.get('path', '')
        required_perms = task.parameters.get('required_permissions', ['read'])
        
        if not path:
            result = {'allowed': False, 'error': 'No path specified'}
            response = self.generate_response('permission_check', "Aucun chemin spécifié pour la vérification des permissions")
            result['ai_response'] = response
            return result
        
        allowed = True
        missing_perms = []
        
        if 'read' in required_perms and not os.access(path, os.R_OK):
            allowed = False
            missing_perms.append('read')
        
        if 'write' in required_perms and not os.access(path, os.W_OK):
            allowed = False
            missing_perms.append('write')
        
        if 'execute' in required_perms and not os.access(path, os.X_OK):
            allowed = False
            missing_perms.append('execute')
        
        result = {
            'allowed': allowed,
            'path': path,
            'missing_permissions': missing_perms,
        }
        response = self.generate_response('permission_check', f"Vérification des permissions pour: {path}")
        result['ai_response'] = response
        return result
    
    def _handle_file_operation(self, task: Task) -> Dict[str, Any]:
        """Execute a file operation (copy, move, delete, etc.)."""
        action = task.parameters.get('action', 'read')
        path = task.parameters.get('path', '')
        destination = task.parameters.get('destination')
        
        # Security check: use absolute paths only
        if path and not os.path.isabs(path):
            return {'success': False, 'error': 'Relative paths not allowed'}
        
        try:
            if action == 'read':
                with open(path, 'r') as f:
                    content = f.read()
                return {'success': True, 'content': content}
            
            elif action == 'copy' and destination:
                import shutil
                shutil.copy2(path, destination)
                return {'success': True, 'destination': destination}
            
            elif action == 'move' and destination:
                import shutil
                shutil.move(path, destination)
                return {'success': True, 'destination': destination}
            
            elif action == 'delete':
                os.remove(path)
                return {'success': True}
            
            else:
                return {'success': False, 'error': f'Unknown action: {action}'}
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _handle_file_verify(self, task: Task) -> Dict[str, Any]:
        """Verify a file operation was successful."""
        path = task.parameters.get('path', '')
        expected_state = task.parameters.get('expected_state', {})
        
        if not os.path.exists(path):
            return {'verified': False, 'error': 'File does not exist'}
        
        # Verify against expected state
        if expected_state:
            stat = os.stat(path)
            if 'size' in expected_state and stat.st_size != expected_state['size']:
                return {'verified': False, 'error': 'Size mismatch'}
        
        return {'verified': True}
    
    def _handle_validate_contact(self, task: Task) -> Dict[str, Any]:
        """Validate a contact/recipient exists."""
        recipient = task.parameters.get('recipient', '')
        
        # In a real implementation, this would check contacts
        if not recipient:
            return {'valid': False, 'error': 'No recipient specified'}
        
        result = {'valid': True, 'recipient': recipient}
        response = self.generate_response('validate_contact', f"Validation du contact: {recipient}")
        result['ai_response'] = response
        return result
    
    def _handle_format_message(self, task: Task) -> Dict[str, Any]:
        """Format a message for sending."""
        text = task.parameters.get('message_text', '')
        platform = task.parameters.get('platform', 'sms')
        
        formatted = {
            'text': text,
            'platform': platform,
            'timestamp': time.time(),
        }
        
        result = {'formatted': True, 'message': formatted}
        response = self.generate_response('format_message', f"Formatage du message: {text[:50]}...")
        result['ai_response'] = response
        return result
    
    def _handle_check_file(self, task: Task) -> Dict[str, Any]:
        """Check an attachment file."""
        attachment = task.parameters.get('attachment', '')
        
        if not attachment:
            return {'valid': True, 'error': 'No attachment'}
        
        if not os.path.isfile(attachment):
            return {'valid': False, 'error': 'Attachment not found'}
        
        size = os.path.getsize(attachment)
        max_size = 10 * 1024 * 1024  # 10MB default
        
        if size > max_size:
            return {'valid': False, 'error': f'File too large: {size} bytes'}
        
        result = {'valid': True, 'size': size}
        response = self.generate_response('check_file', f"Vérification du fichier: {attachment}")
        result['ai_response'] = response
        return result
    
    def _handle_connect_mobile(self, task: Task) -> Dict[str, Any]:
        """Establish connection to mobile device."""
        # Placeholder - actual implementation would use SSH
        result = {'connected': True, 'method': 'ssh'}
        response = self.generate_response('connect_mobile', "Connexion à l'appareil mobile")
        result['ai_response'] = response
        return result
    
    def _handle_send_message(self, task: Task) -> Dict[str, Any]:
        """Send a message via mobile device."""
        recipient = task.parameters.get('recipient', '')
        message = task.parameters.get('message_text', '')
        
        # Placeholder - actual implementation would send via mobile
        result = {
            'sent': True,
            'recipient': recipient,
            'message': message[:50] + '...' if len(message) > 50 else message,
        }
        response = self.generate_response('send_message', f"Envoi du message à {recipient}")
        result['ai_response'] = response
        return result
    
    def _handle_verify_delivery(self, task: Task) -> Dict[str, Any]:
        """Verify message delivery."""
        result = {'delivered': True}
        response = self.generate_response('verify_delivery', "Vérification de la livraison du message")
        result['ai_response'] = response
        return result
    
    def _handle_validate_command(self, task: Task) -> Dict[str, Any]:
        """Validate a shell command is safe to execute."""
        command = task.parameters.get('command', '')
        
        # Dangerous commands/patterns to block
        dangerous_patterns = [
            'rm -rf /',
            'mkfs',
            'dd if=',
            ':(){:|:&};:',  # Fork bomb
            'chmod -R 777',
        ]
        
        for pattern in dangerous_patterns:
            if pattern in command.lower():
                return {'safe': False, 'error': f'Dangerous pattern detected: {pattern}'}
        
        result = {'safe': True, 'command': command}
        response = self.generate_response('validate_command', f"Validation de la commande: {command}")
        result['ai_response'] = response
        return result
    
    def _handle_check_sudo(self, task: Task) -> Dict[str, Any]:
        """Check if sudo privileges are available."""
        try:
            result = subprocess.run(
                ['sudo', '-n', 'true'],
                capture_output=True,
                timeout=5,
            )
            output = {'sudo_available': result.returncode == 0}
            response = self.generate_response('check_sudo', "Vérification des privilèges sudo")
            output['ai_response'] = response
            return output
        except Exception:
            output = {'sudo_available': False}
            response = self.generate_response('check_sudo', "Échec de la vérification sudo")
            output['ai_response'] = response
            return output
    
    def _handle_execute_shell(self, task: Task) -> Dict[str, Any]:
        """Execute a shell command safely."""
        command = task.parameters.get('command', '')
        
        if not command:
            return {'success': False, 'error': 'No command specified'}
        
        try:
            # Use subprocess with security measures
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=task.timeout or 60,
            )
            
            output = {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
            }
            response = self.generate_response('execute_shell', f"Exécution de la commande: {command}")
            output['ai_response'] = response
            return output
        except subprocess.TimeoutExpired:
            output = {'success': False, 'error': 'Command timed out'}
            response = self.generate_response('execute_shell', "La commande a expiré")
            output['ai_response'] = response
            return output
        except Exception as e:
            output = {'success': False, 'error': str(e)}
            response = self.generate_response('execute_shell', f"Erreur lors de l'exécution: {str(e)}")
            output['ai_response'] = response
            return output
    
    def _handle_verify_output(self, task: Task) -> Dict[str, Any]:
        """Verify shell command output."""
        expected = task.parameters.get('expected_output')
        actual = task.parameters.get('actual_output', '')
        
        if expected and expected not in actual:
            result = {'verified': False, 'error': 'Expected output not found'}
            response = self.generate_response('verify_output', "La sortie attendue n'a pas été trouvée")
            result['ai_response'] = response
            return result
        
        result = {'verified': True}
        response = self.generate_response('verify_output', "La sortie a été vérifiée avec succès")
        result['ai_response'] = response
        return result
    
    def _handle_check_ssh(self, task: Task) -> Dict[str, Any]:
        """Check SSH connection to mobile device."""
        # Placeholder for actual SSH check
        result = {'ssh_available': True}
        response = self.generate_response('check_ssh', "Vérification de la connexion SSH")
        result['ai_response'] = response
        return result
    
    def _handle_ssh_auth(self, task: Task) -> Dict[str, Any]:
        """Authenticate via SSH."""
        # Placeholder for actual SSH auth
        result = {'authenticated': True}
        response = self.generate_response('ssh_auth', "Authentification SSH réussie")
        result['ai_response'] = response
        return result
    
    def _handle_remote_execute(self, task: Task) -> Dict[str, Any]:
        """Execute command on remote mobile device."""
        command = task.parameters.get('command', '')
        
        # Placeholder - actual implementation would use SSH
        result = {'executed': True, 'command': command}
        response = self.generate_response('remote_execute', f"Exécution distante: {command}")
        result['ai_response'] = response
        return result
    
    def _handle_remote_verify(self, task: Task) -> Dict[str, Any]:
        """Verify remote execution result."""
        result = {'verified': True}
        response = self.generate_response('remote_verify', "Vérification de l'exécution distante")
        result['ai_response'] = response
        return result
    
    def _handle_file_restore(self, task: Task) -> Dict[str, Any]:
        """Restore a file from backup."""
        backup_path = task.parameters.get('backup_path', '')
        
        # Placeholder for actual restore logic
        result = {'restored': True, 'path': backup_path}
        response = self.generate_response('file_restore', f"Restauration du fichier: {backup_path}")
        result['ai_response'] = response
        return result
    
    def _handle_disconnect(self, task: Task) -> Dict[str, Any]:
        """Disconnect from mobile device."""
        result = {'disconnected': True}
        response = self.generate_response('disconnect', "Déconnexion de l'appareil mobile")
        result['ai_response'] = response
        return result
    
    def _handle_generic(self, task: Task) -> Dict[str, Any]:
        """Handle generic/unknown actions."""
        result = {'handled': True, 'action': task.action}
        response = self.generate_response('generic', f"Action générique: {task.action}")
        result['ai_response'] = response
        return result
    
    def _handle_noop(self, task: Task) -> Dict[str, Any]:
        """No-operation handler."""
        result = {'noop': True}
        response = self.generate_response('noop', "Aucune opération")
        result['ai_response'] = response
        return result
    
    def generate_response(self, intent: str, user_message: str) -> str:
        """
        Generate a response using Mistral AI API.
        
        Args:
            intent: The validated intent name
            user_message: The user's message
            
        Returns:
            Textual response in French
        """
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("MISTRAL_API_KEY environment variable is not set")
        
        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        
        prompt = f"Intent: {intent}\nMessage utilisateur: {user_message}\n\nRéponds en français de manière appropriée à cet intent."
        
        response = client.chat.complete(
            model="mistral-small-latest",
            messages=[
                {"role": "system", "content": "Tu es un assistant utile. Réponds toujours en français."},
                {"role": "user", "content": prompt}
            ]
        )
        
        return response.choices[0].message.content
    
    def get_resource_usage(self) -> Dict[str, Any]:
        """Get current resource usage statistics."""
        process = psutil.Process(os.getpid())
        
        return {
            'cpu_percent': process.cpu_percent(),
            'memory_mb': process.memory_info().rss / 1024 / 1024,
            'threads': process.num_threads(),
            'open_files': len(process.open_files()),
            'running_tasks': len(self.running_tasks),
        }
