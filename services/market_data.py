"""
글로벌 시장 지표 — 네이버 금융 실시간 API 기반.

원래 yfinance(야후 파이낸스)를 썼으나, 야후는 데이터센터 IP(Render 등 클라우드 호스팅)를
봇으로 인식해 자주 차단/타임아웃시킨다. 로컬 PC에서는 문제없이 동작해도 배포 환경에서는
전체 요청이 502로 실패하는 원인이 되므로, 이미 배포 환경에서 정상 동작이 확인된 네이버
금융 API로 전량 교체했다.
"""

import re
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/"
}

# (표시명, 소스 종류, 코드)
INDEX_SOURCES = [
    ("KOSPI",   "domestic", "KOSPI"),
    ("KOSDAQ",  "domestic", "KOSDAQ"),
    ("S&P500",  "world",    ".INX"),
    ("NASDAQ",  "world",    ".IXIC"),
    ("DOW",     "world",    ".DJI"),
    ("WTI유가", "oil",      "OIL_CL"),
    ("VIX",     "world",    ".VIX"),
    ("USD/KRW", "exchange", "FX_USDKRW"),
]

UNITS = {
    "KOSPI": "pt", "KOSDAQ": "pt", "S&P500": "pt", "NASDAQ": "pt",
    "DOW": "pt", "WTI유가": "$", "VIX": "pt", "USD/KRW": "원",
}


def _parse_num(text) -> float:
    if not text:
        return 0.0
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return 0.0


def _sign_from_code(code: str) -> int:
    return 1 if code in ("1", "2") else (-1 if code in ("4", "5") else 0)


def _fetch_index(reuters_code: str, category: str) -> dict:
    url = f"https://polling.finance.naver.com/api/realtime/{category}/index/{reuters_code}"
    resp = requests.get(url, headers=HEADERS, timeout=8)
    item = (resp.json().get("datas") or [None])[0]
    if not item:
        return None

    price = _parse_num(item.get("closePriceRaw") or item.get("closePrice"))
    change_pct = _parse_num(item.get("fluctuationsRatioRaw") or item.get("fluctuationsRatio"))
    sign = _sign_from_code((item.get("compareToPreviousPrice") or {}).get("code", "3"))

    return {"price": round(price, 2), "change_pct": round(sign * abs(change_pct), 2), "up": sign >= 0}


def _fetch_exchange(reuters_code: str) -> dict:
    url = "https://m.stock.naver.com/front-api/marketIndex/prices"
    resp = requests.get(url, headers=HEADERS, params={"category": "exchange", "reutersCode": reuters_code}, timeout=8)
    rows = resp.json().get("result") or []
    if not rows:
        return None

    latest = rows[0]
    price = _parse_num(latest.get("closePrice"))
    change_pct = _parse_num(latest.get("fluctuationsRatio"))
    sign = _sign_from_code((latest.get("fluctuationsType") or {}).get("code", "3"))

    return {"price": round(price, 2), "change_pct": round(sign * abs(change_pct), 2), "up": sign >= 0}


def _fetch_oil(marketindex_cd: str) -> dict:
    """WTI유가는 실시간 API가 따로 없어 상세 페이지를 직접 스크래핑한다."""
    url = "https://finance.naver.com/marketindex/worldOilDetail.naver"
    resp = requests.get(url, headers=HEADERS, params={"marketindexCd": marketindex_cd, "fdtc": 2}, timeout=8)
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "lxml")

    today = soup.select_one("p.no_today em")
    exday = soup.select_one("p.no_exday em:nth-of-type(2)")
    if not today:
        return None

    price = _parse_num(today.get_text(strip=True))
    is_down = "no_down" in (today.get("class") or [])
    pct_text = exday.get_text(strip=True) if exday else "0"
    pct_match = re.search(r"[\d.]+", pct_text)
    change_pct = _parse_num(pct_match.group()) if pct_match else 0.0

    return {"price": round(price, 2), "change_pct": round(-change_pct if is_down else change_pct, 2), "up": not is_down}


def _fetch_one(item):
    name, category, code = item
    try:
        if category == "domestic":
            result = _fetch_index(code, "domestic")
        elif category == "world":
            result = _fetch_index(code, "worldstock")
        elif category == "exchange":
            result = _fetch_exchange(code)
        elif category == "oil":
            result = _fetch_oil(code)
        else:
            result = None

        if not result:
            return name, {"price": 0, "change_pct": 0, "up": True, "unit": UNITS.get(name, ""), "error": "데이터 없음"}

        result["unit"] = UNITS.get(name, "")
        return name, result
    except Exception as e:
        return name, {"price": 0, "change_pct": 0, "up": True, "unit": UNITS.get(name, ""), "error": str(e)}


def get_market_data():
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_fetch_one, INDEX_SOURCES))

    data = {name: val for name, val in results if val}

    return {
        "timestamp": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "data": data
    }
