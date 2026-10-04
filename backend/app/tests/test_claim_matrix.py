"""互斥与到期矩阵测例包。

每行：先调 claim_lock 引擎探针，再打 HTTP，再读墙卡与 /api/mine，
核对 status、claimer、mine 长度与墙认领人口径一致。

拍板记录（boundary_now_eq_expires_at 行）：拨钟时刻恰好等于 expires_at 时，
引擎以 `parse_ts(expires_at) <= now` 判定，含端点、视为锁已过期，
第三人此刻 claim 成功（HTTP 200），不是 409。该决定已写入该行期望列。
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tests.clock_data_kit import T0, TTL_SECONDS, FakeClock, Kit, run_row

ROWS = [
    {
        "key": "dual_claim_exactly_one_wins",
        "note": "同 wish 双 claim 恰一胜：先到者得锁，后到者 409",
        "probes": [
            {"fn": "claim_allowed", "args": ["open", None, "$NOW", None],
             "expect": {"ok": True, "reason": ""}},
        ],
        "ops": [
            ("claim", "alice", 200),
            ("claim", "bob", 409, "locked"),
        ],
        "expect": {"status": "claimed", "claimer": "alice",
                   "mine": {"alice": 1, "bob": 0}},
    },
    {
        "key": "locked_second_claim_409",
        "note": "锁定期内二次 claim 返回 409（reason=locked），锁主与墙卡不变",
        "probes": [
            {"fn": "claim_allowed", "args": ["claimed", "alice", "$NOW", "$FUTURE"],
             "expect": {"ok": False, "reason": "locked"}},
        ],
        "ops": [
            ("claim", "alice", 200),
            ("claim", "bob", 409, "locked"),
        ],
        "expect": {"status": "claimed", "claimer": "alice",
                   "mine": {"alice": 1, "bob": 0}},
    },
    {
        "key": "ttl_expired_third_claimer_wins",
        "note": "拨钟越过 expires_at 后旧锁自动释放，第三人 claim 成功",
        "probes": [
            {"fn": "claim_allowed", "args": ["claimed", "alice", "$NOW", "$PAST"],
             "expect": {"ok": True, "reason": "ttl_expired_reclaim"}},
            {"fn": "release_if_expired", "args": ["claimed", "$PAST", "$NOW"],
             "expect": {"status": "open", "claimer": None, "claimed_at": None, "expires_at": None}},
        ],
        "ops": [
            ("claim", "alice", 200),
            ("advance", TTL_SECONDS + 1),
            ("claim", "carol", 200),
        ],
        "expect": {"status": "claimed", "claimer": "carol",
                   "mine": {"alice": 0, "carol": 1}},
    },
    {
        "key": "release_then_reclaim",
        "note": "release 后愿望回到可认领态，他人再 claim 成功",
        "probes": [
            {"fn": "claim_allowed", "args": ["released", None, "$NOW", None],
             "expect": {"ok": True, "reason": ""}},
        ],
        "ops": [
            ("claim", "alice", 200),
            ("release", 200),
            ("claim", "bob", 200),
        ],
        "expect": {"status": "claimed", "claimer": "bob",
                   "mine": {"alice": 0, "bob": 1}},
    },
    {
        "key": "boundary_now_eq_expires_at",
        "note": "拍板：拨钟时刻恰好等于 expires_at 视为已过期（引擎 <= 含端点），第三人 claim 成功 200",
        "probes": [
            {"fn": "claim_allowed", "args": ["claimed", "alice", "$NOW", "$EQ"],
             "expect": {"ok": True, "reason": "ttl_expired_reclaim"}},
            {"fn": "release_if_expired", "args": ["claimed", "$EQ", "$NOW"],
             "expect": {"status": "open", "claimer": None, "claimed_at": None, "expires_at": None}},
        ],
        "ops": [
            ("claim", "alice", 200),
            ("sync_to_expires",),
            ("claim", "bob", 200),
        ],
        "expect": {"status": "claimed", "claimer": "bob",
                   "mine": {"alice": 0, "bob": 1}},
    },
    {
        "key": "fulfilled_blocks_claim",
        "note": "已核销愿望不可再认领，返回 409（reason=already_fulfilled）",
        "probes": [
            {"fn": "claim_allowed", "args": ["fulfilled", "alice", "$NOW", "$FUTURE"],
             "expect": {"ok": False, "reason": "already_fulfilled"}},
        ],
        "ops": [
            ("claim", "alice", 200),
            ("fulfill", 200),
            ("claim", "bob", 409, "already_fulfilled"),
        ],
        "expect": {"status": "fulfilled", "claimer": "alice",
                   "mine": {"alice": 1, "bob": 0}},
    },
]


@pytest.fixture()
def kit(tmp_path, monkeypatch):
    """每行一个隔离实例：独立 DATA_DIR + 拨到 T0 的假钟。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    clock = FakeClock(T0)
    monkeypatch.setattr("app.main.now", clock.now)
    with TestClient(app) as client:
        yield Kit(client, clock)


@pytest.mark.parametrize("row", ROWS, ids=[r["key"] for r in ROWS])
def test_claim_mutex_expiry_matrix(kit, row):
    try:
        run_row(kit, row)
    except Exception:
        print(f"矩阵行失败: {row['key']}")
        raise
