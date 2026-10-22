"""Mail.tm response bodies for mocked tests.

Documented, not captured.

Field sets follow the documented API shapes. The 401, 404, and 422 bodies
use the shapes recorded in the API research notes. No populated message was
captured, so the message bodies are examples of those shapes, not live payloads.
"""

BASE_URL = "https://api.mail.tm"

DOMAIN = {
    "@id": "/domains/000000000000000000000001",
    "@type": "Domain",
    "@context": "/contexts/Domain",
    "id": "000000000000000000000001",
    "domain": "example.com",
    "isActive": True,
    "isPrivate": False,
    "createdAt": "2022-04-01T00:00:00.000Z",
    "updatedAt": "2022-04-01T00:00:00.000Z",
}

DOMAIN_COLLECTION = {
    "@context": "/contexts/Domain",
    "@id": "/domains",
    "@type": "hydra:Collection",
    "hydra:totalItems": 1,
    "hydra:member": [DOMAIN],
}

TOKEN = {
    "id": "000000000000000000000002",
    "token": "documented-token",
}

ACCOUNT = {
    "@context": "/contexts/Account",
    "@id": "/accounts/000000000000000000000002",
    "@type": "Account",
    "id": "000000000000000000000002",
    "address": "user@example.com",
    "quota": 0,
    "used": 0,
    "isDisabled": False,
    "isDeleted": False,
    "createdAt": "2022-04-01T00:00:00.000Z",
    "updatedAt": "2022-04-01T00:00:00.000Z",
}

MESSAGE_LIST_ITEM = {
    "@id": "/messages/000000000000000000000003",
    "@type": "Message",
    "@context": "/contexts/Message",
    "id": "000000000000000000000003",
    "accountId": "000000000000000000000002",
    "msgid": "<documented@example.com>",
    "from": {"name": "Sender", "address": "sender@example.com"},
    "to": [{"name": "User", "address": "user@example.com"}],
    "subject": "Subject",
    "intro": "Message preview",
    "seen": False,
    "isDeleted": False,
    "hasAttachments": False,
    "size": 0,
    "downloadUrl": "/messages/000000000000000000000003/download",
    "createdAt": "2022-04-01T00:00:00.000Z",
    "updatedAt": "2022-04-01T00:00:00.000Z",
}

MESSAGE_DETAIL = {
    "@context": "/contexts/Message",
    "@id": "/messages/000000000000000000000003",
    "@type": "Message",
    "id": "000000000000000000000003",
    "accountId": "000000000000000000000002",
    "msgid": "<documented@example.com>",
    "from": {"name": "Sender", "address": "sender@example.com"},
    "to": [{"name": "User", "address": "user@example.com"}],
    "cc": ["cc@example.com"],
    "bcc": ["bcc@example.com"],
    "subject": "Subject",
    "seen": False,
    "flagged": False,
    "isDeleted": False,
    "verifications": ["string"],
    "retention": True,
    "retentionDate": "2022-04-01T00:00:00.000Z",
    "text": "Message body",
    "html": ["<p>Message body</p>"],
    "hasAttachments": True,
    "attachments": [
        {
            "id": "ATTACH000001",
            "filename": "file.png",
            "contentType": "image/png",
            "disposition": "attachment",
            "transferEncoding": "base64",
            "related": False,
            "size": 666,
            "downloadUrl": "/messages/000000000000000000000003/attachment/ATTACH000001",
        }
    ],
    "size": 666,
    "downloadUrl": "/messages/000000000000000000000003/download",
    "createdAt": "2022-04-01T00:00:00.000Z",
    "updatedAt": "2022-04-01T00:00:00.000Z",
}

ERROR_401 = {"code": 401, "message": "Invalid JWT Token"}

ERROR_404 = {
    "@id": "/errors/404",
    "@type": "hydra:Error",
    "title": "An error occurred",
    "detail": "Not Found",
    "status": 404,
    "type": "/errors/404",
    "hydra:title": "An error occurred",
    "hydra:description": "Not Found",
}

ERROR_422 = {
    "@id": "/validation_errors/c1051bb4-d103-4f74-8988-acbcafc7fdc3",
    "@type": "ConstraintViolationList",
    "status": 422,
    "violations": [
        {
            "propertyPath": "address",
            "message": "This value should not be blank.",
            "code": "c1051bb4-d103-4f74-8988-acbcafc7fdc3",
        }
    ],
    "detail": "address: This value should not be blank.",
    "hydra:title": "An error occurred",
    "hydra:description": "address: This value should not be blank.",
    "type": "/validation_errors/c1051bb4-d103-4f74-8988-acbcafc7fdc3",
    "title": "An error occurred",
}


def _summary(
    message_id: str,
    *,
    subject: str = "Subject",
    intro: str = "Message preview",
) -> dict:
    """One inbox summary, copied from the documented list item."""
    message = dict(MESSAGE_LIST_ITEM)
    message["id"] = message_id
    message["@id"] = f"/messages/{message_id}"
    message["subject"] = subject
    message["intro"] = intro
    return message


def _calls_for(mocked_responses, path: str, *, method: str | None = None) -> list:
    """Recorded calls whose path matches, ignoring a query string."""
    url = f"{BASE_URL}{path}"
    return [
        call
        for call in mocked_responses.calls
        if (method is None or call.request.method == method)
        and (call.request.url == url or call.request.url.startswith(f"{url}?"))
    ]


def _message_gets(mocked_responses) -> list:
    """Recorded GET /messages calls, including paged URLs."""
    return _calls_for(mocked_responses, "/messages", method="GET")


def _recorded_timeout(mocked_responses, path: str):
    """The timeout of the last recorded call to path."""
    recorded = [
        call.request.req_kwargs["timeout"] for call in _calls_for(mocked_responses, path)
    ]
    assert recorded
    return recorded[-1]
