"""
Rate limiting utilities for USGS Water Services API.

This module provides rate limiting and retry logic to help prevent exceeding
USGS API rate limits and handle 429 "Too Many Requests" errors gracefully.

USGS API Rate Limits:
    - Without API key: Lower limits (not publicly documented)
    - With free API key: ~1,000 requests per hour
    - Recommended sustained rate: 5-10 requests per second
    - Burst rate: Up to 40-50 requests per second (not sustained)

Classes:
    UsgsRateLimiter: Token bucket rate limiter for API requests

Functions:
    retry_with_backoff: Decorator for exponential backoff on API errors
    configure_api_key: Helper to set USGS API key
    check_api_key: Check if API key is configured

Example Usage:
    >>> from ras_commander.usgs.rate_limiter import UsgsRateLimiter, configure_api_key
    >>>
    >>> # Configure API key (increases rate limits)
    >>> configure_api_key("your_key_here")
    >>>
    >>> # Create rate limiter (5 requests/sec sustained, bursts to 40)
    >>> limiter = UsgsRateLimiter(requests_per_second=5, burst_size=40)
    >>>
    >>> # Make rate-limited API calls
    >>> for site_id in site_ids:
    ...     limiter.wait_if_needed()
    ...     data = retrieve_flow_data(site_id, ...)
    >>>
    >>> # Or use as context manager
    >>> with limiter:
    ...     data = retrieve_flow_data(site_id, ...)

References:
    - USGS API Keys: https://api.waterdata.usgs.gov/signup/
    - API Documentation: https://api.waterdata.usgs.gov/docs/
    - Efficiency Guide: https://api.waterdata.usgs.gov/docs/ogcapi/efficiency/
"""

import time
import os
from functools import wraps
from typing import Optional, Callable, Any
import logging

logger = logging.getLogger(__name__)


class UsgsRateLimiter:
    """
    Token bucket rate limiter for USGS API requests.

    Implements a token bucket algorithm that allows burst traffic while
    maintaining a sustainable average request rate. Compatible with USGS
    recommended rates of 5-10 req/sec sustained, up to 40-50 req/sec burst.

    Attributes:
        requests_per_second (float): Sustained request rate (tokens per second)
        burst_size (int): Maximum burst capacity (bucket size)
        tokens (float): Current token count
        last_update (float): Last token refill timestamp

    Parameters:
        requests_per_second (float): Target sustained rate (default: 5.0)
            - 5.0 = conservative (recommended for batch processing)
            - 10.0 = moderate (recommended for interactive use)
        burst_size (int): Maximum burst tokens (default: 40)
            - Allows short bursts while maintaining average rate
            - USGS allows up to 40-50 req/sec bursts

    Example:
        >>> # Conservative rate limiting (5 req/sec)
        >>> limiter = UsgsRateLimiter(requests_per_second=5.0, burst_size=40)
        >>>
        >>> # Process 100 gauges with rate limiting
        >>> for i, site_id in enumerate(site_ids):
        ...     limiter.wait_if_needed()  # Blocks if rate exceeded
        ...     data = retrieve_flow_data(site_id, start, end)
        ...     print(f"Processed {i+1}/{len(site_ids)}: {limiter.tokens:.1f} tokens")
        >>>
        >>> # Context manager automatically waits
        >>> for site_id in site_ids:
        ...     with limiter:
        ...         data = retrieve_flow_data(site_id, start, end)

    Notes:
        - Thread-safe for single-threaded applications
        - For multi-threaded use, consider adding thread locks
        - Tokens refill continuously based on requests_per_second
        - Burst capacity allows temporary rate spikes
    """

    def __init__(
        self,
        requests_per_second: float = 5.0,
        burst_size: int = 40
    ):
        """Initialize rate limiter with token bucket parameters."""
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size
        self.tokens = float(burst_size)  # Start with full bucket
        self.last_update = time.time()

        logger.debug(f"Initialized UsgsRateLimiter: {requests_per_second} req/sec, "
                    f"burst={burst_size}")

    def _refill_tokens(self):
        """Refill tokens based on elapsed time since last update."""
        now = time.time()
        elapsed = now - self.last_update

        # Add tokens based on time elapsed and rate
        tokens_to_add = elapsed * self.requests_per_second
        self.tokens = min(self.burst_size, self.tokens + tokens_to_add)
        self.last_update = now

        logger.debug(f"Refilled tokens: {self.tokens:.2f}/{self.burst_size}")

    def wait_if_needed(self):
        """
        Wait if necessary to stay within rate limit.

        Blocks execution until at least one token is available.
        Consumes one token from the bucket.

        Returns:
            None

        Example:
            >>> limiter = UsgsRateLimiter(requests_per_second=5)
            >>> for site_id in many_sites:
            ...     limiter.wait_if_needed()  # Automatically throttles
            ...     data = api_call(site_id)
        """
        self._refill_tokens()

        # If no tokens available, wait until we have at least one
        if self.tokens < 1.0:
            wait_time = (1.0 - self.tokens) / self.requests_per_second
            logger.debug(f"Rate limit: waiting {wait_time:.2f}s for token")
            time.sleep(wait_time)
            self._refill_tokens()

        # Consume one token
        self.tokens -= 1.0

    def __enter__(self):
        """Context manager entry - waits if needed."""
        self.wait_if_needed()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - no action needed."""
        return False  # Don't suppress exceptions


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None
):
    """
    Decorator for exponential backoff retry logic on API errors.

    Automatically retries failed API calls with progressively longer delays.
    Particularly useful for handling HTTP 429 "Too Many Requests" errors.

    Parameters:
        max_retries (int): Maximum number of retry attempts (default: 3)
        initial_delay (float): First retry delay in seconds (default: 1.0)
        backoff_factor (float): Delay multiplier for each retry (default: 2.0)
            - Delays: 1s, 2s, 4s with default settings
        exceptions (tuple): Exception types to catch (default: all Exceptions)
        on_retry (Callable): Optional callback(retry_num, exception) on each retry

    Returns:
        Decorated function that retries on failure

    Example:
        >>> @retry_with_backoff(max_retries=3, initial_delay=1.0)
        ... def fetch_gauge_data(site_id):
        ...     return retrieve_flow_data(site_id, start, end)
        >>>
        >>> # Automatically retries up to 3 times on failure
        >>> data = fetch_gauge_data("01646500")

    Example with custom exception handling:
        >>> def log_retry(attempt, error):
        ...     print(f"Retry {attempt}: {error}")
        >>>
        >>> @retry_with_backoff(
        ...     max_retries=5,
        ...     exceptions=(requests.exceptions.HTTPError,),
        ...     on_retry=log_retry
        ... )
        ... def api_call(site_id):
        ...     return retrieve_flow_data(site_id, start, end)

    Notes:
        - Logs each retry attempt at DEBUG level
        - Final exception is re-raised after max_retries
        - Useful for transient errors (429, 503, network timeouts)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except exceptions as e:
                    last_exception = e

                    # If this was the last attempt, raise the exception
                    if attempt == max_retries:
                        logger.error(f"Max retries ({max_retries}) exceeded for {func.__name__}")
                        raise

                    # Log retry
                    logger.debug(f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                                f"after error: {e}")

                    # Call optional retry callback
                    if on_retry:
                        on_retry(attempt + 1, e)

                    # Wait before retrying
                    time.sleep(delay)
                    delay *= backoff_factor

            # Should never reach here, but just in case
            raise last_exception

        return wrapper
    return decorator


