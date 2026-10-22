"""Shallow validation of successful Mail.tm response bodies."""

from typing import get_type_hints

import pytest
import responses

from fixtures import ACCOUNT, MESSAGE_DETAIL, MESSAGE_LIST_ITEM, TOKEN
from mailtm_client_wrapper import MailTMClient, MailTMResponseError, Message, MessageSummary

BASE_URL = "https://api.mail.tm"
SUMMARY_KEYS = ("id", "from", "subject", "createdAt", "seen", "hasAttachments")
DETAIL_KEYS = SUMMARY_KEYS + ("text", "html")


def _logged_in_client(mocked_responses) -> MailTMClient:
    mocked_responses.add(responses.POST, f"{BASE_URL}/token", json=TOKEN, status=200)
    client = MailTMClient()
    client.login("user@example.com", "password")
    return client


def test_login_names_a_missing_token_and_chains_the_key_error(mocked_responses):
    """A token response without token names that key and chains the KeyError."""
    mocked_responses.add(
        responses.POST,
        f"{BASE_URL}/token",
        json={"id": "abc"},
        status=200,
    )

    with pytest.raises(MailTMResponseError, match="token") as caught:
        MailTMClient().login("user@example.com", "password")

    assert isinstance(caught.value.__cause__, KeyError)
    assert caught.value.body == {"id": "abc"}


def test_domain_lookup_names_a_missing_domain_key(mocked_responses):
    """The first domain item without a domain key names that key."""
    payload = {"hydra:member": [{"id": "1", "isActive": True}]}
    mocked_responses.add(responses.GET, f"{BASE_URL}/domains", json=payload, status=200)

    with pytest.raises(MailTMResponseError, match=r"\bdomain\b") as caught:
        MailTMClient().get_domain()

    assert isinstance(caught.value.__cause__, KeyError)
    assert caught.value.body == payload


@pytest.mark.parametrize("missing_key", SUMMARY_KEYS)
def test_inbox_names_a_missing_summary_key(mocked_responses, missing_key):
    """Each inbox item must include the summary keys the caller can rely on."""
    item = dict(MESSAGE_LIST_ITEM)
    del item[missing_key]
    payload = {"hydra:member": [item]}
    client = _logged_in_client(mocked_responses)
    mocked_responses.add(responses.GET, f"{BASE_URL}/messages", json=payload, status=200)

    with pytest.raises(MailTMResponseError, match=rf"\b{missing_key}\b") as caught:
        client.read_inbox()

    assert isinstance(caught.value.__cause__, KeyError)
    assert caught.value.body == payload


@pytest.mark.parametrize("missing_key", DETAIL_KEYS)
def test_message_names_a_missing_detail_key(mocked_responses, missing_key):
    """A message detail must include the summary keys plus text and html."""
    message = dict(MESSAGE_DETAIL)
    message_id = "000000000000000000000003"
    del message[missing_key]
    client = _logged_in_client(mocked_responses)
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/messages/{message_id}",
        json=message,
        status=200,
    )

    with pytest.raises(MailTMResponseError, match=rf"\b{missing_key}\b") as caught:
        client.read_message(message_id)

    assert isinstance(caught.value.__cause__, KeyError)
    assert caught.value.body == message


@pytest.mark.parametrize(
    ("method_name", "path", "args", "authenticated"),
    [
        ("read_inbox", "/messages", (), True),
        ("get_domain", "/domains", (), False),
    ],
)
@pytest.mark.parametrize(
    ("members", "cause_type"),
    [
        ("missing", KeyError),
        ({"id": "not-a-list"}, TypeError),
        ("not-a-list", TypeError),
    ],
)
def test_missing_or_non_list_member_is_a_response_error(
    mocked_responses,
    method_name,
    path,
    args,
    authenticated,
    members,
    cause_type,
):
    """A collection without a hydra:member list fails instead of looking empty."""
    payload = {"hydra:totalItems": 0}
    if members != "missing":
        payload["hydra:member"] = members
    client = _logged_in_client(mocked_responses) if authenticated else MailTMClient()
    mocked_responses.add(responses.GET, f"{BASE_URL}{path}", json=payload, status=200)

    with pytest.raises(MailTMResponseError, match="hydra:member") as caught:
        getattr(client, method_name)(*args)

    assert isinstance(caught.value.__cause__, cause_type)
    assert caught.value.body == payload


