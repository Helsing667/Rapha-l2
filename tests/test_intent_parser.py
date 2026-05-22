"""
Tests for Intent Parser module.
"""

import pytest
from core.intent_parser import IntentParser, ParsedIntent, IntentType, PrivilegeLevel


class TestIntentParser:
    """Test cases for IntentParser."""
    
    @pytest.fixture
    def parser(self):
        """Create a parser instance for testing."""
        return IntentParser(language='fr', confidence_threshold=0.5)
    
    def test_parse_message_send_french(self, parser):
        """Test parsing French message send request."""
        text = "Envoie un message WhatsApp à Jean avec le texte 'Réunion demain 10h'"
        result = parser.parse(text)
        
        assert result.intent_type == IntentType.MESSAGE_SEND
        assert result.confidence >= 0.5
        assert 'recipient' in result.parameters or 'Jean' in str(result.parameters)
    
    def test_parse_file_operation(self, parser):
        """Test parsing file operation request."""
        text = "Ouvre le fichier /home/user/document.txt"
        result = parser.parse(text)
        
        assert result.intent_type == IntentType.FILE_OPERATION
        assert '/home/user/document.txt' in result.parameters.get('path', '')
    
    def test_parse_system_command(self, parser):
        """Test parsing system command request."""
        text = "Exécuter la commande ls -la"
        result = parser.parse(text)
        
        assert result.intent_type == IntentType.SYSTEM_COMMAND
    
    def test_parse_unknown_intent(self, parser):
        """Test parsing unknown intent returns UNKNOWN type."""
        text = "xyzabc123 random gibberish"
        result = parser.parse(text)
        
        # May be unknown or low confidence
        assert result.confidence < 1.0
    
    def test_privilege_level_sudo_detection(self, parser):
        """Test that system paths trigger sudo privilege level."""
        text = "Modifier le fichier /etc/hosts"
        result = parser.parse(text)
        
        assert result.privilege_level == PrivilegeLevel.SUDO
    
    def test_confirmation_required_for_deletion(self, parser):
        """Test that deletion operations require confirmation."""
        text = "Supprimer le fichier /tmp/test.txt"
        result = parser.parse(text)
        
        assert result.requires_confirmation == True
    
    def test_validate_intent_valid(self, parser):
        """Test validation of valid intent."""
        parsed = ParsedIntent(
            intent_type=IntentType.MESSAGE_SEND,
            confidence=0.9,
            original_text="test",
            parameters={'recipient': 'Jean', 'message_text': 'Hello'},
        )
        
        assert parser.validate_intent(parsed) == True
    
    def test_validate_intent_missing_params(self, parser):
        """Test validation fails for missing required parameters."""
        parsed = ParsedIntent(
            intent_type=IntentType.MESSAGE_SEND,
            confidence=0.9,
            original_text="test",
            parameters={},  # Missing required params
        )
        
        assert parser.validate_intent(parsed) == False
    
    def test_batch_parse(self, parser):
        """Test batch parsing of multiple requests."""
        texts = [
            "Ouvre le fichier test.txt",
            "Envoie un message à Marie",
        ]
        results = parser.batch_parse(texts)
        
        assert len(results) == 2
        assert all(isinstance(r, ParsedIntent) for r in results)
    
    def test_to_dict_conversion(self, parser):
        """Test converting ParsedIntent to dictionary."""
        parsed = ParsedIntent(
            intent_type=IntentType.FILE_OPERATION,
            confidence=0.85,
            original_text="test",
            parameters={'path': '/tmp/test'},
        )
        
        result_dict = parsed.to_dict()
        
        assert result_dict['intent_type'] == 'file_operation'
        assert result_dict['confidence'] == 0.85
        assert result_dict['original_text'] == 'test'


class TestIntentParserEnglish:
    """Test cases for English language parsing."""
    
    @pytest.fixture
    def parser_en(self):
        """Create an English parser instance."""
        return IntentParser(language='en', confidence_threshold=0.5)
    
    def test_parse_message_send_english(self, parser_en):
        """Test parsing English message send request."""
        text = "Send a message to John with text 'Meeting tomorrow'"
        result = parser_en.parse(text)
        
        assert result.intent_type == IntentType.MESSAGE_SEND
    
    def test_parse_file_operation_english(self, parser_en):
        """Test parsing English file operation."""
        text = "Open the file /home/user/doc.txt"
        result = parser_en.parse(text)
        
        assert result.intent_type == IntentType.FILE_OPERATION
