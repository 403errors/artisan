"""Unit tests for the shared GitHub App auth helpers. No network: the AppAuthStrategy/GitHub
client construction is asserted via mocks, and `mint_installation_token` is exercised against a
fake `gh.rest.apps` surface."""

from unittest.mock import MagicMock

import pytest
from artisan_shared import github_auth


def test_build_installation_client_uses_app_auth_strategy(monkeypatch) -> None:
    strategy = MagicMock(name="AppAuthStrategy")
    app_auth = MagicMock()
    app_auth.as_installation.return_value = strategy
    github = MagicMock(name="GitHub")
    monkeypatch.setattr(github_auth, "AppAuthStrategy", lambda **kw: app_auth)
    monkeypatch.setattr(github_auth, "GitHub", github)

    result = github_auth.build_installation_client(
        app_id="123", installation_id="456", private_key="pem"
    )

    app_auth.as_installation.assert_called_once_with(456)
    github.assert_called_once_with(strategy)
    assert result is github.return_value


@pytest.mark.asyncio
async def test_mint_installation_token_returns_parsed_token(monkeypatch) -> None:
    response = MagicMock()
    response.parsed_data.token = "ghs_installation_token"

    class FakeGitHub:
        def __init__(self, strategy):
            self.rest = MagicMock()
            self.rest.apps.async_create_installation_access_token = self._mint(response)

        @staticmethod
        def _mint(resp):
            async def _call(installation_id: int):
                assert installation_id == 456
                return resp

            return _call

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(github_auth, "AppAuthStrategy", lambda **kw: MagicMock())
    monkeypatch.setattr(github_auth, "GitHub", FakeGitHub)

    token = await github_auth.mint_installation_token(
        app_id="123", installation_id="456", private_key="pem"
    )
    assert token == "ghs_installation_token"


@pytest.mark.parametrize("installation_id", ["456", 456])
def test_build_installation_client_accepts_str_or_int_like_ids(monkeypatch, installation_id) -> None:
    app_auth = MagicMock()
    monkeypatch.setattr(github_auth, "AppAuthStrategy", lambda **kw: app_auth)
    monkeypatch.setattr(github_auth, "GitHub", MagicMock())

    github_auth.build_installation_client(
        app_id="123", installation_id=str(installation_id), private_key="pem"
    )
    app_auth.as_installation.assert_called_once_with(456)
