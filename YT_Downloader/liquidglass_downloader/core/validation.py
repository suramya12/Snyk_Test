"""
URL validation and input sanitization utilities.
"""
from __future__ import annotations
import re
from typing import List
from urllib.parse import urlparse, ParseResult


# Supported video platforms
SUPPORTED_DOMAINS = [
    'youtube.com',
    'youtu.be',
    'vimeo.com',
    'dailymotion.com',
    'facebook.com',
    'twitter.com',
    'x.com',
    'instagram.com',
    'tiktok.com',
    'twitch.tv',
    'reddit.com',
]


class URLValidationError(Exception):
    """Raised when URL validation fails."""
    pass


def is_valid_url(url: str) -> bool:
    """
    Check if a string is a valid URL.

    Args:
        url: The URL string to validate

    Returns:
        True if valid, False otherwise
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()

    # Basic URL pattern check
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )

    return bool(url_pattern.match(url))


def is_supported_platform(url: str) -> bool:
    """
    Check if the URL is from a supported video platform.

    Args:
        url: The URL to check

    Returns:
        True if platform is supported, False otherwise
    """
    try:
        parsed: ParseResult = urlparse(url)
        domain = parsed.netloc.lower()

        # Remove 'www.' prefix if present
        domain = domain.replace('www.', '')

        # Check if any supported domain matches
        return any(supported in domain for supported in SUPPORTED_DOMAINS)
    except Exception:
        return False


def validate_url(url: str, check_platform: bool = True) -> str:
    """
    Validate and sanitize a URL.

    Args:
        url: The URL to validate
        check_platform: Whether to check if platform is supported

    Returns:
        Sanitized URL string

    Raises:
        URLValidationError: If validation fails
    """
    if not url:
        raise URLValidationError("URL cannot be empty")

    # Strip whitespace
    url = url.strip()

    # Check basic URL validity
    if not is_valid_url(url):
        raise URLValidationError(f"Invalid URL format: {url}")

    # Check if platform is supported (optional)
    if check_platform and not is_supported_platform(url):
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        raise URLValidationError(
            f"Unsupported platform: {domain}. "
            f"Supported platforms: {', '.join(SUPPORTED_DOMAINS)}"
        )

    # Additional security checks
    parsed = urlparse(url)

    # Block file:// and other dangerous schemes
    if parsed.scheme not in ['http', 'https']:
        raise URLValidationError(f"Unsupported URL scheme: {parsed.scheme}")

    # Block localhost and private IPs for security
    if 'localhost' in parsed.netloc or parsed.netloc.startswith('127.'):
        raise URLValidationError("Local URLs are not allowed")

    return url


def validate_urls(urls: List[str], check_platform: bool = True) -> tuple[List[str], List[str]]:
    """
    Validate multiple URLs and return valid and invalid lists.

    Args:
        urls: List of URLs to validate
        check_platform: Whether to check if platforms are supported

    Returns:
        Tuple of (valid_urls, error_messages)
    """
    valid_urls: List[str] = []
    errors: List[str] = []

    for url in urls:
        try:
            validated = validate_url(url, check_platform=check_platform)
            valid_urls.append(validated)
        except URLValidationError as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(f"Unexpected error validating {url}: {str(e)}")

    return valid_urls, errors


def extract_urls_from_text(text: str) -> List[str]:
    """
    Extract URLs from a text string.

    Args:
        text: Text containing URLs (one per line or space-separated)

    Returns:
        List of extracted URLs
    """
    if not text:
        return []

    # Split by newlines and spaces
    lines = text.split('\n')
    urls = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Split by spaces in case multiple URLs on one line
        parts = line.split()
        for part in parts:
            part = part.strip()
            if part and is_valid_url(part):
                urls.append(part)

    return urls
