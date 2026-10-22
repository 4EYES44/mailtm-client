"""Waiting for an inbox message through the public client."""

import pytest
import responses
from responses import matchers

from fixtures import BASE_URL, MESSAGE_DETAIL, _summary
from mailtm_client_wrapper import (
    MailTMClient,
    MailTMNotAuthenticatedError,
    MailTMServerError,
    MailTMWaitTimeoutError,
    RetryPolicy,
)


def _detail(message_id: str) -> dict:
    message = dict(MESSAGE_DETAIL)
    message["id"] = message_id
    message["@id"] = f"/messages/{message_id}"
    return message


def _add_inbox(
    mocked_responses,
    members: list,
    *,
    page: int = 1,
    total: int | None = None,
) -> None:
    if total is None:
        total = len(members)
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/messages",
        json={"hydra:member": members, "hydra:totalItems": total},
        status=200,
        match=[matchers.query_param_matcher({"page": str(page)})],
    )


def _add_message(mocked_responses, message_id: str) -> None:
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/messages/{message_id}",
        json=_detail(message_id),
        status=200,
    )


def test_message_already_in_the_inbox_is_returned_without_sleeping(
    authenticated_client, mocked_responses, fake_clock
):
    """A message that is already there comes back in full on the first poll, with no delay."""
    _add_inbox(mocked_responses, [_summary("msg-1")])
    _add_message(mocked_responses, "msg-1")
    client = authenticated_client

    assert client.wait_for_message() == _detail("msg-1")
    assert fake_clock.delays == []


def test_message_arriving_on_the_third_poll_waits_two_intervals(
    authenticated_client, mocked_responses, fake_clock
):
    """A message that shows up on the third poll is returned after two default poll intervals."""
    _add_inbox(mocked_responses, [])
    _add_inbox(mocked_responses, [])
    _add_inbox(mocked_responses, [_summary("msg-1")])
    _add_message(mocked_responses, "msg-1")
    client = authenticated_client

    assert client.wait_for_message() == _detail("msg-1")
    assert fake_clock.delays == [3.0, 3.0]


def test_match_on_a_later_inbox_page_is_returned(
    authenticated_client, mocked_responses, fake_clock
):
    """A matching message that is not on the first page is still returned, with no extra wait."""
    _add_inbox(mocked_responses, [_summary("msg-1", subject="Welcome")], total=2)
    _add_inbox(
        mocked_responses,
        [_summary("msg-2", subject="Your code")],
        page=2,
        total=2,
    )
    _add_message(mocked_responses, "msg-2")
    client = authenticated_client

    found = client.wait_for_message(lambda message: message["subject"] == "Your code")

    assert found == _detail("msg-2")
    assert fake_clock.delays == []


def test_predicate_selects_the_matching_summary(
    authenticated_client, mocked_responses, fake_clock
):
    """The predicate sees the summary and the full text of only that message is returned."""
    _add_inbox(
        mocked_responses,
        [
            _summary("msg-1", subject="Welcome"),
            _summary("msg-2", subject="Your code", intro="code 1234"),
        ],
    )
    _add_message(mocked_responses, "msg-2")
    client = authenticated_client

    found = client.wait_for_message(
        lambda message: message["subject"] == "Your code" and message["intro"] == "code 1234"
    )

    assert found == _detail("msg-2")
    assert fake_clock.delays == []


def test_excluded_ids_are_skipped(authenticated_client, mocked_responses, fake_clock):
    """Messages named in exclude_ids are ignored, and the next one is returned in full."""
    _add_inbox(mocked_responses, [_summary("msg-1"), _summary("msg-2")])
    _add_message(mocked_responses, "msg-2")
    client = authenticated_client

    assert client.wait_for_message(exclude_ids={"msg-1"}) == _detail("msg-2")
    assert fake_clock.delays == []


