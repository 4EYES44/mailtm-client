import secrets
import string

import requests

from .exceptions import (
    MailTMAPIError,
    MailTMAuthError,
    MailTMConnectionError,
    MailTMNotAuthenticatedError,
    MailTMRateLimitError,
    MailTMResponseError,
    MailTMServerError,
    MailTMTimeoutError,
)
from .models import Message, MessageSummary
from .validation import (
    MESSAGE_DETAIL_KEYS,
    MESSAGE_SUMMARY_KEYS,
    require_keys,
    require_member_list,
)


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
    def __init__(self, base_url: str = "https://api.mail.tm"):
        self.base_url = base_url
        self.session = requests.Session()
        self.token: str | None = None
        self.domain: str | None = None
        self.email_address: str | None = None
        self.password: str | None = None

    def _send(self, method: str, path: str, **kwargs: object) -> requests.Response:
        operation = f"{method} {path}"
        try:
            response = self.session.request(method, f"{self.base_url}{path}", **kwargs)
        except requests.Timeout as exc:
            raise MailTMTimeoutError(f"{operation} timed out") from exc
        except requests.ConnectionError as exc:
            raise MailTMConnectionError(f"{operation} could not connect") from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise _error_for_status(response) from exc
        return response

    def _read_json(self, method: str, path: str, **kwargs: object) -> dict[str, object]:
        response = self._send(method, path, **kwargs)
        return _json_object(response, f"{method} {path}")

    def get_domain(self) -> str:
        """Fetch an available domain from the MailTR API."""
        payload = self._read_json("GET", "/domains")
        domains = require_member_list(payload)
        if not domains:
            raise MailTMResponseError("No available domains found.", body=payload)
        domain_item = domains[0]
        require_keys(domain_item, ("domain",), body=payload)
        self.domain = domain_item["domain"]
        return self.domain

    def create_account(self, email_address: str, password: str) -> bool:
        """Create a new disposable account."""
        self._read_json(
            "POST",
            "/accounts",
            json={"address": email_address, "password": password},
        )
        return True

    def login(self, email_address: str, password: str) -> str:
        """Login and return the JWT token."""
        payload = self._read_json(
            "POST",
            "/token",
            json={"address": email_address, "password": password},
        )
        require_keys(payload, ("token",))
        token = payload["token"]
        self.token = token
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        return token

    def read_inbox(self) -> list[MessageSummary]:
        """Fetch the list of messages in the inbox."""
        self._require_login()
        payload = self._read_json("GET", "/messages")
        messages = require_member_list(payload)
        for message in messages:
            require_keys(message, MESSAGE_SUMMARY_KEYS, body=payload)
        return messages

    def read_message(self, message_id: str) -> Message:
        """Fetch the full content of a specific message."""
        self._require_login()
        payload = self._read_json("GET", f"/messages/{message_id}")
        require_keys(payload, MESSAGE_DETAIL_KEYS)
        return payload

    def _require_login(self) -> None:
        if not self.token:
            raise MailTMNotAuthenticatedError("Not authenticated. Call login() first.")

    def generate_random_credentials(self) -> tuple[str, str]:
        """Helper to generate a random email and password."""
        if not self.domain:
            self.get_domain()
        
        local_part = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10))
        email = f"{local_part}@{self.domain}"
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        return email, password
