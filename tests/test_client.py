import os
import tomllib
from pathlib import Path

import pytest
import requests
from mailtm_client_wrapper import MailTMClient

ROOT = Path(__file__).resolve().parents[1]


def test_unmocked_request_is_rejected():
    """An HTTP call with no registered mock never reaches the network."""
    with pytest.raises(
        requests.exceptions.ConnectionError,
        match="doesn't match any registered mock",
    ):
        requests.get("https://api.mail.tm/domains")


def test_package_targets_python_312_through_314():
    """Python 3.12 is the baseline, with classifiers through 3.14 and a matching lockfile."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    lock_header = (ROOT / "uv.lock").read_text().split("[[package]]", 1)[0]

    assert project["requires-python"] == ">=3.12"
    assert "Programming Language :: Python :: 3.12" in project["classifiers"]
    assert "Programming Language :: Python :: 3.13" in project["classifiers"]
    assert "Programming Language :: Python :: 3.14" in project["classifiers"]
    assert 'requires-python = ">=3.12"' in lock_header


def test_pytest_and_responses_stay_out_of_runtime_dependencies():
    """The test runner and HTTP mocking library are dev-only."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    runtime = pyproject["project"]["dependencies"]

    assert any(item.startswith("requests") for item in runtime)
    assert all(not item.startswith(("pytest", "responses")) for item in runtime)
    assert pyproject["dependency-groups"]["dev"] == ["pytest", "responses"]


def test_client_init():
    """Test that the client initializes correctly."""
    client = MailTMClient()
    assert client.base_url == "https://api.mail.tm"
    assert client.token is None


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("MAILTM_LIVE") != "1",
    reason="set MAILTM_LIVE=1 to call the live API",
)
def test_live_domain_lookup_returns_a_domain():
    """Opt-in smoke test: read one domain, and fail if the call fails."""
    domain = MailTMClient().get_domain()

    assert isinstance(domain, str)
    assert domain
    assert "@" not in domain
