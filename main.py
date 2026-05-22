#!/usr/bin/env python3
"""
Nexus Core - Main Entry Point

This is the main entry point for the Nexus Core autonomous AI system.
It initializes all components and provides the primary interface for
user interaction.

Usage:
    python main.py
    python main.py --config config.yaml
"""

import argparse
import asyncio
import signal
import sys
from typing import Optional, Dict, Any
from pathlib import Path
import logging
import yaml

from core.intent_parser import IntentParser, ParsedIntent
from core.task_orchestrator import TaskOrchestrator, TaskGraph
from core.execution_engine import ExecutionEngine
from core.security_layer import SecurityLayer
from utils.logging_config import setup_logging
from utils.encryption import EncryptionManager
from utils.api_wrapper import MistralAPIWrapper
from utils.mobile_client import MobileClient, MobileConnectionConfig


class NexusCore:
    """
    Main Nexus Core orchestrator class.
    
    This class coordinates all components of the Nexus Core system:
    - Intent parsing
    - Task orchestration
    - Task execution
    - Security monitoring
    - API integration
    - Mobile device control
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize Nexus Core.
        
        Args:
            config_path: Path to configuration file
        """
        self.config = self._load_config(config_path)
        self.logger = logging.getLogger("nexus.core")
        
        # Initialize components
        self.encryption_manager = EncryptionManager()
        self.security_layer = SecurityLayer(
            enable_isolation=self.config.get('security', {}).get('enable_isolation', True),
            enable_anomaly_detection=self.config.get('security', {}).get('enable_anomaly_detection', True),
            anomaly_threshold=self.config.get('security', {}).get('anomaly_threshold', 0.85),
        )
        
        self.intent_parser = IntentParser(
            language=self.config.get('intent_parser', {}).get('default_language', 'fr'),
            confidence_threshold=self.config.get('intent_parser', {}).get('confidence_threshold', 0.7),
        )
        
        self.orchestrator = TaskOrchestrator(
            max_parallel_tasks=self.config.get('orchestrator', {}).get('max_parallel_tasks', 10),
            default_timeout=self.config.get('orchestrator', {}).get('default_task_timeout', 300),
        )
        
        self.execution_engine = ExecutionEngine(
            max_workers=self.config.get('execution', {}).get('max_workers', 8),
            pool_type=self.config.get('execution', {}).get('pool_type', 'thread'),
            enable_rollback=self.config.get('execution', {}).get('enable_auto_rollback', True),
        )
        
        # Initialize Mistral API if key available
        self.mistral_api: Optional[MistralAPIWrapper] = None
        api_key = self.encryption_manager.retrieve_secret('mistral_api_key')
        if api_key:
            self.mistral_api = MistralAPIWrapper(api_key=api_key)
        
        # Initialize mobile client if enabled
        self.mobile_client: Optional[MobileClient] = None
        if self.config.get('mobile', {}).get('enabled', False):
            mobile_config = self.config.get('mobile', {}).get('ssh', {})
            
            # Get host IP - use phone_ip if available, otherwise fallback to host
            host = mobile_config.get('host', 'localhost')
            # Override with phone_ip if explicitly set (and not placeholder)
            phone_ip = self.config.get('mobile', {}).get('phone_ip', '')
            if phone_ip and phone_ip != 'PHONE_IP_ADDRESS':
                host = phone_ip
            
            self.mobile_client = MobileClient(
                config=MobileConnectionConfig(
                    host=host,
                    port=mobile_config.get('port', 8022),
                    username=mobile_config.get('username', 'u0_a123'),
                    key_path=mobile_config.get('key_path'),
                )
            )
        
        # State
        self.running = False
        self.current_graph: Optional[TaskGraph] = None
        
        self.logger.info("Nexus Core initialized")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        path = Path(config_path)
        if not path.exists():
            return {}
        
        with open(path, 'r') as f:
            return yaml.safe_load(f) or {}
    
    def start(self) -> None:
        """Start Nexus Core services."""
        self.logger.info("Starting Nexus Core...")
        
        # Set up logging
        log_config = self.config.get('system', {})
        setup_logging(
            log_level=log_config.get('log_level', 'INFO'),
            audit_log_path=log_config.get('audit_log_path'),
            operations_log_path=log_config.get('operations_log_path'),
            enable_encryption=log_config.get('encrypt_logs', False),
            encryption_manager=self.encryption_manager,
        )
        
        # Start execution engine
        self.execution_engine.start()
        
        # Start mobile auto-reconnect if enabled
        if self.mobile_client:
            self.mobile_client.start_auto_reconnect()
        
        self.running = True
        self.logger.info("Nexus Core started successfully")
    
    def stop(self) -> None:
        """Stop Nexus Core services."""
        self.logger.info("Stopping Nexus Core...")
        
        self.running = False
        
        # Stop mobile client
        if self.mobile_client:
            self.mobile_client.stop_auto_reconnect()
            self.mobile_client.disconnect()
        
        # Stop execution engine
        self.execution_engine.stop(wait=True)
        
        # Clean up sensitive data
        self.encryption_manager.cleanup()
        
        self.logger.info("Nexus Core stopped")
    
    async def process_request(self, request: str) -> Dict[str, Any]:
        """
        Process a user request through the full pipeline.
        
        Args:
            request: User's natural language request
            
        Returns:
            Result dictionary with status and output
        """
        self.logger.info(f"Processing request: {request[:100]}...")
        
        # Step 1: Parse intent
        parsed_intent = self.intent_parser.parse(request)
        
        if parsed_intent.intent_type.value == 'unknown':
            return {
                "success": False,
                "error": "Could not understand request",
                "confidence": parsed_intent.confidence,
            }
        
        # Step 2: Security validation
        is_valid, security_event = self.security_layer.validate_request(
            action=parsed_intent.intent_type.value,
            parameters=parsed_intent.parameters,
            privilege_level=parsed_intent.privilege_level.value,
        )
        
        if not is_valid:
            return {
                "success": False,
                "error": f"Security violation: {security_event.description}",
                "blocked": True,
            }
        
        # Step 3: Check if confirmation needed
        if parsed_intent.requires_confirmation:
            # In production, this would prompt the user
            self.logger.warning(f"Confirmation required for: {parsed_intent.intent_type.value}")
        
        # Step 4: Decompose into task graph
        self.current_graph = self.orchestrator.decompose_intent(
            parsed_intent.to_dict()
        )
        
        # Step 5: Execute tasks
        results = []
        graph_id = self.current_graph.id
        
        while True:
            # Get ready tasks
            ready_tasks = self.orchestrator.get_next_executable_tasks(graph_id)
            
            if not ready_tasks:
                # Check if all tasks are done
                status = self.orchestrator.get_graph_status(graph_id)
                if status.get('progress', 0) >= 100:
                    break
                elif status.get('status') == 'failed':
                    break
                continue
            
            # Execute tasks (respecting parallel limit)
            exec_results = self.execution_engine.execute_parallel(
                ready_tasks,
                max_parallel=self.orchestrator.max_parallel_tasks,
            )
            
            # Update orchestrator with results
            for task_id, result in exec_results.items():
                if result.success:
                    self.orchestrator.mark_task_completed(
                        graph_id, task_id, result.output
                    )
                else:
                    self.orchestrator.mark_task_failed(
                        graph_id, task_id, result.error
                    )
                    
                    # Check if rollback needed
                    if result.rollback_performed:
                        results.append({
                            "task_id": task_id,
                            "status": "rolled_back",
                        })
            
            results.extend([
                {"task_id": tid, "success": r.success}
                for tid, r in exec_results.items()
            ])
        
        # Finalize graph
        success = self.orchestrator.finalize_graph(graph_id)
        
        return {
            "success": success,
            "graph_id": graph_id,
            "intent": parsed_intent.intent_type.value,
            "results": results,
        }
    
    def run_interactive(self) -> None:
        """Run Nexus Core in interactive mode."""
        print("\n" + "="*60)
        print("NEXUS CORE - Autonomous AI System")
        print("="*60)
        print("Type 'quit' or 'exit' to stop\n")
        
        while self.running:
            try:
                user_input = input("> ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() in ('quit', 'exit', 'q'):
                    break
                
                # Process request asynchronously
                result = asyncio.run(self.process_request(user_input))
                
                # Display result
                if result['success']:
                    print(f"\n✓ Request completed successfully")
                    print(f"  Intent: {result['intent']}")
                    print(f"  Tasks executed: {len(result.get('results', []))}\n")
                else:
                    print(f"\n✗ Request failed")
                    print(f"  Error: {result.get('error', 'Unknown error')}\n")
                
            except KeyboardInterrupt:
                print("\nInterrupted")
                break
            except Exception as e:
                self.logger.exception(f"Error processing request: {e}")
                print(f"\nError: {e}\n")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current system status."""
        return {
            "running": self.running,
            "components": {
                "intent_parser": "ready",
                "orchestrator": "ready",
                "execution_engine": "running" if self.execution_engine.executor else "stopped",
                "security_layer": "active",
                "mistral_api": "connected" if self.mistral_api else "not configured",
                "mobile_client": "connected" if (self.mobile_client and self.mobile_client.connected) else "disconnected",
            },
            "resource_usage": self.execution_engine.get_resource_usage(),
            "security_events": len(list(self.security_layer.events)),
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Nexus Core - Autonomous AI System")
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to configuration file",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive mode",
    )
    parser.add_argument(
        "--request",
        type=str,
        help="Process a single request",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show system status and exit",
    )
    
    args = parser.parse_args()
    
    # Create and start Nexus Core
    nexus = NexusCore(config_path=args.config)
    
    # Handle shutdown signals
    def signal_handler(sig, frame):
        print("\nShutting down...")
        nexus.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        nexus.start()
        
        if args.status:
            import json
            print(json.dumps(nexus.get_status(), indent=2))
        elif args.request:
            result = asyncio.run(nexus.process_request(args.request))
            import json
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.interactive:
            nexus.run_interactive()
        else:
            # Default to interactive mode
            nexus.run_interactive()
    
    finally:
        nexus.stop()


if __name__ == "__main__":
    main()
