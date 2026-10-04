from datetime import datetime, timedelta, timezone
from app.engines.claim_lock import claim_allowed, lock_payload, release_if_expired

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

def test_mutex_blocks_second_claimer():
    r = claim_allowed("claimed", "alice", NOW, (NOW + timedelta(hours=1)).isoformat())
    assert r["ok"] is False and r["reason"] == "locked"

def test_ttl_allows_reclaim():
    r = claim_allowed("claimed", "alice", NOW, (NOW - timedelta(minutes=1)).isoformat())
    assert r["ok"] is True

def test_lock_payload_sets_expiry():
    p = lock_payload("bob", NOW, 3600)
    assert p["status"] == "claimed" and p["claimer"] == "bob"
    assert release_if_expired("claimed", p["expires_at"], NOW) is None
    assert release_if_expired("claimed", (NOW - timedelta(seconds=1)).isoformat(), NOW)["status"] == "open"