def test_inbox_item_that_is_not_an_object_names_the_missing_key(mocked_responses):
    """A hydra:member entry that is not an object still fails as a response error."""
    payload = {"hydra:member": ["not-an-object"]}
    client = _logged_in_client(mocked_responses)
    mocked_responses.add(responses.GET, f"{BASE_URL}/messages", json=payload, status=200)

    with pytest.raises(MailTMResponseError, match=r"\bid\b") as caught:
        client.read_inbox()

    assert isinstance(caught.value.__cause__, TypeError)
    assert caught.value.body == payload


def test_inbox_and_message_return_api_dicts_unchanged(mocked_responses):
    """Unknown keys, html lists and timestamp strings come back exactly as sent."""
    summary = dict(MESSAGE_LIST_ITEM)
    del summary["intro"]
    summary["vendor"] = "kept"
    second = dict(MESSAGE_LIST_ITEM)
    second["id"] = "000000000000000000000004"
    del second["updatedAt"]
    second["vendor"] = "kept"
    detail = dict(MESSAGE_DETAIL)
    detail["vendor"] = "kept"
    client = _logged_in_client(mocked_responses)
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/messages",
        json={"hydra:totalItems": 2, "hydra:member": [summary, second]},
        status=200,
    )
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/messages/{summary['id']}",
        json=detail,
        status=200,
    )

    assert client.read_inbox() == [summary, second]
    assert client.read_message(summary["id"]) == detail


def test_inbox_rejects_a_later_item_missing_a_required_key(mocked_responses):
    """A valid first message does not hide a later item that lacks a required key."""
    first = dict(MESSAGE_LIST_ITEM)
    second = dict(MESSAGE_LIST_ITEM)
    second["id"] = "000000000000000000000004"
    del second["seen"]
    payload = {"hydra:member": [first, second]}
    client = _logged_in_client(mocked_responses)
    mocked_responses.add(responses.GET, f"{BASE_URL}/messages", json=payload, status=200)

    with pytest.raises(MailTMResponseError, match=r"\bseen\b") as caught:
        client.read_inbox()

    assert isinstance(caught.value.__cause__, KeyError)
    assert caught.value.body == payload


def test_empty_inbox_is_an_empty_list(mocked_responses):
    """A present empty hydra:member list is an empty inbox, not an error."""
    client = _logged_in_client(mocked_responses)
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/messages",
        json={"hydra:totalItems": 0, "hydra:member": []},
        status=200,
    )

    assert client.read_inbox() == []


def test_domain_lookup_returns_the_first_domain_key(mocked_responses):
    """Domain lookup uses the first item's domain key and does not filter the list."""
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        json={
            "hydra:member": [
                {"domain": "first.example", "isActive": False, "isPrivate": True},
                {"domain": "second.example", "isActive": True, "isPrivate": False},
            ]
        },
        status=200,
    )
    client = MailTMClient()

    assert client.get_domain() == "first.example"
    assert client.domain == "first.example"


def test_create_account_returns_true(mocked_responses):
    """Account creation still reports success as True."""
    mocked_responses.add(
        responses.POST,
        f"{BASE_URL}/accounts",
        json=ACCOUNT,
        status=201,
    )

    assert MailTMClient().create_account("user@example.com", "password") is True


def test_login_returns_the_token_string_and_stores_it(mocked_responses):
    """Login still returns the token string and keeps it on the client."""
    mocked_responses.add(responses.POST, f"{BASE_URL}/token", json=TOKEN, status=200)
    client = MailTMClient()

    assert client.login("user@example.com", "password") == "documented-token"
    assert client.token == "documented-token"


def test_message_types_are_exported_and_annotate_the_read_methods():
    """Inbox and message reads are annotated with the exported message types."""
    assert get_type_hints(MailTMClient.read_inbox)["return"] == list[MessageSummary]
    assert get_type_hints(MailTMClient.read_message)["return"] == Message
