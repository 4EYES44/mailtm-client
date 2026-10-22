"""Inbox paging through the public client."""

import pytest
import responses
from responses import matchers

from fixtures import BASE_URL, MESSAGE_LIST_ITEM
from mailtm_client_wrapper import MailTMServerError


def _summary(message_id: str) -> dict:
    message = dict(MESSAGE_LIST_ITEM)
    message["id"] = message_id
    message["@id"] = f"/messages/{message_id}"
    return message


def _add_page(
    mocked_responses,
    page: int,
    members: list,
    *,
    total: object = "omit",
    status: int = 200,
) -> None:
    payload: dict = {"hydra:member": members}
    if total != "omit":
        payload["hydra:totalItems"] = total
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/messages",
        json=payload,
        status=status,
        match=[matchers.query_param_matcher({"page": page})],
    )


def _message_gets(mocked_responses) -> list:
    return [
        call
        for call in mocked_responses.calls
        if call.request.method == "GET" and call.request.url.split("?")[0] == f"{BASE_URL}/messages"
    ]


def test_three_page_inbox_is_returned_in_order(authenticated_client, mocked_responses):
    """Pages 1, 2 and 3 come back as one list in server order, each with its own timeout."""
    first = _summary("msg-1")
    second = _summary("msg-2")
    third = _summary("msg-3")
    _add_page(mocked_responses, 1, [first], total=3)
    _add_page(mocked_responses, 2, [second], total=3)
    _add_page(mocked_responses, 3, [third], total=3)
    client = authenticated_client

    assert client.read_inbox(timeout=3.5) == [first, second, third]
    assert [call.request.url for call in _message_gets(mocked_responses)] == [
        f"{BASE_URL}/messages?page=1",
        f"{BASE_URL}/messages?page=2",
        f"{BASE_URL}/messages?page=3",
    ]
    assert [call.request.req_kwargs["timeout"] for call in _message_gets(mocked_responses)] == [
        3.5,
        3.5,
        3.5,
    ]


def test_message_arriving_mid_listing_appears_once(authenticated_client, mocked_responses):
    """A message that shifts onto the next page is kept once and does not raise."""
    first = _summary("msg-1")
    shifted = _summary("msg-2")
    arrived = _summary("msg-3")
    _add_page(mocked_responses, 1, [first, shifted], total=3)
    _add_page(mocked_responses, 2, [shifted, arrived], total=3)
    client = authenticated_client

    assert client.read_inbox() == [first, shifted, arrived]


def test_paging_stops_on_an_empty_page(authenticated_client, mocked_responses):
    """An empty page ends the inbox even when the reported total is still higher."""
    first = _summary("msg-1")
    _add_page(mocked_responses, 1, [first], total=10)
    _add_page(mocked_responses, 2, [], total=10)
    client = authenticated_client

    assert client.read_inbox() == [first]
    assert [call.request.url for call in _message_gets(mocked_responses)] == [
        f"{BASE_URL}/messages?page=1",
        f"{BASE_URL}/messages?page=2",
    ]


def test_paging_stops_when_a_page_repeats_known_ids(authenticated_client, mocked_responses):
    """A server that ignores page and repeats the same messages does not duplicate or loop."""
    first = _summary("msg-1")
    second = _summary("msg-2")
    _add_page(mocked_responses, 1, [first, second], total=30)
    _add_page(mocked_responses, 2, [first, second], total=30)
    client = authenticated_client

    assert client.read_inbox() == [first, second]
    assert [call.request.url for call in _message_gets(mocked_responses)] == [
        f"{BASE_URL}/messages?page=1",
        f"{BASE_URL}/messages?page=2",
    ]


@pytest.mark.parametrize(
    ("message_ids", "total"),
    [
        (("msg-1", "msg-2"), 2),
        (("msg-1",), 0),
    ],
)
def test_paging_stops_when_the_reported_total_is_reached(authenticated_client, mocked_responses, message_ids, total):
    """Once the collected count reaches hydra:totalItems, no further page is requested."""
    messages = [_summary(message_id) for message_id in message_ids]
    _add_page(mocked_responses, 1, messages, total=total)
    client = authenticated_client

    assert client.read_inbox() == messages
    assert [call.request.url for call in _message_gets(mocked_responses)] == [
        f"{BASE_URL}/messages?page=1",
    ]


def test_failure_on_a_later_page_raises_that_error(authenticated_client, mocked_responses):
    """A failed later page raises that error and does not return the earlier messages."""
    _add_page(mocked_responses, 1, [_summary("msg-1")], total=2)
    _add_page(mocked_responses, 2, [], status=503)
    client = authenticated_client

    with pytest.raises(MailTMServerError) as caught:
        client.read_inbox()

    assert caught.value.status_code == 503


def test_paging_ignores_a_missing_total_and_hydra_view(authenticated_client, mocked_responses):
    """Without hydra:view or hydra:totalItems, paging still returns every page."""
    first = _summary("msg-1")
    second = _summary("msg-2")
    _add_page(mocked_responses, 1, [first])
    _add_page(mocked_responses, 2, [second])
    _add_page(mocked_responses, 3, [])
    client = authenticated_client

    assert client.read_inbox() == [first, second]


@pytest.mark.parametrize("total", [None, "1", 1.5, True, -1])
def test_paging_continues_when_the_reported_total_is_not_a_count(authenticated_client, mocked_responses, total):
    """An unusable hydra:totalItems does not end or crash the listing."""
    first = _summary("msg-1")
    second = _summary("msg-2")
    _add_page(mocked_responses, 1, [first], total=total)
    _add_page(mocked_responses, 2, [second], total=total)
    _add_page(mocked_responses, 3, [], total=total)
    client = authenticated_client

    assert client.read_inbox() == [first, second]