def configure_api_key(api_key: str):
    """
    Configure USGS API key for higher rate limits.

    Sets the API_USGS_PAT environment variable recognized by the
    dataretrieval package. Using an API key increases rate limits
    from low unauthenticated limits to ~1,000 requests per hour.

    Parameters:
        api_key (str): USGS API key from https://api.waterdata.usgs.gov/signup/

    Returns:
        None

    Example:
        >>> from ras_commander.usgs import configure_api_key
        >>> configure_api_key("your_api_key_here")
        >>> # Now all USGS API calls will use higher rate limits

    Notes:
        - Register for free at: https://api.waterdata.usgs.gov/signup/
        - Key is automatically used by dataretrieval package
        - Persists for current Python session only
        - For permanent config, add to ~/.bashrc or system environment

    See Also:
        - check_api_key: Check if API key is configured
        - Using API Keys: https://api.waterdata.usgs.gov/docs/ogcapi/keys/
    """
    os.environ["API_USGS_PAT"] = api_key
    logger.info("USGS API key configured (rate limits increased)")


def check_api_key() -> bool:
    """
    Check if USGS API key is configured.

    Returns:
        bool: True if API_USGS_PAT environment variable is set

    Example:
        >>> from ras_commander.usgs import check_api_key, configure_api_key
        >>>
        >>> if not check_api_key():
        ...     print("Warning: No API key configured. Rate limits are lower.")
        ...     print("Register at: https://api.waterdata.usgs.gov/signup/")
        ...     # configure_api_key("your_key_here")  # Optional

    Notes:
        - API key increases rate limits to ~1,000 requests/hour
        - Without key, rate limits are lower (exact limit not documented)
        - Key registration is free and instant
    """
    has_key = "API_USGS_PAT" in os.environ

    if has_key:
        logger.debug("USGS API key found in environment")
    else:
        logger.debug("No USGS API key found (lower rate limits apply)")

    return has_key


def get_rate_limit_info() -> dict:
    """
    Get information about USGS API rate limits and current configuration.

    Returns:
        dict: Rate limit information with keys:
            - has_api_key (bool): Whether API key is configured
            - recommended_sustained_rate (str): Recommended sustained rate
            - recommended_burst_rate (str): Recommended burst rate
            - estimated_hourly_limit (str): Estimated requests per hour
            - signup_url (str): URL to register for API key

    Example:
        >>> from ras_commander.usgs.rate_limiter import get_rate_limit_info
        >>> info = get_rate_limit_info()
        >>> print(f"API key configured: {info['has_api_key']}")
        >>> print(f"Recommended rate: {info['recommended_sustained_rate']}")
        >>> if not info['has_api_key']:
        ...     print(f"Register at: {info['signup_url']}")
    """
    return {
        'has_api_key': check_api_key(),
        'recommended_sustained_rate': '5-10 requests/sec',
        'recommended_burst_rate': '40-50 requests/sec (not sustained)',
        'estimated_hourly_limit': '~1,000 req/hr with API key, lower without',
        'signup_url': 'https://api.waterdata.usgs.gov/signup/',
        'documentation': 'https://api.waterdata.usgs.gov/docs/ogcapi/keys/'
    }
