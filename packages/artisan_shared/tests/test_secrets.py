"""Unit tests for the shared Secret Manager fetch. The GCP client is mocked — these cover the
path construction and payload decoding, not a live Secret Manager."""

from unittest.mock import MagicMock

from artisan_shared import secrets


def _patched_client(monkeypatch) -> MagicMock:
    client = MagicMock()
    client.secret_version_path.side_effect = lambda project, name, version: (
        f"projects/{project}/secrets/{name}/versions/{version}"
    )
    client.access_secret_version.return_value.payload.data = b"s3cr3t-value"
    monkeypatch.setattr(secrets.secretmanager, "SecretManagerServiceClient", lambda: client)
    return client


def test_fetches_latest_version_by_default(monkeypatch) -> None:
    client = _patched_client(monkeypatch)

    assert secrets.fetch_secret("my-project", "github-webhook-secret") == "s3cr3t-value"
    client.access_secret_version.assert_called_once_with(
        name="projects/my-project/secrets/github-webhook-secret/versions/latest"
    )


def test_explicit_version_is_threaded_through(monkeypatch) -> None:
    client = _patched_client(monkeypatch)

    secrets.fetch_secret("my-project", "jira-api-token", version="3")
    client.access_secret_version.assert_called_once_with(
        name="projects/my-project/secrets/jira-api-token/versions/3"
    )


def test_payload_is_utf8_decoded(monkeypatch) -> None:
    client = _patched_client(monkeypatch)
    client.access_secret_version.return_value.payload.data = "töken".encode()

    assert secrets.fetch_secret("my-project", "name") == "töken"
