import random
import string

import responses

from fixtures import BASE_URL, DOMAIN_COLLECTION
from mailtm_client_wrapper import MailTMClient

LOCAL_PART_CHARACTERS = string.ascii_lowercase + string.digits
PASSWORD_CHARACTERS = string.ascii_letters + string.digits


def _stub_domain_lookup(mocked_responses) -> None:
    mocked_responses.add(
        responses.GET,
        f"{BASE_URL}/domains",
        json=DOMAIN_COLLECTION,
        status=200,
    )


def _block_random(monkeypatch) -> None:
    """Make the random module unusable without touching secrets' already-bound generator."""

    def refuse(*args, **kwargs):
        raise AssertionError("credentials must not use random")

    class BlockedRandom:
        def __init__(self, *args, **kwargs):
            raise AssertionError("credentials must not use random")

    for name in ("choice", "choices", "randrange", "randint", "sample", "getrandbits"):
        monkeypatch.setattr(random, name, refuse)
    monkeypatch.setattr(random, "Random", BlockedRandom)
    monkeypatch.setattr(random, "SystemRandom", BlockedRandom)


def test_credentials_keep_length_and_character_sets_when_random_is_unusable(
    monkeypatch, mocked_responses
):
    """Local part and password stay in the documented sets without the random module."""
    _stub_domain_lookup(mocked_responses)
    _block_random(monkeypatch)

    email, password = MailTMClient().generate_random_credentials()
    local_part, domain = email.split("@")

    assert domain == "example.com"
    assert len(local_part) == 10
    assert set(local_part) <= set(LOCAL_PART_CHARACTERS)
    assert len(password) == 12
    assert set(password) <= set(PASSWORD_CHARACTERS)


def test_address_uses_the_looked_up_domain_when_none_is_set(mocked_responses):
    """An unset domain is fetched and becomes the address domain."""
    _stub_domain_lookup(mocked_responses)
    client = MailTMClient()

    email, _password = client.generate_random_credentials()

    assert email.endswith("@example.com")
    assert [(call.request.method, call.request.url) for call in mocked_responses.calls] == [
        ("GET", f"{BASE_URL}/domains")
    ]


def test_address_uses_a_preset_domain_without_a_lookup(mocked_responses):
    """A domain already on the client is used, and no domain request is made."""
    client = MailTMClient()
    client.domain = "preset.example"

    email, _password = client.generate_random_credentials()

    assert email.endswith("@preset.example")
    assert list(mocked_responses.calls) == []


def test_two_generations_return_different_credentials(mocked_responses):
    """Successive calls do not repeat the address or the password."""
    _stub_domain_lookup(mocked_responses)
    client = MailTMClient()

    first_email, first_password = client.generate_random_credentials()
    second_email, second_password = client.generate_random_credentials()

    assert first_email != second_email
    assert first_password != second_password
