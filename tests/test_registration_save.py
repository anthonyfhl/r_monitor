"""Commit boundaries, retry receipts and independent family writer locks."""
import copy
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import esaver
from src.state import read_json, write_json, file_lock, RECOVERY_EVENTS


@pytest.fixture
def files(tmp_path, monkeypatch):
    RECOVERY_EVENTS.clear()
    monkeypatch.setattr(esaver, "DATA_DIR", tmp_path)
    monkeypatch.setattr(esaver, "PROMOTIONS_FILE", tmp_path / "promotions.json")
    monkeypatch.setattr(esaver, "REGISTRATIONS_FILE", tmp_path / "records.json")
    write_json(esaver.PROMOTIONS_FILE, {"promotions": [{"id": "2026-09"}]})
    write_json(esaver.REGISTRATIONS_FILE, {"members": ["Mum"], "registrations": {}, "version": 0})
    return tmp_path / "app"


def event(token="request-12345", member="Mum"):
    return {"kind": "esaver_registration", "utc": "2026-10-02T00:00:00Z", "email": "owner@example.test",
            "payload": {"event_id": token, "promo_id": "2026-09", "member": member,
                        "status": "registered", "registered_on": None}}


def test_success_means_both_files_are_committed_and_daily_network_lock_is_irrelevant(files):
    with file_lock(esaver.DATA_DIR / "monitor.lock"):
        result = esaver.save_registration(event(), files)
    assert result["ok"] and result["committed"]
    assert read_json(esaver.REGISTRATIONS_FILE)["version"] == 1
    assert read_json(files / "registrations.json") == result["registrations"]
    assert result["registrations"]["registrations"]["2026-09|Mum"]["event_id"] == "request-12345"


def test_lost_reply_retry_is_idempotent_even_after_later_edit(files):
    esaver.save_registration(event(), files)  # imagine the HTTP reply was lost
    changed = event("request-67890")
    changed["payload"]["status"] = "not_registered"
    esaver.save_registration(changed, files)
    retry = esaver.save_registration(event(), files)
    assert retry["registrations"]["version"] == 2
    assert retry["registrations"]["registrations"]["2026-09|Mum"]["status"] == "not_registered"


def test_reusing_token_for_different_data_is_rejected_without_writing(files):
    esaver.save_registration(event(), files)
    before = esaver.REGISTRATIONS_FILE.read_bytes()
    changed = event()
    changed["payload"]["status"] = "not_registered"
    with pytest.raises(ValueError, match="different data"):
        esaver.save_registration(changed, files)
    assert esaver.REGISTRATIONS_FILE.read_bytes() == before


def test_crash_before_canonical_write_never_acknowledges(files, monkeypatch):
    original = esaver.write_json
    def fail(path, value):
        if path == esaver.REGISTRATIONS_FILE:
            raise OSError("simulated write failure")
        original(path, value)
    monkeypatch.setattr(esaver, "write_json", fail)
    with pytest.raises(OSError):
        esaver.save_registration(event(), files)
    assert read_json(esaver.REGISTRATIONS_FILE)["version"] == 0


def test_crash_after_commit_repaired_on_same_submission_without_duplicate(files, monkeypatch):
    original = esaver.write_json
    def fail_view(path, value):
        if path == files / "registrations.json":
            raise OSError("simulated publish failure")
        original(path, value)
    monkeypatch.setattr(esaver, "write_json", fail_view)
    with pytest.raises(OSError):
        esaver.save_registration(event(), files)
    assert read_json(esaver.REGISTRATIONS_FILE)["version"] == 1
    monkeypatch.setattr(esaver, "write_json", original)
    assert esaver.save_registration(event(), files)["registrations"]["version"] == 1


def test_transient_derived_write_failure_gets_immediate_repair(files, monkeypatch):
    original = esaver.write_json
    attempts = []
    def once(path, value):
        if path == files / "registrations.json":
            attempts.append(path)
            if len(attempts) == 1:
                raise OSError("temporary local failure")
        original(path, value)
    monkeypatch.setattr(esaver, "write_json", once)
    assert esaver.save_registration(event(), files)["committed"]
    assert len(attempts) == 2


def test_two_simultaneous_family_writes_preserve_both(files):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda e: esaver.save_registration(e, files),
                                    [event(), event("request-other", "Fong")]))
    records = read_json(esaver.REGISTRATIONS_FILE)
    assert records["version"] == 2 and len(records["registrations"]) == 2
    assert all(r["committed"] for r in results)


def test_invalid_schema_is_preserved_and_verified_backup_repaired_visibly(files):
    write_json(esaver.REGISTRATIONS_FILE, {"members": ["Mum"], "registrations": {}, "version": 0})
    esaver.REGISTRATIONS_FILE.write_text('{"members":null}', encoding="utf-8")
    result = esaver.save_registration(event(), files)
    assert result["committed"] and result["registrations"]["sync_errors"]
    assert list((esaver.DATA_DIR / "quarantine").glob("*.broken"))


def test_missing_file_without_backup_fails_loud_never_creates_empty_state(files):
    esaver.REGISTRATIONS_FILE.unlink()
    with pytest.raises(RuntimeError, match="no verified backup"):
        esaver.save_registration(event(), files)
    assert not esaver.REGISTRATIONS_FILE.exists()


@pytest.mark.parametrize("change", [{"promo_id": "unknown"}, {"member": "A|B"},
                                   {"status": "anything"}, {"registered_on": "2099-01-01"}])
def test_invalid_input_preserves_canonical_file(files, change):
    before = esaver.REGISTRATIONS_FILE.read_bytes()
    bad = copy.deepcopy(event())
    bad["payload"].update(change)
    with pytest.raises(ValueError):
        esaver.save_registration(bad, files)
    assert esaver.REGISTRATIONS_FILE.read_bytes() == before
