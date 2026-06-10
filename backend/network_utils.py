from __future__ import annotations

import socket
from typing import Callable, TypeVar

import requests
from requests.exceptions import ConnectionError, ProxyError, ReadTimeout, Timeout

T = TypeVar("T")

_YFINANCE_MASKED_PROXY_MARKERS = (
    "nonetype",
    "subscriptable",
)


def build_requests_session(ignore_environment_proxy: bool = False) -> requests.Session:
    session = requests.Session()
    if ignore_environment_proxy:
        session.trust_env = False
        session.proxies.clear()
    return session


def is_proxy_error(error: Exception) -> bool:
    if isinstance(error, ProxyError):
        return True
    message = str(error).lower()
    return "proxyerror" in message or "unable to connect to proxy" in message


def is_masked_proxy_error(error: Exception) -> bool:
    message = str(error).lower()
    return all(marker in message for marker in _YFINANCE_MASKED_PROXY_MARKERS)


def is_retryable_network_error(error: Exception) -> bool:
    if isinstance(error, (Timeout, ReadTimeout, ConnectionError, socket.timeout, TimeoutError)):
        return True
    message = str(error).lower()
    markers = (
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "connection refused",
        "remote end closed connection",
    )
    return any(marker in message for marker in markers)


def run_with_proxy_fallback(
    operation: Callable[[requests.Session | None], T],
    *,
    retry_on_masked_proxy_error: bool = False,
) -> T:
    try:
        return operation(None)
    except Exception as error:
        should_retry_without_proxy = is_proxy_error(error) or (
            retry_on_masked_proxy_error and is_masked_proxy_error(error)
        )
        if not should_retry_without_proxy:
            raise
    session = build_requests_session(ignore_environment_proxy=True)
    return operation(session)
