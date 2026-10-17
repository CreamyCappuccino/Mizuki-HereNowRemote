"""Targeted deletion leaves unrelated Site paths intact, using provider version checks."""
import pytest

from here_now_remote.site_models import HereNowError, digest


def test_delete_single_file_preserves_other_files(rig):
    fake, reader, updater = rig
    old_index_hash = digest(fake.bodies["index.html"])
    result = updater.delete_files(fake.slug, "v1", ["assets/style.css"])
    assert result.status == "published"
    assert result.changed_paths == ("assets/style.css",)
    assert result.changed_hashes == {}
    assert result.uploaded == 0 and result.skipped == 1
    assert fake.prepare_count == 1 and fake.finalize_count == 1
    snapshot = reader.get_site(fake.slug)
    assert set(snapshot.by_path) == {"index.html"}
    assert snapshot.by_path["index.html"].sha256 == old_index_hash
    assert snapshot.version == "v2"
    with pytest.raises(HereNowError) as error:
        reader.read_file(fake.slug, "assets/style.css")
    assert error.value.code == "not_found"


@pytest.mark.parametrize("paths,code", [
    ([], "empty_deletion"),
    (["assets/style.css", "assets/style.css"], "duplicate_path"),
    (["missing-file.txt"], "not_found"),
    (["../index.html"], "invalid_path"),
    (["index.html", "assets/style.css"], "empty_site"),
])
def test_delete_rejects_invalid_requests_without_a_write(rig, paths, code):
    fake, reader, updater = rig
    with pytest.raises(HereNowError) as info:
        updater.delete_files(fake.slug, "v1", paths)
    assert info.value.code == code
    assert fake.prepare_count == 0
    assert fake.finalize_count == 0


def test_delete_rejects_stale_base(rig):
    fake, reader, updater = rig
    with pytest.raises(HereNowError) as info:
        updater.delete_files(fake.slug, "not-current", ["assets/style.css"])
    assert info.value.code == "version_conflict"
    assert fake.prepare_count == 0


def test_delete_reuploads_legacy_unchanged_file_when_required(rig):
    fake, reader, updater = rig
    fake.force_upload_all = True
    receipt = updater.delete_files(fake.slug, "v1", ["assets/style.css"])
    assert receipt.status == "published"
    assert receipt.uploaded == 1
    assert set(reader.get_site(fake.slug).by_path) == {"index.html"}