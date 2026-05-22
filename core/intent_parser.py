"""
Intent Parser Module for Nexus Core.

This module analyzes user requests in natural language and converts them
into executable task graphs using semantic parsing and contextual validation.

Features:
- Multi-language support (fr, en, de, es)
- Semantic analysis using spaCy
- Contextual disambiguation
- Intent classification with confidence scoring
"""

import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

import spacy
from spacy.tokens import Doc

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """Types of intents that can be parsed."""
    FILE_OPERATION = "file_operation"
    MESSAGE_SEND = "message_send"
    SYSTEM_COMMAND = "system_command"
    API_CALL = "api_call"
    MOBILE_ACTION = "mobile_action"
    QUERY = "query"
    UNKNOWN = "unknown"


class PrivilegeLevel(Enum):
    """Privilege levels required for task execution."""
    USER = "user"
    SUDO = "sudo"
    ROOT = "root"
    API = "api"


@dataclass
class ParsedIntent:
    """Represents a parsed user intent."""
    intent_type: IntentType
    confidence: float
    original_text: str
    entities: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    privilege_level: PrivilegeLevel = PrivilegeLevel.USER
    requires_confirmation: bool = False
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "intent_type": self.intent_type.value,
            "confidence": self.confidence,
            "original_text": self.original_text,
            "entities": self.entities,
            "parameters": self.parameters,
            "privilege_level": self.privilege_level.value,
            "requires_confirmation": self.requires_confirmation,
            "context": self.context,
        }


