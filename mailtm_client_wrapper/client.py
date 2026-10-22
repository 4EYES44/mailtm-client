import math
import secrets
import string
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import cast

import requests
import urllib3.exceptions

from . import _timing
from .exceptions import (
    MailTMAPIError,
    MailTMAuthError,
    MailTMConnectionError,
    MailTMError,
    MailTMNotAuthenticatedError,
    MailTMRateLimitError,
    MailTMResponseError,
    MailTMServerError,
    MailTMTimeoutError,
    MailTMWaitTimeoutError,
)
from .models import Message, MessageSummary
from .validation import (
    MESSAGE_DETAIL_KEYS,
    MESSAGE_SUMMARY_KEYS,
    require_keys,
    require_member_list,
)


type _Timeout = int | float | tuple[int | float, int | float]

_TIMEOUT_ERROR = "timeout must be a positive number of seconds or a (connect, read) pair"
_JITTER_SHARE = 0.25
_RETRYABLE = (
    MailTMRateLimitError,
    MailTMServerError,
    MailTMTimeoutError,
    MailTMConnectionError,
)


@dataclass(frozen=True)
class RetryPolicy:
    """How many times a call is attempted, and how long to wait between tries."""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 8.0

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise TypeError("max_attempts must be an integer greater than or equal to 1")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be an integer greater than or equal to 1")
        for name in ("base_delay", "max_delay"):
            _require_positive_finite(
                getattr(self, name),
                f"{name} must be a positive finite number of seconds",
            )
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be greater than or equal to base_delay")

    def _backoff_delay(self, retry_number: int, jitter_fraction: float) -> float:
        computed = min(self.max_delay, self.base_delay * 2 ** (retry_number - 1))
        return computed + computed * _JITTER_SHARE * jitter_fraction


def _require_positive_finite(number: object, message: str) -> int | float:
    """Reject a bool, a non-number, or a number that is not positive and finite.

    ``None`` is not handled here. Callers that must report ``None`` as
    ``ValueError`` check it first; other callers get ``TypeError``.
    """
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        raise TypeError(message)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(message)
    return number


def _positive_duration(value: object, name: str) -> int | float:
    message = f"{name} must be a positive number of seconds"
    if value is None:
        raise ValueError(message)
    return _require_positive_finite(value, message)


def _positive_seconds(value: object) -> None:
    if value is None:
        raise ValueError(_TIMEOUT_ERROR)
    _require_positive_finite(value, _TIMEOUT_ERROR)


def _checked_timeout(timeout: object) -> _Timeout:
    if isinstance(timeout, tuple):
        if len(timeout) != 2:
            raise TypeError(_TIMEOUT_ERROR)
        for part in timeout:
            _positive_seconds(part)
        return timeout
    _positive_seconds(timeout)
    assert isinstance(timeout, (int, float))
    return timeout


def _response_body(response: requests.Response) -> object:
    if response.text == "":
        return ""
    try:
        return response.json()
    except requests.JSONDecodeError:
        return response.text


# Only these statuses carry a Retry-After the client will honor.
_RETRY_AFTER_STATUSES = frozenset({429, 503})


def _parse_retry_after(response: requests.Response) -> int | float | None:
    """A positive finite Retry-After in seconds, or None when the header is not usable."""
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        seconds = float(header)
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    if seconds.is_integer():
        return int(seconds)
    return seconds


def _is_read_timeout(exc: BaseException) -> bool:
    """True when a requests error is a read timeout reported as a connection error.

    requests raises ``ConnectionError`` for a timeout while the body is read, and
    the urllib3 ``ReadTimeoutError`` sits on the cause, the context, or the args.
    """
    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        if isinstance(current, urllib3.exceptions.ReadTimeoutError):
            return True
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None and not current.__suppress_context__:
            pending.append(current.__context__)
        for arg in current.args:
            if isinstance(arg, BaseException):
                pending.append(arg)
    return False


def _error_for_other_request(exc: requests.RequestException, operation: str) -> MailTMError:
    """Wrap a requests failure that is neither a timeout nor a dropped connection.

    A body cut off mid-transfer is a connection error, so it is retried. A body
    that cannot be decoded is a response error. A bad URL, a redirect loop and
    every other request failure stay on the root error and are not retried.
    """
    if isinstance(exc, requests.exceptions.ChunkedEncodingError):
        return MailTMConnectionError(f"{operation} could not connect")
    if isinstance(exc, requests.exceptions.ContentDecodingError):
        return MailTMResponseError(
            f"{operation} returned a body that could not be decoded"
        )
    return MailTMError(f"{operation} could not be completed")


