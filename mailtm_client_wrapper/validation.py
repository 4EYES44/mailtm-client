"""Shallow checks on Mail.tm JSON bodies.

Every collection reader uses these helpers. They require a ``hydra:member``
list and the keys a caller can rely on. They do not check field types.
"""

from .exceptions import MailTMResponseError

MESSAGE_SUMMARY_KEYS = ("id", "from", "subject", "createdAt", "seen", "hasAttachments")
MESSAGE_DETAIL_KEYS = (*MESSAGE_SUMMARY_KEYS, "text", "html")


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
    """Raise if any key is absent, naming that key and chaining the cause."""
    error_body = payload if body is None else body
    for key in keys:
        try:
            if not isinstance(payload, dict):
                raise TypeError(key)
            payload[key]
        except (KeyError, TypeError) as exc:
            raise MailTMResponseError(
                f"Response is missing {key}.",
                body=error_body,
            ) from exc
