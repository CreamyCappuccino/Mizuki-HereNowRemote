import pytest
import httpx

from here_now_remote.here_now_http import ProviderHTTP, load_api_key
from here_now_remote.site_models import HereNowError, TextChange, validate_path


@pytest.mark.parametrize("path", ["/index.html", "../a", "a/../b", "a//b", "a\\b", "a%2fb", "x?y", "https://example.com", "a\nb"])
def test_relative_path_only(path):
    with pytest.raises(HereNowError):
        validate_path(path)


@pytest.mark.parametrize("path", [".env", ".env.production", ".ssh/id_ed25519", ".git/config"])
def test_secret_paths_are_not_published(path):
    with pytest.raises(HereNowError, match="must not be published"):
        validate_path(path, writing=True)


def test_well_known_file_is_not_blanket_banned():
    assert validate_path(".well-known/security.txt", writing=True)


def test_duplicate_change_and_size_are_rejected_before_prepare(rig):
    fake, _, updater = rig
    with pytest.raises(HereNowError, match="twice"):
        updater.update(fake.slug, "v1", [TextChange("index.html", "a"), TextChange("index.html", "b")])
    updater.max_change_bytes = 3
    with pytest.raises(HereNowError, match="limit"):
        updater.update(fake.slug, "v1", [TextChange("index.html", "long")])
    assert fake.prepare_count == 0


def test_no_key_or_redirect_forwarding():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://not-allowed.example"})
    client = ProviderHTTP("test-key", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(HereNowError) as caught:
            client.json("GET", "/api/v1/publishes")
        assert len(requests) == 1
        assert "test-key" not in str(caught.value)
    finally:
        client.close()


def test_429_reports_retry_after_without_retrying():
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(429, headers={"Retry-After": "15"}, json={"message": "secret"})
    client = ProviderHTTP("test-key", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(HereNowError, match="15 seconds") as caught:
            client.json("GET", "/api/v1/publishes")
        assert "secret" not in str(caught.value) and count == 1
    finally:
        client.close()


@pytest.mark.parametrize("url", ["http://bucket.r2.cloudflarestorage.com/a", "https://evil.example/a", "https://bucket.r2.cloudflarestorage.com.evil.example/a"])
def test_unexpected_upload_origin_has_no_request(rig, url):
    fake, reader, _ = rig
    with pytest.raises(HereNowError):
        reader.http.upload({"url": url, "method": "PUT", "headers": {}}, b"a")
    assert fake.requests == []


def test_credentials_env_and_owner_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HERENOW_API_KEY", "test-key")
    assert load_api_key() == "test-key"
    monkeypatch.delenv("HERENOW_API_KEY")
    path = tmp_path / "credentials"
    path.write_text("test-key\n")
    path.chmod(0o600)
    monkeypatch.setenv("HERENOW_CREDENTIALS_FILE", str(path))
    assert load_api_key() == "test-key"
    path.chmod(0o644)
    with pytest.raises(HereNowError, match="owner-only"):
        load_api_key()
