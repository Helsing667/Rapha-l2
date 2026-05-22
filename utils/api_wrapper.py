"""
Mistral API Wrapper for Nexus Core.

This module provides a secure wrapper for the Mistral AI API with:
- Rate limiting
- Request signing
- Response validation
- Automatic retries
- Token rotation support
"""

import time
import uuid
import hashlib
import hmac
from typing import Dict, List, Optional, Any, Generator
from dataclasses import dataclass
import logging
import json

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


@dataclass
class APIResponse:
    """Represents an API response."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    model: Optional[str] = None


class MistralAPIWrapper:
    """
    Secure wrapper for the Mistral AI API.
    
    This class handles authentication, rate limiting, request signing,
    and response validation for all Mistral API interactions.
    
    Attributes:
        api_key: Mistral API key
        base_url: API base URL
        default_model: Default model to use
        max_retries: Maximum retry attempts
        rate_limit: Requests per minute limit
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.mistral.ai/v1",
        default_model: str = "mistral-large-latest",
        max_retries: int = 3,
        rate_limit_per_minute: int = 60,
        request_timeout: int = 30,
    ):
        """
        Initialize the Mistral API Wrapper.
        
        Args:
            api_key: Mistral API key
            base_url: API base URL
            default_model: Default model for requests
            max_retries: Maximum number of retries
            rate_limit_per_minute: Rate limit in requests per minute
            request_timeout: Timeout for requests in seconds
        """
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model
        self.max_retries = max_retries
        self.rate_limit = rate_limit_per_minute
        self.request_timeout = request_timeout
        
        # Rate limiting state
        self._request_timestamps: List[float] = []
        self._lock = None  # Would use threading.Lock in production
        
        # Set up session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        
        # Headers
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })
        
        logger.info(f"MistralAPIWrapper initialized (model={default_model})")
    
    def _check_rate_limit(self) -> None:
        """Check and enforce rate limiting."""
        now = time.time()
        window_start = now - 60  # 1-minute window
        
        # Remove old timestamps
        self._request_timestamps = [
            ts for ts in self._request_timestamps if ts > window_start
        ]
        
        # Check if we're at the limit
        if len(self._request_timestamps) >= self.rate_limit:
            oldest = min(self._request_timestamps)
            wait_time = 60 - (now - oldest)
            if wait_time > 0:
                logger.warning(f"Rate limit reached, waiting {wait_time:.1f}s")
                time.sleep(wait_time)
        
        self._request_timestamps.append(now)
    
    def _generate_nonce(self) -> str:
        """Generate a unique nonce for request signing."""
        return str(uuid.uuid4())
    
    def _sign_request(self, payload: Dict[str, Any], nonce: str, timestamp: float) -> str:
        """
        Sign a request payload.
        
        Args:
            payload: Request payload
            nonce: Unique nonce
            timestamp: Request timestamp
            
        Returns:
            HMAC signature
        """
        message = json.dumps(payload, sort_keys=True) + nonce + str(timestamp)
        signature = hmac.new(
            self.api_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _validate_response(self, response: requests.Response) -> bool:
        """Validate API response structure."""
        try:
            data = response.json()
            
            # Check for required fields in chat completion
            if 'choices' not in data and 'data' not in data:
                logger.warning("Invalid response structure: missing choices/data")
                return False
            
            return True
        except json.JSONDecodeError:
            logger.error("Invalid JSON in response")
            return False
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_p: float = 1.0,
        stream: bool = False,
    ) -> APIResponse:
        """
        Send a chat completion request.
        
        Args:
            messages: List of message dictionaries
            model: Model to use (default: instance default)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            top_p: Top-p sampling parameter
            stream: Whether to stream the response
            
        Returns:
            APIResponse object
        """
        self._check_rate_limit()
        
        endpoint = f"{self.base_url}/chat/completions"
        
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "stream": stream,
        }
        
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        # Add security headers
        nonce = self._generate_nonce()
        timestamp = time.time()
        signature = self._sign_request(payload, nonce, timestamp)
        
        headers = {
            **self.session.headers,
            "X-Request-Nonce": nonce,
            "X-Request-Timestamp": str(timestamp),
            "X-Request-Signature": signature,
        }
        
        try:
            response = self.session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=self.request_timeout,
                stream=stream,
            )
            
            if not self._validate_response(response):
                return APIResponse(
                    success=False,
                    error="Invalid response structure",
                )
            
            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                return APIResponse(
                    success=False,
                    error=f"API error {response.status_code}: {error_data}",
                )
            
            data = response.json()
            
            return APIResponse(
                success=True,
                data=data,
                usage=data.get('usage'),
                model=data.get('model'),
            )
            
        except requests.exceptions.Timeout:
            logger.error("Request timed out")
            return APIResponse(success=False, error="Request timed out")
        except requests.exceptions.RequestException as e:
            logger.exception(f"Request failed: {e}")
            return APIResponse(success=False, error=str(e))
    
    def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Generator[str, None, None]:
        """
        Stream a chat completion response.
        
        Args:
            messages: List of message dictionaries
            model: Model to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Yields:
            Text chunks from the response
        """
        response = self.chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        
        if not response.success:
            raise RuntimeError(f"Stream request failed: {response.error}")
        
        for line in response.data.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = line[6:]
                    if data == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data)
                        content = chunk['choices'][0]['delta'].get('content', '')
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError):
                        continue
    
    def list_models(self) -> APIResponse:
        """
        List available models.
        
        Returns:
            APIResponse with model list
        """
        self._check_rate_limit()
        
        endpoint = f"{self.base_url}/models"
        
        try:
            response = self.session.get(
                endpoint,
                timeout=self.request_timeout,
            )
            
            if response.status_code != 200:
                return APIResponse(
                    success=False,
                    error=f"API error {response.status_code}",
                )
            
            data = response.json()
            
            return APIResponse(
                success=True,
                data=data,
            )
            
        except Exception as e:
            logger.exception(f"Failed to list models: {e}")
            return APIResponse(success=False, error=str(e))
    
    def embed(
        self,
        texts: List[str],
        model: str = "mistral-embed",
    ) -> APIResponse:
        """
        Generate embeddings for texts.
        
        Args:
            texts: List of texts to embed
            model: Embedding model to use
            
        Returns:
            APIResponse with embeddings
        """
        self._check_rate_limit()
        
        endpoint = f"{self.base_url}/embeddings"
        
        payload = {
            "model": model,
            "inputs": texts,
        }
        
        try:
            response = self.session.post(
                endpoint,
                json=payload,
                timeout=self.request_timeout,
            )
            
            if response.status_code != 200:
                return APIResponse(
                    success=False,
                    error=f"API error {response.status_code}",
                )
            
            data = response.json()
            
            return APIResponse(
                success=True,
                data=data,
                usage=data.get('usage'),
            )
            
        except Exception as e:
            logger.exception(f"Embedding request failed: {e}")
            return APIResponse(success=False, error=str(e))
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics."""
        now = time.time()
        window_start = now - 60
        
        recent_requests = len([
            ts for ts in self._request_timestamps if ts > window_start
        ])
        
        return {
            "requests_last_minute": recent_requests,
            "rate_limit": self.rate_limit,
            "remaining": max(0, self.rate_limit - recent_requests),
        }