def _error_for_status(response: requests.Response) -> MailTMAPIError:
    """Map one HTTP status to its library error, parsing Retry-After once."""
    status_code = response.status_code
    body = _response_body(response)
    message = f"Mail.tm returned {status_code}"
    retry_after = (
        _parse_retry_after(response) if status_code in _RETRY_AFTER_STATUSES else None
    )
    if status_code == 401:
        error: MailTMAPIError = MailTMAuthError(message, status_code=status_code, body=body)
    elif status_code == 429:
        error = MailTMRateLimitError(
            message,
            status_code=status_code,
            body=body,
            retry_after=retry_after,
        )
    elif status_code >= 500:
        error = MailTMServerError(message, status_code=status_code, body=body)
    else:
        error = MailTMAPIError(message, status_code=status_code, body=body)
    # Private copy so the retry loop does not read the requests response again.
    setattr(error, "_retry_after", retry_after)
    return error


def _is_active_public_domain(domain_item: dict[str, object]) -> bool:
    return domain_item.get("isActive") is True and domain_item.get("isPrivate") is False


def _reported_inbox_total(payload: dict[str, object]) -> int | None:
    """hydra:totalItems when it is a non-negative integer. Booleans and other JSON are not."""
    total = payload.get("hydra:totalItems")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        return None
    return total


def _json_object(response: requests.Response, operation: str) -> dict[str, object]:
    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        raise MailTMResponseError(
            f"{operation} returned a body that is not valid JSON",
            status_code=response.status_code,
            body=response.text,
        ) from exc
    if not isinstance(payload, dict):
        raise MailTMResponseError(
            f"{operation} returned a body that is not a JSON object",
            status_code=response.status_code,
            body=payload,
        )
    return payload


