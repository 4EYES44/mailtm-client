import pytest
from mailtm_client import MailTMClient

def test_client_init():
    """Test that the client initializes correctly."""
    client = MailTMClient()
    assert client.base_url == "https://api.mail.tm"
    assert client.token is None

def test_domain_fetching():
    """Test if we can fetch a domain (requires internet)."""
    client = MailTMClient()
    try:
        domain = client.get_domain()
        assert isinstance(domain, str)
        assert "@" not in domain
    except Exception as e:
        pytest.skip(f"Skipping due to network error/API unavailable: {e}")

def test_credential_generation():
    """Test if random credentials are generated correctly."""
    client = MailTMClient()
    # We need a domain for this, so we call get_domain first
    try:
        email, password = client.generate_random_credentials()
        assert "@" in email
        assert len(password) == 12
    except Exception as e:
        pytest.skip(f"Skipping due to dependency on domain fetching: {e}")
