"""Typed shapes for Mail.tm message payloads.

These types are annotations only. The client still returns the dicts the API
sent. Keys the API may omit are NotRequired. ``from`` is a keyword, so the
dictionaries are built with the functional form.
"""

from typing import NotRequired, TypedDict

_JSON_LD = {
    "@id": NotRequired[str],
    "@type": NotRequired[str],
    "@context": NotRequired[str | dict[str, object]],
}

_SUMMARY_REQUIRED = {
    "id": str,
    "from": dict[str, object],
    "subject": str,
    "createdAt": str,
    "seen": bool,
    "hasAttachments": bool,
}

_SUMMARY_OPTIONAL = {
    **_JSON_LD,
    "accountId": NotRequired[str],
    "msgid": NotRequired[str],
    "to": NotRequired[list[dict[str, object]]],
    "intro": NotRequired[str],
    "isDeleted": NotRequired[bool],
    "size": NotRequired[int],
    "downloadUrl": NotRequired[str],
    "updatedAt": NotRequired[str],
    "sourceUrl": NotRequired[str | None],
}

MessageSummary = TypedDict(
    "MessageSummary",
    {**_SUMMARY_REQUIRED, **_SUMMARY_OPTIONAL},
)

Message = TypedDict(
    "Message",
    {
        **_SUMMARY_REQUIRED,
        "text": str,
        "html": list[str],
        **_SUMMARY_OPTIONAL,
        "cc": NotRequired[list[object]],
        "bcc": NotRequired[list[object]],
        "flagged": NotRequired[bool],
        "verifications": NotRequired[list[str]],
        "retention": NotRequired[bool],
        "retentionDate": NotRequired[str],
        "attachments": NotRequired[list[dict[str, object]]],
    },
)