class MailTMClient:
    """
    A robust API wrapper for https://docs.mail.tm/ 
    Handles domain fetching, account creation, authentication, and message retrieval.
    """
    def __init__(
        self,
        base_url: str = "https://api.mail.tm",
        *,
        timeout: _Timeout = 10.0,
        retry: RetryPolicy | None = None,
    ):
        self.base_url = base_url
        self._timeout = _checked_timeout(timeout)
        self._retry = retry if retry is not None else RetryPolicy()
        self.session = requests.Session()
        self.token: str | None = None
        self.domain: str | None = None
        self.email_address: str | None = None
        self.password: str | None = None

    def _effective_timeout(self, timeout: object) -> _Timeout:
        if timeout is None:
            return self._timeout
        return _checked_timeout(timeout)

    def _request_once(
        self,
        method: str,
        path: str,
        timeout: _Timeout,
        **kwargs: object,
    ) -> requests.Response:
        operation = f"{method} {path}"
        try:
            response = self.session.request(
                method, f"{self.base_url}{path}", timeout=timeout, **kwargs
            )
        except requests.Timeout as exc:
            # ConnectTimeout subclasses ConnectionError, so it has to be handled first.
            raise MailTMTimeoutError(f"{operation} timed out (timeout={timeout})") from exc
        except requests.ConnectionError as exc:
            if _is_read_timeout(exc):
                raise MailTMTimeoutError(
                    f"{operation} timed out (timeout={timeout})"
                ) from exc
            raise MailTMConnectionError(f"{operation} could not connect") from exc
        except requests.RequestException as exc:
            raise _error_for_other_request(exc, operation) from exc
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise _error_for_status(response) from exc
        return response

    def _retry_delay(self, retry_number: int, exc: MailTMError) -> float:
        override = getattr(exc, "_retry_after", None)
        if not isinstance(override, (int, float)) or isinstance(override, bool):
            return self._retry._backoff_delay(retry_number, _timing.jitter_fraction())
        if override > self._retry.max_delay:
            # Sleeping the header would exceed max_delay. The original error
            # already has the right class, so a 503 is not turned into a 429.
            raise exc
        return override

    def _request_with_retries(
        self,
        method: str,
        path: str,
        timeout: _Timeout,
        *,
        retryable: tuple[type[MailTMError], ...] = _RETRYABLE,
        **kwargs: object,
    ) -> requests.Response:
        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                return self._request_once(method, path, timeout, **kwargs)
            except retryable as exc:
                # Consult Retry-After before giving up, so a value past the cap
                # raises on the last attempt the same way it does on an earlier one.
                delay = self._retry_delay(attempt, exc)
                if attempt >= self._retry.max_attempts:
                    raise
                _timing.sleep(delay)

    def _read_json(
        self,
        method: str,
        path: str,
        timeout: _Timeout,
        *,
        retryable: tuple[type[MailTMError], ...] = _RETRYABLE,
        **kwargs: object,
    ) -> dict[str, object]:
        response = self._request_with_retries(
            method, path, timeout, retryable=retryable, **kwargs
        )
        return _json_object(response, f"{method} {path}")

    def get_domain(self, *, timeout: _Timeout | None = None) -> str:
        """Fetch the first active, public domain from the first page."""
        return self._load_domain(self._effective_timeout(timeout))

    def _load_domain(self, timeout: _Timeout) -> str:
        payload = self._read_json("GET", "/domains", timeout)
        domains = require_member_list(payload)
        for domain_item in domains:
            require_keys(domain_item, ("domain",), body=payload)
        for domain_item in domains:
            assert isinstance(domain_item, dict)
            if not _is_active_public_domain(domain_item):
                continue
            domain = domain_item["domain"]
            self.domain = domain
            return domain
        raise MailTMResponseError("No available domains found.", body=payload)

    def create_account(
        self,
        email_address: str,
        password: str,
        *,
        timeout: _Timeout | None = None,
    ) -> bool:
        """Create a new disposable account."""
        # A later timeout or 5xx can mean the account already exists, so only 429 is retried.
        self._read_json(
            "POST",
            "/accounts",
            self._effective_timeout(timeout),
            json={"address": email_address, "password": password},
            retryable=(MailTMRateLimitError,),
        )
        return True

    def login(
        self,
        email_address: str,
        password: str,
        *,
        timeout: _Timeout | None = None,
    ) -> str:
        """Login and return the JWT token."""
        payload = self._read_json(
            "POST",
            "/token",
            self._effective_timeout(timeout),
            json={"address": email_address, "password": password},
        )
        require_keys(payload, ("token",))
        token = payload["token"]
        self.token = token
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        return token

    def read_inbox(self, *, timeout: _Timeout | None = None) -> list[MessageSummary]:
        """Fetch every message in the inbox, across all pages."""
        timeout = self._effective_timeout(timeout)
        self._require_login()
        return self._read_inbox_pages(timeout)

    def _read_inbox_pages(self, timeout: _Timeout) -> list[MessageSummary]:
        collected: list[MessageSummary] = []
        seen_ids: set[object] = set()
        page = 1
        while True:
            payload = self._read_json("GET", "/messages", timeout, params={"page": page})
            messages = require_member_list(payload)
            if not messages:
                break
            new_ids = 0
            for message in messages:
                require_keys(message, MESSAGE_SUMMARY_KEYS, body=payload)
                summary = cast(MessageSummary, message)
                if summary["id"] in seen_ids:
                    continue
                seen_ids.add(summary["id"])
                collected.append(summary)
                new_ids += 1
            if new_ids == 0:
                break
            total = _reported_inbox_total(payload)
            if total is not None and len(collected) >= total:
                break
            page += 1
        return collected

    def read_message(
        self,
        message_id: str,
        *,
        timeout: _Timeout | None = None,
    ) -> Message:
        """Fetch the full content of a specific message."""
        timeout = self._effective_timeout(timeout)
        self._require_login()
        payload = self._read_json("GET", f"/messages/{message_id}", timeout)
        require_keys(payload, MESSAGE_DETAIL_KEYS)
        return payload

    def wait_for_message(
        self,
        predicate: Callable[[MessageSummary], object] | None = None,
        *,
        timeout: int | float = 60.0,
        poll_interval: int | float = 3.0,
        exclude_ids: Collection[str] = (),
    ) -> Message:
        """Poll the inbox until a matching message arrives and return it in full.

        ``predicate`` receives each inbox summary (``from``, ``subject``,
        ``intro``). ``None`` accepts any message that is not listed in
        ``exclude_ids``. Messages already in the inbox are candidates. The
        first poll is immediate. Between polls the wait sleeps the smaller of
        ``poll_interval`` and the time remaining, then polls once more at the
        deadline. If nothing matched, this raises ``MailTMWaitTimeoutError``
        with ``timeout`` set to the wait timeout.

        The deadline is checked only between polls. Each poll keeps its own
        request timeout and retries, which are not shortened to the time left.
        During an outage the wait can therefore run past its deadline by up to
        one call's worst case (three attempts of the request timeout plus the
        retry sleeps; about 33 seconds with the defaults).
        """
        timeout = _positive_duration(timeout, "timeout")
        poll_interval = _positive_duration(poll_interval, "poll_interval")
        self._require_login()
        excluded = set(exclude_ids)
        deadline = _timing.monotonic() + timeout
        while True:
            for summary in self.read_inbox():
                if summary["id"] in excluded:
                    continue
                if predicate is not None and not predicate(summary):
                    continue
                return self.read_message(summary["id"])
            remaining = deadline - _timing.monotonic()
            if remaining <= 0:
                raise MailTMWaitTimeoutError(
                    f"No matching message arrived within {timeout} seconds",
                    timeout=timeout,
                )
            _timing.sleep(min(poll_interval, remaining))

    def _require_login(self) -> None:
        if not self.token:
            raise MailTMNotAuthenticatedError("Not authenticated. Call login() first.")

    def generate_random_credentials(self, *, timeout: _Timeout | None = None) -> tuple[str, str]:
        """Helper to generate a random email and password."""
        timeout = self._effective_timeout(timeout)
        if not self.domain:
            self._load_domain(timeout)
        
        local_part = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10))
        email = f"{local_part}@{self.domain}"
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        return email, password
