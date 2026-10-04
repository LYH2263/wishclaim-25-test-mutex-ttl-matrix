"""互斥与到期矩阵测例：引擎判定 + HTTP 行为 + 墙卡//mine 口径三层核对。

每行流程：造数(落库) → 拨钟 → 先调 claim_lock 引擎核对判定 → 再打 HTTP
核对状态码 → 最后读墙卡 /api/wishes 与 /api/mine，核对 status、claimer、
mine 长度与墙认领人口径一致。

拍板记录（恰好相等边界）：拨钟时刻 == expires_at 时，引擎以
`parse_ts(expires_at) <= now` 判定，锁视为【已过期】，第三人 claim
【成功，返回 200】而非 409。该结论固化在 exact_expiry_boundary 行的
期望列中，改动引擎比较符会让本行失败。
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, seed
from app.engines.claim_lock import claim_allowed
from app.tests import clockkit
from app.tests.clockkit import T0, iso

TTL = 3600            # 矩阵统一锁定时长（秒）
EXP = T0 + timedelta(seconds=TTL)  # 统一到期时刻


def locked_wish(claimer):
    """造数：claimer 在 T0 时刻认领、EXP 时刻到期的愿望。"""
    return {
        "title": f"矩阵愿望-{claimer}",
        "status": "claimed",
        "claimer": claimer,
        "claimed_at": iso(T0),
        "expires_at": iso(EXP),
    }


# 步骤指令：("shift", 秒) 拨钟偏移 | ("shift_to", 时刻) 拨到定点 |
# ("engine", ok, reason) 引擎判定核对 | ("claim", 认领人, HTTP状态码) |
# ("release", HTTP状态码) | ("fulfill", HTTP状态码)
ROWS = [
    {
        "key": "double_claim_one_winner",
        "wish": {"title": "双人抢单", "status": "open"},
        "steps": [
            ("engine", True, ""),
            ("claim", "alice", 200),
            ("engine", False, "locked"),
            ("claim", "bob", 409),
        ],
        "expect": {"wall_status": "claimed", "wall_claimer": "alice",
                   "mine": {"alice": 1, "bob": 0}},
    },
    {
        "key": "second_claim_during_lock_409",
        "wish": locked_wish("alice"),
        "steps": [
            ("shift", 600),
            ("engine", False, "locked"),
            ("claim", "bob", 409),
        ],
        "expect": {"wall_status": "claimed", "wall_claimer": "alice",
                   "mine": {"alice": 1, "bob": 0}},
    },
    {
        "key": "reclaim_after_expiry",
        "wish": locked_wish("alice"),
        "steps": [
            ("shift", TTL + 1),
            ("engine", True, "ttl_expired_reclaim"),
            ("claim", "carol", 200),
        ],
        "expect": {"wall_status": "claimed", "wall_claimer": "carol",
                   "mine": {"alice": 0, "carol": 1}},
    },
    {
        "key": "release_then_reclaim",
        "wish": locked_wish("alice"),
        "steps": [
            ("shift", 100),
            ("release", 200),
            ("engine", True, ""),
            ("claim", "bob", 200),
        ],
        "expect": {"wall_status": "claimed", "wall_claimer": "bob",
                   "mine": {"alice": 0, "bob": 1}},
    },
    {
        # 拍板：恰好等于 expires_at ⇒ 锁已过期，claim 成功（200），非 409。
        "key": "exact_expiry_boundary",
        "wish": locked_wish("alice"),
        "steps": [
            ("shift_to", EXP),
            ("engine", True, "ttl_expired_reclaim"),
            ("claim", "bob", 200),
        ],
        "expect": {"wall_status": "claimed", "wall_claimer": "bob",
                   "mine": {"alice": 0, "bob": 1}},
    },
    {
        "key": "fulfilled_blocks_new_claim",
        "wish": locked_wish("alice"),
        "steps": [
            ("shift", 100),
            ("fulfill", 200),
            ("engine", False, "already_fulfilled"),
            ("claim", "bob", 409),
        ],
        "expect": {"wall_status": "fulfilled", "wall_claimer": "alice",
                   "mine": {"alice": 1, "bob": 0}},
    },
]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """每行一套独立环境：临时 DATA_DIR、干净种子库、拨到 T0 的时钟、TTL=3600。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seed.init_db()
    clock = clockkit.Clock(T0)
    clockkit.patch_app_clock(monkeypatch, clock)
    clockkit.set_ttl(TTL)
    with TestClient(main.app) as client:
        yield SimpleNamespace(clock=clock, client=client)


def check(row, cond, msg):
    if not cond:
        raise AssertionError(f"[行 {row['key']}] {msg}")


def run_step(env, row, wid, step):
    op = step[0]
    if op == "shift":
        env.clock.advance(step[1])
    elif op == "shift_to":
        env.clock.set_to(step[1])
    elif op == "engine":
        _, ok, reason = step
        w = clockkit.read_wish(wid)
        r = claim_allowed(w["status"], w["claimer"], env.clock.now, w["expires_at"])
        check(row, r["ok"] is ok and r["reason"] == reason,
              f"引擎判定期望 ok={ok},reason={reason!r}，实得 {r}")
    elif op == "claim":
        _, claimer, status = step
        resp = env.client.post(f"/api/wishes/{wid}/claim", json={"claimer": claimer})
        check(row, resp.status_code == status,
              f"POST claim({claimer}) 期望 HTTP {status}，实得 {resp.status_code} body={resp.text}")
    elif op in ("release", "fulfill"):
        _, status = step
        resp = env.client.post(f"/api/wishes/{wid}/{op}")
        check(row, resp.status_code == status,
              f"POST {op} 期望 HTTP {status}，实得 {resp.status_code} body={resp.text}")
    else:
        raise AssertionError(f"[行 {row['key']}] 未知步骤 {op!r}")


def verify_wall_and_mine(env, row, wid):
    exp = row["expect"]
    cards = {w["id"]: w for w in env.client.get("/api/wishes").json()}
    check(row, wid in cards, "墙卡中找不到该愿望")
    card = cards[wid]
    check(row, card["status"] == exp["wall_status"],
          f"墙卡 status 期望 {exp['wall_status']}，实得 {card['status']}")
    check(row, card["claimer"] == exp["wall_claimer"],
          f"墙卡 claimer 期望 {exp['wall_claimer']}，实得 {card['claimer']}")
    for person, count in exp["mine"].items():
        mine = env.client.get("/api/mine", params={"claimer": person}).json()
        check(row, len(mine) == count,
              f"/api/mine?claimer={person} 长度期望 {count}，实得 {len(mine)}")
        in_mine = any(m["id"] == wid for m in mine)
        should_hold = person == exp["wall_claimer"]
        check(row, in_mine == should_hold,
              f"墙认领人口径不一致：{person} 的 mine 含该愿望={in_mine}，期望={should_hold}")


@pytest.mark.parametrize("row", ROWS, ids=[r["key"] for r in ROWS])
def test_claim_mutex_expiry_matrix(env, row):
    try:
        wid = clockkit.make_wish(**row["wish"])
        for step in row["steps"]:
            run_step(env, row, wid, step)
        verify_wall_and_mine(env, row, wid)
    except Exception:
        print(f"\n[矩阵行失败] key={row['key']}")
        raise
