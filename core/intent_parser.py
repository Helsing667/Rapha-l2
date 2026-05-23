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
    GREETING = "greeting"
    JOKE = "joke"
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
            'greeting': [
                r'(bonjour|salut|coucou|hey|hello|bonne\s+journée|bonne\s+soirée)',
                r'(ça\s+va|comment\s+(vas|allez)\s+tu|comment\s+ça\s+va)',
            ],
            'joke': [
                r'(raconte|dis)\s+(moi\s+)?(une\s+)?(blague|histoire\s+drôle)',
                r'(je\s+veux\s+(rire|une\s+blague)|fais\s+moi\s+rire)',
            ],
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
            'greeting': [
                r'(hello|hi|hey|good\s+(morning|afternoon|evening))',
                r'(how\s+(are\s+)?you|what\'?s\s+up)',
            ],
            'joke': [
                r'(tell\s+me\s+)?(a\s+)?(joke|funny\s+story)',
                r'(i\s+want\s+to\s+laugh|make\s+me\s+laugh)',
            ],
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
        confidence_threshold: float = 0.45,
        model_name: Optional[str] = None,
    ):
        """
        Initialize the Intent Parser.
        
        Args:
            language: Language code for parsing ('fr', 'en', 'de', 'es')
            confidence_threshold: Minimum confidence score to accept a parse (dynamic, default 0.45)
            model_name: Optional spaCy model name (auto-detected if None)
        """
        self.language = language
        self.base_confidence_threshold = confidence_threshold
        self.confidence_threshold = self._compute_dynamic_threshold(confidence_threshold)
        
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
    
    def _compute_dynamic_threshold(self, base_threshold: float) -> float:
        """
        Compute dynamic confidence threshold based on context.
        
        Args:
            base_threshold: Base threshold value
            
        Returns:
            Adjusted threshold based on various factors
        """
        # Dynamic adjustment: lower threshold for short queries, higher for complex ones
        # This can be extended with more sophisticated logic
        adjusted = base_threshold
        logger.debug(f"Computing dynamic threshold: base={base_threshold}, adjusted={adjusted}")
        return adjusted
    
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
        logger.info(f"[PARSE] Starting parsing of: '{text[:100]}...'")
        logger.debug(f"[PARSE] Current confidence threshold: {self.confidence_threshold}")
        
        # Try pattern matching first
        logger.debug("[PARSE] Attempting pattern matching...")
        intent, confidence, params = self._match_patterns(text)
        logger.debug(f"[PARSE] Pattern matching result: intent={intent}, confidence={confidence:.2f}")
        
        if intent and confidence >= self.confidence_threshold:
            logger.info(f"[PARSE] Pattern matched with sufficient confidence: {intent.value} ({confidence:.2f})")
            parsed = ParsedIntent(
                intent_type=intent,
                confidence=confidence,
                original_text=text,
                parameters=params,
            )
            
            # Enrich with NLP if available
            if self.nlp:
                logger.debug("[PARSE] Enriching with NLP analysis...")
                parsed = self._enrich_with_nlp(parsed, text)
                logger.debug(f"[PARSE] NLP enrichment complete. Entities: {parsed.entities}")
            else:
                logger.debug("[PARSE] NLP not available, skipping enrichment")
            
            # Determine privilege level
            logger.debug("[PARSE] Determining privilege level...")
            parsed.privilege_level = self._determine_privilege(parsed)
            logger.debug(f"[PARSE] Privilege level: {parsed.privilege_level.value}")
            
            # Check if confirmation is required
            logger.debug("[PARSE] Checking if confirmation is needed...")
            parsed.requires_confirmation = self._check_confirmation_needed(parsed)
            logger.debug(f"[PARSE] Confirmation required: {parsed.requires_confirmation}")
            
            logger.info(
                f"[PARSE] Successfully parsed intent: {parsed.intent_type.value} "
                f"(confidence: {confidence:.2f})"
            )
            
            return parsed
        
        # Fallback to unknown intent with French response
        logger.warning(f"[PARSE] Could not parse intent with sufficient confidence: '{text}'")
        fallback_response = self._handle_fallback(text)
        logger.info(f"[PARSE] Fallback handler returned: '{fallback_response[:50]}...'")
        
        return ParsedIntent(
            intent_type=IntentType.UNKNOWN,
            confidence=confidence or 0.0,
            original_text=text,
            parameters={"raw_text": text, "fallback_response": fallback_response},
        )
    
    def _handle_fallback(self, text: str) -> str:
        """
        Handle unrecognized intents with a French fallback response.
        
        Args:
            text: The original user input
            
        Returns:
            A French fallback response string
        """
        logger.debug(f"[FALLBACK] Handling fallback for: '{text[:50]}...'")
        
        fallback_responses = [
            "Je n'ai pas compris votre demande. Pourriez-vous reformuler ?",
            "Désolé, je ne suis pas sûr de comprendre. Pouvez-vous être plus précis ?",
            "Je ne peux pas traiter cette demande. Essayez une autre formulation.",
            "Je n'arrive pas à identifier votre intention. Reformulez s'il vous plaît.",
        ]
        
        # Select a random fallback response (using simple index based on text length)
        response = fallback_responses[len(text) % len(fallback_responses)]
        logger.info(f"[FALLBACK] Returning response: '{response}'")
        return response
    
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
        logger.debug(f"[MATCH] Starting pattern matching for: '{text[:50]}...'")
        best_match = None
        best_confidence = 0.0
        best_params = {}
        
        for category, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    logger.debug(f"[MATCH] Pattern matched for category '{category}': {pattern.pattern[:30]}...")
                    confidence = 0.8  # Base confidence for pattern match
                    params = self._extract_parameters(category, match, text)
                    
                    # Adjust confidence based on match quality
                    matched_length = match.end() - match.start()
                    confidence += min(0.2, matched_length / len(text) * 0.2)
                    
                    logger.debug(f"[MATCH] Category '{category}' confidence: {confidence:.2f}")
                    
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_params = params
                        best_match = self._category_to_intent(category)
                        logger.debug(f"[MATCH] New best match: {best_match.value} with confidence {best_confidence:.2f}")
        
        logger.debug(f"[MATCH] Final result: intent={best_match}, confidence={best_confidence:.2f}")
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
        logger.debug(f"[CATEGORY] Converting category '{category}' to IntentType")
        mapping = {
            'file_operations': IntentType.FILE_OPERATION,
            'message_send': IntentType.MESSAGE_SEND,
            'system_command': IntentType.SYSTEM_COMMAND,
            'mobile_action': IntentType.MOBILE_ACTION,
            'greeting': IntentType.GREETING,
            'joke': IntentType.JOKE,
        }
        result = mapping.get(category, IntentType.UNKNOWN)
        logger.debug(f"[CATEGORY] Result: {result.value}")
        return result
    
    def _enrich_with_nlp(self, parsed: ParsedIntent, text: str) -> ParsedIntent:
        """
        Enrich parsed intent with NLP analysis.
        
        Args:
            parsed: Current parsed intent
            text: Original text
            
        Returns:
            Enriched ParsedIntent
        """
        logger.debug(f"[NLP] Starting NLP enrichment for intent: {parsed.intent_type.value}")
        if not self.nlp:
            logger.debug("[NLP] NLP pipeline not available, skipping enrichment")
            return parsed
        
        doc: Doc = self.nlp(text)
        logger.debug(f"[NLP] Processed text with spaCy, found {len(doc.ents)} entities")
        
        # Extract named entities
        entities = {}
        for ent in doc.ents:
            label = ent.label_
            if label not in entities:
                entities[label] = []
            entities[label].append(ent.text)
        
        parsed.entities = entities
        logger.debug(f"[NLP] Extracted entities: {entities}")
        
        # Extract additional context from dependencies
        for token in doc:
            if token.dep_ in ("dobj", "pobj"):
                if "objects" not in parsed.parameters:
                    parsed.parameters["objects"] = []
                parsed.parameters["objects"].append(token.text)
        
        logger.debug(f"[NLP] Enrichment complete. Parameters: {parsed.parameters}")
        return parsed
    
    def _determine_privilege(self, parsed: ParsedIntent) -> PrivilegeLevel:
        """
        Determine the privilege level required for an intent.
        
        Args:
            parsed: Parsed intent
            
        Returns:
            Required PrivilegeLevel
        """
        logger.debug(f"[PRIVILEGE] Determining privilege for intent: {parsed.intent_type.value}")
        
        # File operations in system directories require sudo
        if parsed.intent_type == IntentType.FILE_OPERATION:
            path = parsed.parameters.get('path', '')
            system_paths = ['/etc', '/usr', '/var', '/root', '/boot']
            if any(path.startswith(p) for p in system_paths):
                logger.debug("[PRIVILEGE] System path detected, returning SUDO")
                return PrivilegeLevel.SUDO
        
        # System commands often require elevated privileges
        if parsed.intent_type == IntentType.SYSTEM_COMMAND:
            command = parsed.parameters.get('command', '').lower()
            privileged_commands = ['install', 'remove', 'update', 'upgrade', ' systemctl']
            if any(cmd in command for cmd in privileged_commands):
                logger.debug("[PRIVILEGE] Privileged command detected, returning SUDO")
                return PrivilegeLevel.SUDO
        
        # API calls have their own privilege level
        if parsed.intent_type == IntentType.API_CALL:
            logger.debug("[PRIVILEGE] API call detected, returning API")
            return PrivilegeLevel.API
        
        # Greeting and joke intents always return USER level
        if parsed.intent_type in (IntentType.GREETING, IntentType.JOKE):
            logger.debug("[PRIVILEGE] Social intent detected, returning USER")
            return PrivilegeLevel.USER
        
        logger.debug("[PRIVILEGE] Defaulting to USER level")
        return PrivilegeLevel.USER
    
    def _check_confirmation_needed(self, parsed: ParsedIntent) -> bool:
        """
        Check if an intent requires user confirmation.
        
        Args:
            parsed: Parsed intent
            
        Returns:
            True if confirmation is required
        """
        logger.debug(f"[CONFIRMATION] Checking confirmation for intent: {parsed.intent_type.value}")
        
        # Deletion operations always require confirmation
        if parsed.intent_type == IntentType.FILE_OPERATION:
            action = parsed.parameters.get('action', '').lower()
            if 'delete' in action or 'supprimer' in action:
                logger.debug("[CONFIRMATION] Deletion operation requires confirmation")
                return True
        
        # System modifications require confirmation
        if parsed.privilege_level in (PrivilegeLevel.SUDO, PrivilegeLevel.ROOT):
            logger.debug("[CONFIRMATION] Elevated privilege requires confirmation")
            return True
        
        # Mobile actions may require confirmation
        if parsed.intent_type == IntentType.MOBILE_ACTION:
            logger.debug("[CONFIRMATION] Mobile action requires confirmation")
            return True
        
        # Greeting and joke intents never require confirmation
        if parsed.intent_type in (IntentType.GREETING, IntentType.JOKE):
            logger.debug("[CONFIRMATION] Social intent does not require confirmation")
            return False
        
        logger.debug("[CONFIRMATION] No confirmation required")
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
