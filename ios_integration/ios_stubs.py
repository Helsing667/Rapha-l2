"""
iOS Stubs Module for Nexus Core.

This module provides placeholder implementations for iOS functionality
when the iOS integration module is disabled. It returns contextual responses
and logs requests for future analysis.

Features:
- Contextual adaptive responses
- Request logging for analysis
- File storage in pending directory
- Alternative local suggestions
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class StubResponse:
    """Represents a stub response for disabled iOS features."""
    message: str
    action_taken: str
    alternatives: List[str] = field(default_factory=list)
    logged: bool = True
    pending_path: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "message": self.message,
            "action_taken": self.action_taken,
            "alternatives": self.alternatives,
            "logged": self.logged,
            "pending_path": self.pending_path,
        }


class IOSStubs:
    """
    iOS functionality stubs.
    
    This class provides placeholder responses for iOS-related requests
    when the iOS integration module is disabled.
    
    Attributes:
        pending_dir: Directory for storing pending iOS transfers
        log_file: Path to iOS request log file
    """
    
    def __init__(self, pending_dir: str = "~/nexus_core/ios_pending"):
        """
        Initialize iOS stubs.
        
        Args:
            pending_dir: Directory for pending iOS transfers
        """
        self.pending_dir = Path(pending_dir).expanduser()
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = self.pending_dir / "ios_requests.log"
        
        logger.info(f"IOSStubs initialized (pending_dir={self.pending_dir})")
    
    def _log_request(self, request_type: str, request_text: str, metadata: Dict[str, Any] = None) -> None:
        """
        Log an iOS request for future analysis.
        
        Args:
            request_type: Type of iOS request
            request_text: Original request text
            metadata: Additional metadata
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "request_type": request_type,
            "request_text": request_text,
            "metadata": metadata or {},
        }
        
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to log iOS request: {e}")
    
    def handle_file_transfer(self, file_path: str, request_text: str = "") -> StubResponse:
        """
        Handle file transfer to iOS request (stub).
        
        Args:
            file_path: Path to file to transfer
            request_text: Original request text
            
        Returns:
            Stub response
        """
        # Copy file to pending directory
        from pathlib import Path
        import shutil
        
        source = Path(file_path).expanduser()
        if source.exists():
            dest = self.pending_dir / source.name
            try:
                shutil.copy2(str(source), str(dest))
                pending_path = str(dest)
            except Exception as e:
                pending_path = None
                logger.error(f"Failed to copy file to pending: {e}")
        else:
            pending_path = None
        
        # Log the request
        self._log_request("file_transfer", request_text, {"file_path": file_path})
        
        return StubResponse(
            message="Le module iOS est actuellement désactivé. Voici ce que je peux faire :",
            action_taken="file_staged",
            alternatives=[
                "1. Stocker le fichier dans ~/nexus_core/ios_pending/ pour un transfert ultérieur.",
                "2. Te guider pour activer le module iOS (nécessite une application iOS dédiée).",
                "3. Envoyer le fichier via un autre canal (email, cloud, etc.).",
            ],
            pending_path=pending_path,
        )
    
    def handle_camera_request(self, request_text: str = "") -> StubResponse:
        """
        Handle camera/photo request for iOS (stub).
        
        Args:
            request_text: Original request text
            
        Returns:
            Stub response
        """
        # Log the request
        self._log_request("camera", request_text)
        
        # Suggest local alternative
        alternatives = [
            "Je ne peux pas accéder à ton iPhone pour l'instant, mais voici comment prendre une photo avec ta webcam :",
            "  - Utilise la commande: cheese (si installée)",
            "  - Ou: ffmpeg -f video4linux2 -i /dev/video0 -frames:v 1 photo.jpg",
            "  - Ou active le module iOS avec: ./enable_ios.sh",
        ]
        
        return StubResponse(
            message="Le module iOS est désactivé. Alternatives locales :",
            action_taken="alternative_suggested",
            alternatives=alternatives,
        )
    
    def handle_reminder_request(self, title: str, due_date: str = None, request_text: str = "") -> StubResponse:
        """
        Handle reminder creation request for iOS (stub).
        
        Args:
            title: Reminder title
            due_date: Due date/time
            request_text: Original request text
            
        Returns:
            Stub response
        """
        # Log the request
        self._log_request("reminder", request_text, {"title": title, "due_date": due_date})
        
        # Save to pending
        reminder_data = {
            "type": "reminder",
            "title": title,
            "due_date": due_date,
            "created": datetime.now().isoformat(),
            "status": "pending_ios_activation",
        }
        
        reminder_file = self.pending_dir / f"reminder_{int(datetime.now().timestamp())}.json"
        try:
            with open(reminder_file, 'w') as f:
                json.dump(reminder_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save reminder: {e}")
        
        return StubResponse(
            message="Le module iOS est désactivé. Rappel enregistré en attente :",
            action_taken="reminder_saved_pending",
            alternatives=[
                f"Le rappel '{title}' sera créé sur ton iPhone lorsque le module iOS sera activé.",
                f"Fichier en attente: {reminder_file}",
            ],
            pending_path=str(reminder_file) if reminder_file.exists() else None,
        )
    
    def handle_photo_analysis(self, request_text: str = "") -> StubResponse:
        """
        Handle photo analysis request using iOS camera (stub).
        
        Args:
            request_text: Original request text
            
        Returns:
            Stub response
        """
        # Log the request
        self._log_request("photo_analysis", request_text)
        
        return StubResponse(
            message="L'analyse de photo via iOS n'est pas disponible. Alternatives :",
            action_taken="alternative_suggested",
            alternatives=[
                "1. Prends une photo avec ta webcam et utilise un modèle ML local.",
                "2. Active le module iOS pour utiliser Core ML sur iPhone.",
                "3. Utilise un service cloud d'analyse d'images.",
            ],
        )
    
    def handle_generic_ios_request(self, request_type: str, request_text: str) -> StubResponse:
        """
        Handle any generic iOS-related request (stub).
        
        Args:
            request_type: Type of iOS request
            request_text: Original request text
            
        Returns:
            Stub response
        """
        # Log the request
        self._log_request(request_type, request_text)
        
        return StubResponse(
            message=f"Cette fonctionnalité ({request_type}) sera disponible après activation du module iOS.",
            action_taken="request_logged",
            alternatives=[
                "1. La requête a été journalisée pour analyse future.",
                "2. Exécute ./enable_ios.sh pour activer le module iOS.",
                "3. Consulte ios_integration/ios_setup_guide.md pour la configuration.",
            ],
        )
    
    def get_pending_items(self) -> List[Dict[str, Any]]:
        """
        Get list of pending iOS items.
        
        Returns:
            List of pending item information
        """
        pending_items = []
        
        for item_file in self.pending_dir.glob("*.json"):
            try:
                with open(item_file, 'r') as f:
                    item_data = json.load(f)
                
                pending_items.append({
                    "file": str(item_file),
                    "type": item_data.get("type", "unknown"),
                    "created": item_data.get("created", "unknown"),
                })
            except Exception:
                continue
        
        # Also count non-JSON files (transferred files)
        file_count = len([f for f in self.pending_dir.iterdir() if f.is_file() and f.suffix != '.json'])
        
        return pending_items
    
    def get_status(self) -> Dict[str, Any]:
        """Get iOS stubs status."""
        return {
            "ios_enabled": False,
            "pending_dir": str(self.pending_dir),
            "pending_items_count": len(self.get_pending_items()),
            "log_file": str(self.log_file),
            "last_requests": self._get_recent_logs(),
        }
    
    def _get_recent_logs(self, count: int = 5) -> List[Dict[str, Any]]:
        """Get recent logged requests."""
        recent = []
        
        if not self.log_file.exists():
            return recent
        
        try:
            with open(self.log_file, 'r') as f:
                lines = f.readlines()
            
            for line in lines[-count:]:
                try:
                    recent.append(json.loads(line.strip()))
                except Exception:
                    continue
        except Exception:
            pass
        
        return recent


# Singleton instance
_stub_instance: Optional[IOSStubs] = None


def get_ios_stubs(pending_dir: str = "~/nexus_core/ios_pending") -> IOSStubs:
    """
    Get or create the iOS stubs singleton.
    
    Args:
        pending_dir: Directory for pending iOS transfers
        
    Returns:
        IOSStubs instance
    """
    global _stub_instance
    if _stub_instance is None:
        _stub_instance = IOSStubs(pending_dir)
    return _stub_instance
