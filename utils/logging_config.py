"""
Logging configuration for Nexus Core.

This module sets up structured logging with separate streams for
audit logs and operational logs, with encryption support.

Features:
- Structured logging with structlog
- Separate audit and operations logs
- Log encryption
- Log rotation
"""

import os
import sys
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

try:
    import structlog
    STRUCTLOG_AVAILABLE = True
except ImportError:
    STRUCTLOG_AVAILABLE = False


class EncryptedFileHandler(RotatingFileHandler):
    """File handler that encrypts log entries."""
    
    def __init__(
        self,
        filename: str,
        encryption_manager=None,
        maxBytes: int = 104857600,  # 100MB
        backupCount: int = 7,
        encoding: str = 'utf-8',
        delay: bool = False,
    ):
        super().__init__(filename, maxBytes=maxBytes, backupCount=backupCount, 
                        encoding=encoding, delay=delay)
        self.encryption_manager = encryption_manager
    
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            
            if self.encryption_manager:
                msg = self.encryption_manager.encrypt_string(msg)
            
            stream = self.stream
            stream.write(msg + '\n')
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logging(
    log_level: str = "INFO",
    audit_log_path: Optional[str] = None,
    operations_log_path: Optional[str] = None,
    enable_encryption: bool = False,
    encryption_manager=None,
    console_output: bool = True,
) -> Dict[str, logging.Logger]:
    """
    Set up logging configuration for Nexus Core.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        audit_log_path: Path for audit logs
        operations_log_path: Path for operations logs
        enable_encryption: Whether to encrypt logs
        encryption_manager: EncryptionManager instance
        console_output: Whether to output to console
        
    Returns:
        Dictionary of configured loggers
    """
    # Create log directories
    if audit_log_path:
        Path(audit_log_path).parent.mkdir(parents=True, exist_ok=True)
    if operations_log_path:
        Path(operations_log_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_format)
        root_logger.addHandler(console_handler)
    
    # Audit log handler
    audit_logger = logging.getLogger('nexus.audit')
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False
    
    if audit_log_path:
        audit_handler_class = EncryptedFileHandler if enable_encryption else RotatingFileHandler
        audit_handler = audit_handler_class(
            audit_log_path,
            maxBytes=104857600,
            backupCount=30,
        )
        audit_handler.setLevel(logging.INFO)
        audit_format = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        audit_handler.setFormatter(audit_format)
        audit_logger.addHandler(audit_handler)
    
    # Operations log handler
    ops_logger = logging.getLogger('nexus.operations')
    ops_logger.setLevel(logging.DEBUG)
    ops_logger.propagate = False
    
    if operations_log_path:
        ops_handler_class = EncryptedFileHandler if enable_encryption else RotatingFileHandler
        ops_handler = ops_handler_class(
            operations_log_path,
            maxBytes=104857600,
            backupCount=7,
        )
        ops_handler.setLevel(logging.DEBUG)
        ops_handler.setFormatter(audit_format)
        ops_logger.addHandler(ops_handler)
    
    # Configure structlog if available
    if STRUCTLOG_AVAILABLE:
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    
    loggers = {
        'root': root_logger,
        'audit': audit_logger,
        'operations': ops_logger,
    }
    
    return loggers


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.
    
    Args:
        name: Logger name
        
    Returns:
        Logger instance
    """
    if STRUCTLOG_AVAILABLE:
        return structlog.get_logger(name)
    return logging.getLogger(name)
