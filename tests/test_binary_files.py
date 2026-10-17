"""Binary encoding is opt-in; old UTF-8 calls remain unchanged."""
import base64

import pytest

from here_now_remote.site_models import HereNowError, TextChange, digest
from here_now_remote.tool_output import file_text

PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x01\x02\xff\x00"


def test_png_update_readback_and_legacy_html_preserved(rig):
    fake, reader, updater = rig
    body = base64.b64encode(PNG_BYTES).decode("ascii")
    original_html = digest(fake.bodies["index.html"])
    receipt = updater.update(fake.slug, "v1", [TextChange("assets/pic.png", body, encoding="base64")])
    assert receipt.status == "published" and receipt.uploaded == 1
    entry = reader.get_site(fake.slug).by_path["assets/pic.png"]
    assert (entry.content_type, entry.size, entry.sha256) == ("image/png", len(PNG_BYTES), digest(PNG_BYTES))
    assert reader.get_site(fake.slug).by_path["index.html"].sha256 == original_html
    assert fake.uploads["assets/pic.png"] == PNG_BYTES
    assert not any("authorization" in req.headers for req in fake.requests
                   if req.url.host.endswith(".r2.cloudflarestorage.com"))
    prior_calls = len(fake.requests)
    metadata = reader.read_file(fake.slug, "assets/pic.png")
    assert metadata["content"] is None and metadata["file"].size == len(PNG_BYTES)
    assert not any("/files/" in req.url.path for req in fake.requests[prior_calls:])
    decoded = reader.read_file(fake.slug, "assets/pic.png", binary_mode="base64")
    assert decoded["content"] == body and decoded["encoding"] == "base64"
    assert "binary content (base64" in file_text(decoded)


def test_existing_utf8_format_is_unchanged(rig):
    _, reader, updater = rig
    assert updater.update("test-site", "v1",
                          [TextChange("index.html", "<h1>日本語</h1>")]).status == "published"
    result = reader.read_file("test-site", "index.html")
    assert result["content"] == "<h1>日本語</h1>" and result["encoding"] == "utf-8"
    assert "--- file content (data" in file_text(result)


def test_explicit_binary_mime_supported(rig):
    _, reader, updater = rig
    encoded = base64.b64encode(PNG_BYTES).decode()
    receipt = updater.update("test-site", "v1", [
        TextChange("assets/unknown.data", encoded, "application/octet-stream", "base64")])
    assert receipt.status == "published"
    assert reader.get_site("test-site").by_path["assets/unknown.data"].content_type == "application/octet-stream"


@pytest.mark.parametrize("bad", ["abc", "a?==", "ab c", "YQ", "YR==", "YQ==="])
def test_invalid_base64_never_writes(rig, bad):
    fake, _, updater = rig
    with pytest.raises(HereNowError) as error:
        updater.update(fake.slug, "v1", [TextChange("pic.png", bad, encoding="base64")])
    assert error.value.code == "invalid_base64"
    assert fake.prepare_count == 0


def test_empty_base64_file_supported(rig):
    _, _, updater = rig
    assert updater.update("test-site", "v1", [
        TextChange("empty.bin", "", encoding="base64")]).status == "published"


def test_binary_encoding_validation_and_size(rig):
    fake, _, updater = rig
    for change, expected in [
        (TextChange("image.png", "x", encoding="utf-8"), "not_text"),
        (TextChange("image.png", "YQ==", encoding="hex"), "invalid_encoding"),
    ]:
        with pytest.raises(HereNowError) as error:
            updater.update(fake.slug, "v1", [change])
        assert error.value.code == expected
    updater.max_change_bytes = 4
    with pytest.raises(HereNowError) as error:
        updater.update(fake.slug, "v1", [
            TextChange("large.png", base64.b64encode(b"abcdef").decode(), encoding="base64")])
    assert error.value.code == "too_large"
    assert fake.prepare_count == 0


def test_large_binary_read_is_metadata_only(rig):
    fake, reader, _ = rig
    blob = b"x" * (256 * 1024 + 1)
    fake.bodies["large.png"] = blob
    fake.manifest.append({"path": "large.png", "size": len(blob),
                          "contentType": "image/png", "hash": digest(blob)})
    assert reader.read_file(fake.slug, "large.png")["content"] is None
    with pytest.raises(HereNowError) as error:
        reader.read_file(fake.slug, "large.png", binary_mode="base64")
    assert error.value.code == "too_large"


def test_invalid_read_mode_rejected(rig):
    _, reader, _ = rig
    with pytest.raises(HereNowError) as error:
        reader.read_file("test-site", "index.html", binary_mode="raw")
    assert error.value.code == "invalid_binary_mode"
