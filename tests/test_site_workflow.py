from concurrent.futures import ThreadPoolExecutor

import pytest

from here_now_remote.site_models import HereNowError, TextChange
from here_now_remote.tool_output import file_text, receipt_text


def change():
    return [TextChange("assets/style.css", "h1 { font-size: 42px; }")]


def test_list_and_read_with_snapshot(rig):
    fake, reader, _ = rig
    assert reader.list_sites()[0]["slug"] == fake.slug
    result = reader.read_file(fake.slug, "index.html", "v1")
    assert result["content"] == "<h1>Hello</h1>"
    assert "version v1" in file_text(result)
    assert fake.prepare_count == 0


def test_partial_update_preserves_other_files_url_and_mime(rig):
    fake, reader, updater = rig
    before = reader.get_site(fake.slug)
    result = updater.update(fake.slug, "v1", change())
    after = reader.get_site(fake.slug)
    assert result.status == "published"
    assert result.url == before.url == after.url
    assert before.by_path["index.html"] == after.by_path["index.html"]
    assert after.by_path["assets/style.css"].content_type == "text/css"
    assert result.uploaded == 1 and result.skipped == 1
    assert fake.finalize_count == 1
    assert not any(r.url.host == "test-site.here.now" for r in fake.requests)  # No untouched bytes downloaded.
    assert "secret" not in receipt_text(result)


def test_unchanged_does_not_prepare(rig):
    fake, _, updater = rig
    result = updater.update(fake.slug, "v1", [TextChange("index.html", fake.bodies["index.html"].decode())])
    assert result.status == "unchanged" and fake.prepare_count == 0


def test_stale_base_has_no_mutation(rig):
    fake, _, updater = rig
    with pytest.raises(HereNowError, match="Current version"):
        updater.update(fake.slug, "old", change())
    assert fake.prepare_count == 0


def test_change_after_prepare_stops_before_finalize(rig):
    fake, _, updater = rig
    fake.after_prepare_change = True
    result = updater.update(fake.slug, "v1", change())
    assert result.status == "not_published"
    assert "version_conflict" in result.message
    assert fake.finalize_count == 0


def test_finalize_timeout_reconciles_without_duplicate_publish(rig):
    fake, _, updater = rig
    fake.finalize_timeout = True
    result = updater.update(fake.slug, "v1", change())
    assert result.status == "published"
    assert "Recovered by readback" in result.message
    assert fake.prepare_count == fake.finalize_count == 1


def test_failed_readback_is_unknown_not_false_success(rig):
    fake, _, updater = rig
    fake.finalize_readback_error = True
    result = updater.update(fake.slug, "v1", change())
    assert result.status == "outcome_unknown"
    assert result.target_version == "v2" and result.current_version is None
    assert result.changed_hashes["assets/style.css"]
    assert fake.finalize_count == 1


def test_upload_failure_keeps_current_site(rig):
    fake, _, updater = rig
    fake.upload_failure = True
    result = updater.update(fake.slug, "v1", change())
    assert result.status == "not_published" and "http_503" in result.message
    assert fake.version == "v1" and fake.finalize_count == 0


def test_invalid_upload_plan_never_finalizes(rig):
    fake, _, updater = rig
    fake.bad_targets = True
    result = updater.update(fake.slug, "v1", change())
    assert result.status == "not_published" and fake.finalize_count == 0


def test_provider_can_request_unchanged_bytes(rig):
    fake, _, updater = rig
    fake.force_upload_all = True
    result = updater.update(fake.slug, "v1", change())
    assert result.status == "published" and result.uploaded == 2
    assert fake.bodies["index.html"] == b"<h1>Hello</h1>"


def test_read_drift_is_rejected(rig):
    fake, reader, _ = rig
    fake.read_drift = True
    with pytest.raises(HereNowError, match="changed during"):
        reader.read_file(fake.slug, "index.html")


def test_incorrect_public_bytes_are_not_returned(rig):
    fake, reader, _ = rig
    fake.corrupt_read = True
    with pytest.raises(HereNowError, match="Public bytes differ"):
        reader.read_file(fake.slug, "index.html")


def test_same_process_simultaneous_edits_do_not_silently_overwrite(rig):
    fake, _, updater = rig
    def update(_):
        try:
            return updater.update(fake.slug, "v1", change()).status
        except HereNowError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(update, range(2)))
    assert sorted(outcomes) == ["published", "version_conflict"]
    assert fake.prepare_count == 1


def test_multiple_files_and_utf8_byte_sizes(rig):
    fake, reader, updater = rig
    result = updater.update(fake.slug, "v1", change() + [TextChange("index.html", "<h1>潮さん</h1>")])
    assert result.status == "published" and result.uploaded == 2
    entry = reader.get_site(fake.slug).by_path["index.html"]
    assert entry.size == len("<h1>潮さん</h1>".encode())
