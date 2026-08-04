"""
향후 이벤트(FOMC/실적발표) 조회

FOMC 일정은 연준이 매년 말 다음 해 일정을 공식 발표하는 고정 스케줄이라
API로 제공되지 않는다. 아래 리스트는 연방준비제도(federalreserve.gov) 공식
캘린더 기준이며, 매년 갱신이 필요하다 (다음 갱신: 2027년 일정 발표 시).
"""

from datetime import datetime

import yfinance as yf

# 2026년 FOMC 정례회의 마지막 날짜 (federalreserve.gov 공식 캘린더 기준)
FOMC_2026_DATES = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]


def get_next_fomc(today: datetime = None) -> str:
    today = today or datetime.now()
    for d in FOMC_2026_DATES:
        if datetime.strptime(d, "%Y-%m-%d") >= today:
            return d
    return None


def get_next_earnings(code: str) -> str:
    """다음 실적발표 예정일 (yfinance 제공 시). 조회 불가하면 None."""
    for suffix in [".KS", ".KQ"]:
        try:
            t = yf.Ticker(code + suffix)
            dates = t.get_earnings_dates(limit=8)
            if dates is None or dates.empty:
                continue
            now = datetime.now(dates.index.tz) if dates.index.tz else datetime.now()
            future = [d for d in dates.index if d >= now]
            if future:
                return min(future).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None
