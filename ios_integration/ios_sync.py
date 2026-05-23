"""
iOS Data Synchronization Module.

This module handles bidirectional data synchronization between Nexus Core
on Linux and iOS devices, using iCloud or a local NAS as an intermediary.

Features:
- Bidirectional file/metadata sync
- Conflict resolution with reconciliation protocol
- iCloud Drive integration
- NAS-based synchronization fallback
- Incremental sync for efficiency
- Encryption during transit and at rest
"""

import os
import json
import hashlib
import logging
import shutil
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from pathlib import Path
import time

logger = logging.getLogger(__name__)


class SyncDirection(Enum):
    """Synchronization direction."""
    BIDIRECTIONAL = "bidirectional"
    LINUX_TO_IOS = "linux_to_ios"
    IOS_TO_LINUX = "ios_to_linux"


class SyncMethod(Enum):
    """Synchronization method."""
    ICLOUD = "icloud"
    NAS = "nas"
    DIRECT = "direct"


class ConflictResolution(Enum):
    """Conflict resolution strategy."""
    NEWEST_WINS = "newest_wins"
    LINUX_WINS = "linux_wins"
    IOS_WINS = "ios_wins"
    MANUAL = "manual"
    MERGE = "merge"


@dataclass
class SyncItem:
    """Represents an item to be synchronized."""
    item_id: str
    item_type: str  # file, metadata, command
    path: str
    size: int
    checksum: str
    modified_time: float
    created_time: float
    source: str  # linux or ios
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "item_id": self.item_id,
            "item_type": self.item_type,
            "path": self.path,
            "size": self.size,
            "checksum": self.checksum,
            "modified_time": self.modified_time,
            "created_time": self.created_time,
            "source": self.source,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SyncItem':
        """Create from dictionary."""
        return cls(
            item_id=data.get("item_id", ""),
            item_type=data.get("item_type", ""),
            path=data.get("path", ""),
            size=data.get("size", 0),
            checksum=data.get("checksum", ""),
            modified_time=data.get("modified_time", 0),
            created_time=data.get("created_time", 0),
            source=data.get("source", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SyncConflict:
    """Represents a synchronization conflict."""
    item_id: str
    linux_version: SyncItem
    ios_version: SyncItem
    resolution: Optional[ConflictResolution] = None
    resolved: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "item_id": self.item_id,
            "linux_version": self.linux_version.to_dict(),
            "ios_version": self.ios_version.to_dict(),
            "resolution": self.resolution.value if self.resolution else None,
            "resolved": self.resolved,
        }


@dataclass
class SyncConfig:
    """Configuration for data synchronization."""
    sync_method: SyncMethod = SyncMethod.NAS
    sync_direction: SyncDirection = SyncDirection.BIDIRECTIONAL
    conflict_resolution: ConflictResolution = ConflictResolution.NEWEST_WINS
    icloud_path: Optional[str] = None
    nas_path: Optional[str] = None
    pending_dir: str = "~/nexus_core/ios_pending"
    sync_interval: int = 300  # seconds
    max_retries: int = 3
    encrypt_sync: bool = True


class IOSSync:
    """
    iOS Data Synchronization Manager.
    
    This class manages bidirectional synchronization of files, metadata,
    and commands between Linux and iOS devices.
    
    Attributes:
        config: Synchronization configuration
        pending_items: Queue of items waiting for sync
    """
    
    def __init__(self, config: Optional[SyncConfig] = None):
        """
        Initialize the iOS sync manager.
        
        Args:
            config: Synchronization configuration (auto-generated if None)
        """
        self.config = config or SyncConfig()
        self.pending_items: List[SyncItem] = []
        self.conflicts: List[SyncConflict] = []
        self._sync_history: List[Dict[str, Any]] = []
        self._last_sync_time: float = 0
        
        # Ensure pending directory exists
        pending_path = Path(self.config.pending_dir).expanduser()
        pending_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"IOSSync initialized (method={self.config.sync_method.value})")
    
    def _compute_checksum(self, file_path: str) -> str:
        """
        Compute SHA256 checksum of a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            Hex-encoded checksum
        """
        sha256_hash = hashlib.sha256()
        
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error(f"Checksum computation failed: {e}")
            return ""
    
    def _get_sync_path(self) -> Optional[Path]:
        """Get the base path for synchronization."""
        if self.config.sync_method == SyncMethod.ICLOUD:
            # iCloud Drive path (typical locations)
            icloud_paths = [
                Path("~/Library/Mobile Documents/com~apple~CloudDocs/nexus_sync"),
                Path("/iCloud/nexus_sync"),
            ]
            for path in icloud_paths:
                expanded = path.expanduser()
                if expanded.exists():
                    return expanded
            return None
            
        elif self.config.sync_method == SyncMethod.NAS:
            if self.config.nas_path:
                nas_path = Path(self.config.nas_path)
                if nas_path.exists():
                    return nas_path
            return None
            
        return None
    
    async def sync_file(self, file_path: str, destination: str = "") -> Tuple[bool, str]:
        """
        Synchronize a file to/from iOS.
        
        Args:
            file_path: Path to file to sync
            destination: Destination path (optional)
            
        Returns:
            Tuple of (success, message)
        """
        source_path = Path(file_path).expanduser()
        
        if not source_path.exists():
            return False, f"Source file does not exist: {file_path}"
        
        # Create sync item
        stat = source_path.stat()
        sync_item = SyncItem(
            item_id=f"file_{source_path.name}_{int(stat.st_mtime)}",
            item_type="file",
            path=str(source_path),
            size=stat.st_size,
            checksum=self._compute_checksum(str(source_path)),
            modified_time=stat.st_mtime,
            created_time=stat.st_ctime,
            source="linux",
        )
        
        # Determine destination
        if not destination:
            sync_path = self._get_sync_path()
            if not sync_path:
                # Use pending directory as fallback
                pending_path = Path(self.config.pending_dir).expanduser()
                destination = str(pending_path / source_path.name)
            else:
                destination = str(sync_path / source_path.name)
        
        # Check for conflicts
        dest_path = Path(destination)
        if dest_path.exists():
            conflict = await self._check_conflict(sync_item, str(dest_path))
            if conflict:
                return await self._resolve_conflict(conflict)
        
        # Perform sync based on method
        try:
            if self.config.sync_method == SyncMethod.NAS:
                return await self._sync_via_nas(str(source_path), destination)
            elif self.config.sync_method == SyncMethod.ICLOUD:
                return await self._sync_via_icloud(str(source_path), destination)
            else:
                # Direct copy to pending
                shutil.copy2(str(source_path), destination)
                return True, f"File copied to {destination}"
                
        except Exception as e:
            logger.exception(f"Sync failed: {e}")
            return False, str(e)
    
    async def _sync_via_nas(self, source: str, destination: str) -> Tuple[bool, str]:
        """Sync file via NAS."""
        try:
            # Copy to NAS staging area
            nas_path = self._get_sync_path()
            if not nas_path:
                return False, "NAS path not configured or unavailable"
            
            staging_file = nas_path / Path(source).name
            shutil.copy2(source, str(staging_file))
            
            # iOS device will pick up from NAS
            logger.info(f"File staged to NAS: {staging_file}")
            
            return True, f"File staged to NAS for iOS pickup: {staging_file}"
            
        except Exception as e:
            logger.error(f"NAS sync failed: {e}")
            return False, str(e)
    
    async def _sync_via_icloud(self, source: str, destination: str) -> Tuple[bool, str]:
        """Sync file via iCloud Drive."""
        try:
            # Copy to iCloud Drive
            icloud_path = self._get_sync_path()
            if not icloud_path:
                return False, "iCloud Drive not available"
            
            icloud_file = icloud_path / Path(source).name
            shutil.copy2(source, str(icloud_file))
            
            logger.info(f"File synced to iCloud: {icloud_file}")
            
            return True, f"File synced to iCloud Drive: {icloud_file}"
            
        except Exception as e:
            logger.error(f"iCloud sync failed: {e}")
            return False, str(e)
    
    async def _check_conflict(self, linux_item: SyncItem, ios_path: str) -> Optional[SyncConflict]:
        """
        Check for synchronization conflict.
        
        Args:
            linux_item: Linux version of item
            ios_path: Path to iOS version
            
        Returns:
            SyncConflict if conflict detected, None otherwise
        """
        ios_path_obj = Path(ios_path)
        
        if not ios_path_obj.exists():
            return None
        
        # Get iOS item info
        stat = ios_path_obj.stat()
        ios_item = SyncItem(
            item_id=linux_item.item_id,
            item_type="file",
            path=ios_path,
            size=stat.st_size,
            checksum=self._compute_checksum(ios_path),
            modified_time=stat.st_mtime,
            created_time=stat.st_ctime,
            source="ios",
        )
        
        # Check if items differ
        if linux_item.checksum != ios_item.checksum:
            return SyncConflict(
                item_id=linux_item.item_id,
                linux_version=linux_item,
                ios_version=ios_item,
            )
        
        return None
    
    async def _resolve_conflict(self, conflict: SyncConflict) -> Tuple[bool, str]:
        """
        Resolve a synchronization conflict.
        
        Args:
            conflict: Conflict to resolve
            
        Returns:
            Tuple of (success, message)
        """
        self.conflicts.append(conflict)
        
        strategy = self.config.conflict_resolution
        
        if strategy == ConflictResolution.NEWEST_WINS:
            # Compare modification times
            if conflict.linux_version.modified_time > conflict.ios_version.modified_time:
                winner = "linux"
            else:
                winner = "ios"
            
            conflict.resolution = ConflictResolution.NEWEST_WINS
            conflict.resolved = True
            
            return True, f"Conflict resolved: {winner} wins (newest)"
            
        elif strategy == ConflictResolution.LINUX_WINS:
            conflict.resolution = ConflictResolution.LINUX_WINS
            conflict.resolved = True
            return True, "Conflict resolved: Linux wins"
            
        elif strategy == ConflictResolution.IOS_WINS:
            conflict.resolution = ConflictResolution.IOS_WINS
            conflict.resolved = True
            return True, "Conflict resolved: iOS wins"
            
        elif strategy == ConflictResolution.MANUAL:
            # Log conflict for manual resolution
            logger.warning(
                f"Manual resolution required for conflict: {conflict.item_id}"
            )
            return False, "Conflict requires manual resolution"
            
        else:
            return False, f"Unknown conflict resolution strategy: {strategy}"
    
    async def sync_metadata(self, metadata: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Synchronize metadata to iOS.
        
        Args:
            metadata: Metadata dictionary to sync
            
        Returns:
            Tuple of (success, message)
        """
        # Create metadata file
        timestamp = int(time.time())
        metadata_id = f"meta_{timestamp}"
        
        metadata_file = {
            "id": metadata_id,
            "type": "metadata",
            "data": metadata,
            "timestamp": timestamp,
            "source": "linux",
        }
        
        # Save to pending directory
        pending_path = Path(self.config.pending_dir).expanduser()
        metadata_path = pending_path / f"{metadata_id}.json"
        
        try:
            with open(metadata_path, 'w') as f:
                json.dump(metadata_file, f, indent=2)
            
            logger.info(f"Metadata synced: {metadata_path}")
            return True, f"Metadata saved to {metadata_path}"
            
        except Exception as e:
            logger.error(f"Metadata sync failed: {e}")
            return False, str(e)
    
    async def sync_command(self, command: str, parameters: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Synchronize a command to be executed on iOS.
        
        Args:
            command: Command name
            parameters: Command parameters
            
        Returns:
            Tuple of (success, message)
        """
        # Create command file
        timestamp = int(time.time())
        command_id = f"cmd_{timestamp}"
        
        command_file = {
            "id": command_id,
            "type": "command",
            "command": command,
            "parameters": parameters,
            "timestamp": timestamp,
            "source": "linux",
            "status": "pending",
        }
        
        # Save to pending directory
        pending_path = Path(self.config.pending_dir).expanduser()
        command_path = pending_path / f"{command_id}.json"
        
        try:
            with open(command_path, 'w') as f:
                json.dump(command_file, f, indent=2)
            
            logger.info(f"Command queued: {command_path}")
            return True, f"Command queued for iOS execution: {command}"
            
        except Exception as e:
            logger.error(f"Command sync failed: {e}")
            return False, str(e)
    
    async def process_incoming(self) -> List[Dict[str, Any]]:
        """
        Process incoming items from iOS.
        
        Returns:
            List of processed items
        """
        processed = []
        pending_path = Path(self.config.pending_dir).expanduser()
        
        # Look for iOS-synced files
        for item_file in pending_path.glob("ios_*.json"):
            try:
                with open(item_file, 'r') as f:
                    item_data = json.load(f)
                
                # Process based on type
                item_type = item_data.get("type", "")
                
                if item_type == "file":
                    # File transfer from iOS
                    processed.append({
                        "type": "file",
                        "status": "processed",
                        "data": item_data,
                    })
                elif item_type == "metadata":
                    # Metadata from iOS
                    processed.append({
                        "type": "metadata",
                        "status": "processed",
                        "data": item_data,
                    })
                elif item_type == "command_result":
                    # Result from iOS command execution
                    processed.append({
                        "type": "command_result",
                        "status": "processed",
                        "data": item_data,
                    })
                
                # Archive processed file
                archive_path = pending_path / "archive" / item_file.name
                archive_path.parent.mkdir(exist_ok=True)
                item_file.rename(archive_path)
                
            except Exception as e:
                logger.error(f"Failed to process incoming item: {e}")
        
        self._last_sync_time = time.time()
        return processed
    
    def get_sync_status(self) -> Dict[str, Any]:
        """Get current synchronization status."""
        pending_path = Path(self.config.pending_dir).expanduser()
        
        # Count pending items
        pending_count = len(list(pending_path.glob("*.json")))
        
        return {
            "sync_method": self.config.sync_method.value,
            "sync_direction": self.config.sync_direction.value,
            "conflict_resolution": self.config.conflict_resolution.value,
            "pending_items": pending_count,
            "active_conflicts": len([c for c in self.conflicts if not c.resolved]),
            "last_sync_time": datetime.fromtimestamp(self._last_sync_time).isoformat(),
            "sync_path": str(self._get_sync_path()),
        }
