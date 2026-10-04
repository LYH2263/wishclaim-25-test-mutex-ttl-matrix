"""拨钟造数助手模块：互斥/到期矩阵测例的可控时钟、造数工具与行执行器。

- FakeClock：可控时钟。测试夹具用它 monkeypatch 掉 app.main.now，
  advance()/set_to() 即“拨钟”。
- Kit：造数与读数封装（建愿望、claim、release、fulfill、读墙卡、读 /api/mine）。
- run_row：矩阵行执行器——先调 claim_lock 引擎探针，再打 HTTP，
  最后读墙卡与 /api/mine，核对 status、claimer、mine 长度与墙认领人口径一致。
- check：断言失败时打印所在表格行键名。
"""
from datetime import datetime, timedelta, timezone

from app.engines.claim_lock import claim_allowed, parse_ts, release_if_expired

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
TTL_SECONDS = 86400  # 与 seed 写入的 ttl_seconds 一致

ENGINE_FNS = {"claim_allowed": claim_allowed, "release_if_expired": release_if_expired}


class FakeClock:
    """被测服务的时间来源；测试通过替换 app.main.now 注入。"""

    def __init__(self, start):
        self._t = start

    def now(self):
        return self._t

    def advance(self, seconds):
        self._t = self._t + timedelta(seconds=seconds)
        return self._t

    def set_to(self, dt):
        self._t = dt
        return self._t


class Kit:
    """面向单个隔离实例（独立 DATA_DIR）的造数/读数封装。断言一律交给执行器。"""

    def __init__(self, client, clock):
        self.client = client
        self.clock = clock

    def create_wish(self, title):
        return self.client.post("/api/wishes", json={"title": title})

    def claim(self, wid, who):
        return self.client.post(f"/api/wishes/{wid}/claim", json={"claimer": who})

    def release(self, wid):
        return self.client.post(f"/api/wishes/{wid}/release")

    def fulfill(self, wid):
        return self.client.post(f"/api/wishes/{wid}/fulfill")

    def wall_card(self, wid):
        for card in self.client.get("/api/wishes").json():
            if card["id"] == wid:
                return card
        return None

    def mine(self, who):
        return self.client.get("/api/mine", params={"claimer": who}).json()


def check(key, label, ok, got=None, want=None):
    """行内断言：失败时打印表格键名再抛出。"""
    if not ok:
        msg = f"[行 {key}] {label}: got={got!r} want={want!r}"
        print(msg)
        raise AssertionError(msg)


def _resolve(arg, clock):
    """解析探针参数里的时钟占位符。"""
    if not isinstance(arg, str):
        return arg
    now = clock.now()
    placeholders = {
        "$NOW": now,
        "$FUTURE": (now + timedelta(seconds=TTL_SECONDS)).isoformat(),
        "$PAST": (now - timedelta(seconds=1)).isoformat(),
        "$EQ": now.isoformat(),
    }
    return placeholders.get(arg, arg)


def run_probe(kit, key, probe):
    fn = ENGINE_FNS[probe["fn"]]
    args = [_resolve(a, kit.clock) for a in probe["args"]]
    got = fn(*args)
    check(key, f"engine.{probe['fn']}{probe['args']}", got == probe["expect"], got, probe["expect"])


def run_op(kit, key, ctx, op):
    name = op[0]
    if name == "claim":
        who, want_status = op[1], op[2]
        r = kit.claim(ctx["wid"], who)
        check(key, f"http.claim({who}).status", r.status_code == want_status, r.status_code, want_status)
        if r.status_code == 200:
            ctx["last_claim"] = r.json()
        if len(op) > 3:
            got = r.json().get("detail")
            check(key, f"http.claim({who}).detail", got == op[3], got, op[3])
    elif name in ("release", "fulfill"):
        r = getattr(kit, name)(ctx["wid"])
        check(key, f"http.{name}.status", r.status_code == op[1], r.status_code, op[1])
    elif name == "advance":
        kit.clock.advance(op[1])
    elif name == "sync_to_expires":
        last = ctx["last_claim"]
        check(key, "sync_to_expires.has_claim", last is not None, last, "非空认领回包")
        kit.clock.set_to(parse_ts(last["expires_at"]))
    else:
        raise ValueError(f"[行 {key}] 未知操作: {op!r}")


def run_row(kit, row):
    """执行一行矩阵：先引擎探针，再 HTTP 脚本，最后墙卡 + /api/mine 口径核对。"""
    key = row["key"]
    r = kit.create_wish(f"矩阵-{key}")
    check(key, "setup.create_wish", r.status_code == 200, r.status_code, 200)
    ctx = {"wid": r.json()["id"], "last_claim": None}

    # 1) 先调 claim_lock 引擎探针
    for probe in row.get("probes", []):
        run_probe(kit, key, probe)

    # 2) 再打 HTTP
    for op in row["ops"]:
        run_op(kit, key, ctx, op)

    # 3) 读墙卡与 /api/mine，核对 status、claimer、mine 长度与墙认领人口径
    exp = row["expect"]
    card = kit.wall_card(ctx["wid"])
    check(key, "wall.card_exists", card is not None, card, "墙上有卡")
    check(key, "wall.status", card["status"] == exp["status"], card["status"], exp["status"])
    check(key, "wall.claimer", card["claimer"] == exp["claimer"], card["claimer"], exp["claimer"])
    for who, want_len in exp["mine"].items():
        got_len = len(kit.mine(who))
        check(key, f"mine.len[{who}]", got_len == want_len, got_len, want_len)

    claimer = card["claimer"]
    if claimer is None:
        for who in exp["mine"]:
            ids = [w["id"] for w in kit.mine(who)]
            check(key, f"consistency.no_holder[{who}]", ctx["wid"] not in ids, ids, "不含本愿望")
    else:
        mine_rows = kit.mine(claimer)
        ids = [w["id"] for w in mine_rows]
        check(key, "consistency.holder_has_wish", ctx["wid"] in ids, ids, "含本愿望")
        bad = [w["id"] for w in mine_rows if w["claimer"] != claimer]
        check(key, "consistency.claimer_matches_wall", not bad, bad, "mine 认领人与墙卡一致")
