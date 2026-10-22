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


def _positive_duration(value: object, name: str) -> int | float:
    message = f"{name} must be a positive number of seconds"
    if value is None:
        raise ValueError(message)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(message)
    if value <= 0:
        raise ValueError(message)
    return value


def _positive_seconds(value: object) -> None:
    if value is None:
        raise ValueError(_TIMEOUT_ERROR)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(_TIMEOUT_ERROR)
    if value <= 0:
        raise ValueError(_TIMEOUT_ERROR)


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


def _retry_after(response: requests.Response) -> int | float | None:
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        seconds = float(header)
    except ValueError:
        return None
    if seconds.is_integer():
        return int(seconds)
    return seconds


def _retry_after_header(exc: MailTMError) -> int | float | None:
    """Numeric Retry-After on 429 or 503. Anything else, including an HTTP date, is ignored."""
    cause = exc.__cause__
    response = getattr(cause, "response", None)
    if not isinstance(response, requests.Response):
        return None
    if response.status_code not in (429, 503):
        return None
    return _retry_after(response)


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
    status_code = response.status_code
    body = _response_body(response)
    message = f"Mail.tm returned {status_code}"
    if status_code == 401:
        return MailTMAuthError(message, status_code=status_code, body=body)
    if status_code == 429:
        return MailTMRateLimitError(
            message,
            status_code=status_code,
            body=body,
            retry_after=_retry_after(response),
        )
    if status_code >= 500:
        return MailTMServerError(message, status_code=status_code, body=body)
    return MailTMAPIError(message, status_code=status_code, body=body)


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

    def _backoff_delay(self, retry_number: int) -> float:
        policy = self._retry
        computed = min(policy.max_delay, policy.base_delay * 2 ** (retry_number - 1))
        return computed + computed * _JITTER_SHARE * _timing.jitter_fraction()

    def _exchange(
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

    def _pause(self, retry_number: int, exc: MailTMError) -> float:
        override = _retry_after_header(exc)
        if override is None:
            return self._backoff_delay(retry_number)
        if override > self._retry.max_delay:
            if isinstance(exc, MailTMRateLimitError):
                raise exc
            if isinstance(exc, MailTMServerError):
                raise MailTMRateLimitError(
                    str(exc),
                    status_code=exc.status_code,
                    body=exc.body,
                    retry_after=override,
                ) from exc.__cause__
            raise exc
        return override

    def _send(
        self,
        method: str,
        path: str,
        *,
        retryable: tuple[type[MailTMError], ...] = _RETRYABLE,
        **kwargs: object,
    ) -> requests.Response:
        timeout = self._effective_timeout(kwargs.pop("timeout", None))
        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                return self._exchange(method, path, timeout, **kwargs)
            except retryable as exc:
                if attempt >= self._retry.max_attempts:
                    raise
                _timing.sleep(self._pause(attempt, exc))

    def _read_json(self, method: str, path: str, **kwargs: object) -> dict[str, object]:
        response = self._send(method, path, **kwargs)
        return _json_object(response, f"{method} {path}")

    def get_domain(self, *, timeout: _Timeout | None = None) -> str:
        """Fetch the first active, public domain from the first page."""
        payload = self._read_json("GET", "/domains", timeout=timeout)
        domains = require_member_list(payload)
        for domain_item in domains:
            if not isinstance(domain_item, dict) or not _is_active_public_domain(domain_item):
                continue
            require_keys(domain_item, ("domain",), body=payload)
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
            json={"address": email_address, "password": password},
            timeout=timeout,
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
            json={"address": email_address, "password": password},
            timeout=timeout,
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
            payload = self._read_json(
                "GET", "/messages", params={"page": page}, timeout=timeout
            )
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
        payload = self._read_json("GET", f"/messages/{message_id}", timeout=timeout)
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
            self.get_domain(timeout=timeout)
        
        local_part = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10))
        email = f"{local_part}@{self.domain}"
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        return email, password