class IntentParser:
    """
    Parser for natural language user requests.
    
    This class uses spaCy for semantic analysis and custom rules for
    disambiguation. It supports multiple languages and provides confidence
    scoring for parsed intents.
    
    Attributes:
        language: The language code for parsing (e.g., 'fr', 'en')
        confidence_threshold: Minimum confidence score to accept a parse
        nlp: The spaCy NLP pipeline
    """
    
    # Patterns for intent detection (language-specific)
    PATTERNS = {
        'fr': {
            'file_operations': [
                r'(ouvrir|lire|écrire|modifier|supprimer|copier|déplacer|créer)\s+(le\s+fichier|la\s+fichier|fichier)?\s*(.+)',
                r'(accéder\s+à|aller\s+dans)\s+(.+)',
            ],
            'message_send': [
                r'(envoyer|transmettre|faire\s+parvenir)\s+(un\s+)?(message|sms|whatsapp|email)\s+à\s+(\w+)\s+(avec|disant|texte)[\s:]+["\']?(.+?)["\']?',
                r'(envoie|envoi)\s+un?\s+(message|sms)\s+à\s+(\w+)',
            ],
            'system_command': [
                r'(exécuter|lancer|démarrer|arrêter|redémarrer)\s+(le\s+)?(.+)',
                r'(liste|affiche|montre)\s+(les\s+)?(.+)',
            ],
            'mobile_action': [
                r'(sur\s+le\s+(téléphone|mobile)|via\s+le\s+mobile)\s+(.+)',
                r'(envoie|ouvre|ferme)\s+(sur\s+)?(le\s+)?(téléphone|mobile)',
            ],
        },
        'en': {
            'file_operations': [
                r'(open|read|write|modify|delete|copy|move|create)\s+(the\s+)?file\s*(.+)',
                r'(access|go\s+to)\s+(.+)',
            ],
            'message_send': [
                r'(send|transmit)\s+(a\s+)?(message|sms|whatsapp|email)\s+to\s+(\w+)\s+(with|saying|text)[\s:]+["\']?(.+?)["\']?',
            ],
            'system_command': [
                r'(execute|run|start|stop|restart)\s+(the\s+)?(.+)',
                r'(list|show|display)\s+(the\s+)?(.+)',
            ],
        },
    }
    
    def __init__(
        self,
        language: str = "fr",
        confidence_threshold: float = 0.7,
        model_name: Optional[str] = None,
    ):
        """
        Initialize the Intent Parser.
        
        Args:
            language: Language code for parsing ('fr', 'en', 'de', 'es')
            confidence_threshold: Minimum confidence score to accept a parse
            model_name: Optional spaCy model name (auto-detected if None)
        """
        self.language = language
        self.confidence_threshold = confidence_threshold
        
        # Determine spaCy model based on language
        if model_name is None:
            model_map = {
                'fr': 'fr_core_news_md',
                'en': 'en_core_web_md',
                'de': 'de_core_news_md',
                'es': 'es_core_news_md',
            }
            model_name = model_map.get(language, 'fr_core_news_md')
        
        try:
            self.nlp = spacy.load(model_name)
            logger.info(f"Loaded spaCy model: {model_name}")
        except OSError:
            logger.warning(
                f"spaCy model '{model_name}' not found. "
                f"Install it with: python -m spacy download {model_name}"
            )
            # Fallback to minimal processing
            self.nlp = None
        
        # Compile regex patterns for current language
        self.compiled_patterns = self._compile_patterns()
        
        logger.info(f"IntentParser initialized for language: {language}")
    
    def _compile_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Compile regex patterns for the current language."""
        compiled = {}
        lang_patterns = self.PATTERNS.get(self.language, self.PATTERNS['fr'])
        
        for intent_category, patterns in lang_patterns.items():
            compiled[intent_category] = [
                re.compile(pattern, re.IGNORECASE)
                for pattern in patterns
            ]
        
        return compiled
    
    def parse(self, text: str) -> ParsedIntent:
        """
        Parse a user request into a structured intent.
        
        Args:
            text: The user's natural language request
            
        Returns:
            ParsedIntent object containing the parsed intent
        """
        logger.debug(f"Parsing request: {text[:100]}...")
        
        # Try pattern matching first
        intent, confidence, params = self._match_patterns(text)
        
        if intent and confidence >= self.confidence_threshold:
            parsed = ParsedIntent(
                intent_type=intent,
                confidence=confidence,
                original_text=text,
                parameters=params,
            )
            
            # Enrich with NLP if available
            if self.nlp:
                parsed = self._enrich_with_nlp(parsed, text)
            
            # Determine privilege level
            parsed.privilege_level = self._determine_privilege(parsed)
            
            # Check if confirmation is required
            parsed.requires_confirmation = self._check_confirmation_needed(parsed)
            
            logger.info(
                f"Parsed intent: {parsed.intent_type.value} "
                f"(confidence: {confidence:.2f})"
            )
            
            return parsed
        
        # Fallback to unknown intent
        logger.warning(f"Could not parse intent with sufficient confidence: {text}")
        return ParsedIntent(
            intent_type=IntentType.UNKNOWN,
            confidence=confidence or 0.0,
            original_text=text,
            parameters={"raw_text": text},
        )
    
    def _match_patterns(
        self, text: str
    ) -> Tuple[Optional[IntentType], float, Dict[str, Any]]:
        """
        Match text against known patterns.
        
        Args:
            text: Input text to match
            
        Returns:
            Tuple of (IntentType, confidence, parameters)
        """
        best_match = None
        best_confidence = 0.0
        best_params = {}
        
        for category, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    confidence = 0.8  # Base confidence for pattern match
                    params = self._extract_parameters(category, match, text)
                    
                    # Adjust confidence based on match quality
                    matched_length = match.end() - match.start()
                    confidence += min(0.2, matched_length / len(text) * 0.2)
                    
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_params = params
                        best_match = self._category_to_intent(category)
        
        return best_match, best_confidence, best_params
    
    def _extract_parameters(
        self, category: str, match: re.Match, text: str
    ) -> Dict[str, Any]:
        """
        Extract parameters from a regex match.
        
        Args:
            category: Intent category
            match: Regex match object
            text: Original text
            
        Returns:
            Dictionary of extracted parameters
        """
        params = {}
        groups = match.groups()
        
        if category == 'message_send':
            # Pattern: send message to X with text Y
            if len(groups) >= 5:
                params['recipient'] = groups[-2] if groups[-2] else groups[-3]
                params['message_text'] = groups[-1]
                params['platform'] = 'whatsapp' if 'whatsapp' in text.lower() else 'sms'
        
        elif category == 'file_operations':
            # Pattern: action on file path
            if groups:
                action = groups[0].lower() if groups[0] else 'open'
                params['action'] = action
                params['path'] = groups[-1] if groups[-1] else ''
                
                # Extract file attachments mentioned
                if 'join' in text.lower() or 'attach' in text.lower():
                    file_match = re.search(r'/[\w/.-]+\.\w+', text)
                    if file_match:
                        params['attachment'] = file_match.group()
        
        elif category == 'system_command':
            if len(groups) >= 2:
                params['command'] = groups[0].lower() if groups[0] else ''
                params['target'] = groups[-1] if groups[-1] else ''
        
        return params
    
    def _category_to_intent(self, category: str) -> IntentType:
        """Convert category string to IntentType enum."""
        mapping = {
            'file_operations': IntentType.FILE_OPERATION,
            'message_send': IntentType.MESSAGE_SEND,
            'system_command': IntentType.SYSTEM_COMMAND,
            'mobile_action': IntentType.MOBILE_ACTION,
        }
        return mapping.get(category, IntentType.UNKNOWN)
    
    def _enrich_with_nlp(self, parsed: ParsedIntent, text: str) -> ParsedIntent:
        """
        Enrich parsed intent with NLP analysis.
        
        Args:
            parsed: Current parsed intent
            text: Original text
            
        Returns:
            Enriched ParsedIntent
        """
        if not self.nlp:
            return parsed
        
        doc: Doc = self.nlp(text)
        
        # Extract named entities
        entities = {}
        for ent in doc.ents:
            label = ent.label_
            if label not in entities:
                entities[label] = []
            entities[label].append(ent.text)
        
        parsed.entities = entities
        
        # Extract additional context from dependencies
        for token in doc:
            if token.dep_ in ("dobj", "pobj"):
                if "objects" not in parsed.parameters:
                    parsed.parameters["objects"] = []
                parsed.parameters["objects"].append(token.text)
        
        return parsed
    
    def _determine_privilege(self, parsed: ParsedIntent) -> PrivilegeLevel:
        """
        Determine the privilege level required for an intent.
        
        Args:
            parsed: Parsed intent
            
        Returns:
            Required PrivilegeLevel
        """
        # File operations in system directories require sudo
        if parsed.intent_type == IntentType.FILE_OPERATION:
            path = parsed.parameters.get('path', '')
            system_paths = ['/etc', '/usr', '/var', '/root', '/boot']
            if any(path.startswith(p) for p in system_paths):
                return PrivilegeLevel.SUDO
        
        # System commands often require elevated privileges
        if parsed.intent_type == IntentType.SYSTEM_COMMAND:
            command = parsed.parameters.get('command', '').lower()
            privileged_commands = ['install', 'remove', 'update', 'upgrade', ' systemctl']
            if any(cmd in command for cmd in privileged_commands):
                return PrivilegeLevel.SUDO
        
        # API calls have their own privilege level
        if parsed.intent_type == IntentType.API_CALL:
            return PrivilegeLevel.API
        
        return PrivilegeLevel.USER
    
    def _check_confirmation_needed(self, parsed: ParsedIntent) -> bool:
        """
        Check if an intent requires user confirmation.
        
        Args:
            parsed: Parsed intent
            
        Returns:
            True if confirmation is required
        """
        # Deletion operations always require confirmation
        if parsed.intent_type == IntentType.FILE_OPERATION:
            action = parsed.parameters.get('action', '').lower()
            if 'delete' in action or 'supprimer' in action:
                return True
        
        # System modifications require confirmation
        if parsed.privilege_level in (PrivilegeLevel.SUDO, PrivilegeLevel.ROOT):
            return True
        
        # Mobile actions may require confirmation
        if parsed.intent_type == IntentType.MOBILE_ACTION:
            return True
        
        return False
    
    def batch_parse(self, texts: List[str]) -> List[ParsedIntent]:
        """
        Parse multiple requests efficiently.
        
        Args:
            texts: List of texts to parse
            
        Returns:
            List of ParsedIntent objects
        """
        return [self.parse(text) for text in texts]
    
    def validate_intent(self, parsed: ParsedIntent) -> bool:
        """
        Validate that a parsed intent is complete and consistent.
        
        Args:
            parsed: Parsed intent to validate
            
        Returns:
            True if the intent is valid
        """
        if parsed.intent_type == IntentType.UNKNOWN:
            return False
        
        if parsed.confidence < self.confidence_threshold:
            return False
        
        # Check required parameters based on intent type
        if parsed.intent_type == IntentType.MESSAGE_SEND:
            if 'recipient' not in parsed.parameters or 'message_text' not in parsed.parameters:
                return False
        
        if parsed.intent_type == IntentType.FILE_OPERATION:
            if 'path' not in parsed.parameters and 'action' not in parsed.parameters:
                return False
        
        return True