def test_no_match_raises_wait_timeout_after_the_deadline_poll(
    authenticated_client, mocked_responses, fake_clock
):
    """With nothing to return, the last poll happens at the deadline and names that timeout."""
    for _ in range(4):
        _add_inbox(mocked_responses, [])
    client = authenticated_client

    with pytest.raises(MailTMWaitTimeoutError) as caught:
        client.wait_for_message(timeout=7.0, poll_interval=3.0)

    assert caught.value.timeout == 7.0
    assert fake_clock.delays == [3.0, 3.0, 1.0]


def test_default_wait_polls_through_sixty_seconds(
    authenticated_client, mocked_responses, fake_clock
):
    """The default deadline is 60 seconds, with a poll every 3 seconds including the deadline."""
    for _ in range(21):
        _add_inbox(mocked_responses, [])
    client = authenticated_client

    with pytest.raises(MailTMWaitTimeoutError) as caught:
        client.wait_for_message()

    assert caught.value.timeout == 60.0
    assert fake_clock.delays == [3.0] * 20


def test_message_arriving_on_the_deadline_poll_is_returned(
    authenticated_client, mocked_responses, fake_clock
):
    """A message that lands in the last interval is still returned by the poll at the deadline."""
    for _ in range(3):
        _add_inbox(mocked_responses, [])
    _add_inbox(mocked_responses, [_summary("msg-1")])
    _add_message(mocked_responses, "msg-1")
    client = authenticated_client

    assert client.wait_for_message(timeout=7.0, poll_interval=3.0) == _detail("msg-1")
    assert fake_clock.delays == [3.0, 3.0, 1.0]


def test_inbox_error_stops_the_wait_immediately(mocked_responses, fake_clock, log_in):
    """A library error from a poll is raised at once and the wait does not sleep or poll again."""
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/messages",
        json={"message": "unavailable"},
        status=503,
        match=[matchers.query_param_matcher({"page": "1"})],
    )
    client = log_in(MailTMClient(retry=RetryPolicy(max_attempts=1)))

    with pytest.raises(MailTMServerError) as caught:
        client.wait_for_message(timeout=30.0, poll_interval=3.0)

    assert caught.value.status_code == 503
    assert fake_clock.delays == []


def test_waiting_before_login_makes_no_request(mocked_responses, fake_clock):
    """Calling the wait before login() explains that, and does not call the API or sleep."""
    with pytest.raises(MailTMNotAuthenticatedError, match=r"login\(\)"):
        MailTMClient().wait_for_message()

    assert list(mocked_responses.calls) == []
    assert fake_clock.delays == []


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("timeout", 0, ValueError),
        ("timeout", 0.0, ValueError),
        ("timeout", -1, ValueError),
        ("timeout", -0.5, ValueError),
        ("timeout", "60", TypeError),
        ("timeout", None, ValueError),
        ("timeout", True, TypeError),
        ("timeout", False, TypeError),
        ("poll_interval", 0, ValueError),
        ("poll_interval", 0.0, ValueError),
        ("poll_interval", -1, ValueError),
        ("poll_interval", -0.5, ValueError),
        ("poll_interval", "3", TypeError),
        ("poll_interval", None, ValueError),
        ("poll_interval", True, TypeError),
        ("poll_interval", False, TypeError),
        ("timeout", float("inf"), ValueError),
        ("timeout", float("-inf"), ValueError),
        ("timeout", float("nan"), ValueError),
        ("poll_interval", float("inf"), ValueError),
        ("poll_interval", float("-inf"), ValueError),
        ("poll_interval", float("nan"), ValueError),
    ],
)
def test_non_positive_or_non_numeric_wait_timing_is_rejected(
    authenticated_client, mocked_responses, fake_clock, field, value, error_type
):
    """A wait timeout or poll interval that is not a positive number is rejected before any poll."""
    client = authenticated_client
    calls_after_login = len(mocked_responses.calls)

    with pytest.raises(error_type):
        client.wait_for_message(**{field: value})

    assert len(mocked_responses.calls) == calls_after_login
    assert fake_clock.delays == []
