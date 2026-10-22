"""Shallow checks on Mail.tm JSON bodies.

Every collection reader uses these helpers. They require a ``hydra:member``
list and the keys a caller can rely on. They do not check field types.
"""

from .exceptions import MailTMResponseError
from .models import Message, MessageSummary


def _required_keys(shape: type[MessageSummary] | type[Message]) -> tuple[str, ...]:
    """Required TypedDict keys in definition order. There is no second list."""
    required = shape.__required_keys__
    return tuple(key for key in shape.__annotations__ if key in required)


MESSAGE_SUMMARY_KEYS = _required_keys(MessageSummary)
MESSAGE_DETAIL_KEYS = _required_keys(Message)


def require_member_list(payload: dict[str, object]) -> list[object]:
    """Return hydra:member when it is a list. Missing or non-list is an error."""
    try:
        members = payload["hydra:member"]
    except KeyError as exc:
        raise MailTMResponseError(
            "Response is missing hydra:member.",
            body=payload,
        ) from exc
    if isinstance(members, list):
        return members
    raise MailTMResponseError(
        "Response hydra:member is not a list.",
        body=payload,
    ) from TypeError("hydra:member")


def require_keys(
    payload: object,
    keys: tuple[str, ...],
    *,
    body: object | None = None,
) -> None:
    """Raise if the value is not an object or any key is absent.

    A non-object is reported as such. A missing key names that key and chains
    the ``KeyError``.
    """
    error_body = payload if body is None else body
    if not isinstance(payload, dict):
        raise MailTMResponseError(
            "Response item is not an object.",
            body=error_body,
        ) from TypeError("item")
    for key in keys:
        try:
            payload[key]
        except KeyError as exc:
            raise MailTMResponseError(
                f"Response is missing {key}.",
                body=error_body,
            ) from exc
