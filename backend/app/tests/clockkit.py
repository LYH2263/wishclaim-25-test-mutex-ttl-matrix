"""拨钟造数助手：互斥/到期矩阵测例共用的测试工具模块。

- Clock: 可控时钟，经 patch_app_clock 替换 app.main.now，实现"拨钟"，
  使 HTTP 层（claim/sweep/mine）全部按测试时刻判定 TTL。
- make_wish / read_wish / set_ttl: 直接落库造数，绕过 HTTP 层构造
  任意 status/claimer/expires_at 组合的愿望与设置。
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db import connect

# 矩阵基准时刻：所有行的拨钟偏移都相对它计算。
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


@dataclass
class Clock:
    now: datetime

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def set_to(self, t: datetime) -> None:
        self.now = t


def patch_app_clock(monkeypatch, clock: Clock) -> None:
    """把 app.main.now 拨到测试时钟；endpoint 内是运行时全局查找，替换即生效。"""
    from app import main

    monkeypatch.setattr(main, "now", lambda: clock.now)


def make_wish(title, status="open", claimer=None, claimed_at=None,
              expires_at=None, note="", quality="clean") -> int:
    c = connect()
    cur = c.execute(
        "INSERT INTO wishes(title,note,status,claimer,claimed_at,expires_at,data_quality)"
        " VALUES (?,?,?,?,?,?,?)",
        (title, note, status, claimer, claimed_at, expires_at, quality),
    )
    c.commit()
    wid = cur.lastrowid
    c.close()
    return wid


def read_wish(wid: int) -> dict | None:
    c = connect()
    r = c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
    c.close()
    return dict(r) if r else None


def set_ttl(seconds: int) -> None:
    c = connect()
    c.execute(
        "INSERT INTO settings(key,value) VALUES ('ttl_seconds',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(seconds),),
    )
    c.commit()
    c.close()
