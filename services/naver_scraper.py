import requests
from bs4 import BeautifulSoup
import re
import time

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/"
}

# frgn 페이지 컬럼 인덱스 (9컬럼 구조)
# 날짜(0), 종가(1), 전일비(2), 등락률(3), 거래량(4), 외국인순매수(5), 기관순매수(6), 보유주수(7), 지분율(8)
COL_DATE    = 0
COL_CLOSE   = 1
COL_VOLUME  = 4
COL_FOREIGN = 5
COL_INST    = 6


def _parse_int(text: str) -> int:
    cleaned = re.sub(r"[^\d\-+]", "", text.strip().replace(",", ""))
    cleaned = cleaned.lstrip("+")
    try:
        return int(cleaned)
    except ValueError:
        return 0


def get_frgn_data(code: str, days: int = 20) -> list:
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 두 번째 type2 테이블이 날짜별 수급 데이터
        tables = soup.find_all("table", {"class": "type2"})
        table = None
        for t in tables:
            rows = t.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 9:
                    date_text = cols[COL_DATE].text.strip()
                    if re.match(r"\d{4}\.\d{2}\.\d{2}", date_text):
                        table = t
                        break
            if table:
                break

        if not table:
            return []

        rows = table.find_all("tr")
        data = []

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 9:
                continue

            date = cols[COL_DATE].text.strip()
            if not re.match(r"\d{4}\.\d{2}\.\d{2}", date):
                continue

            foreign_text = cols[COL_FOREIGN].text.strip()
            inst_text    = cols[COL_INST].text.strip()

            data.append({
                "date": date[5:],
                "close": _parse_int(cols[COL_CLOSE].text),
                "volume": _parse_int(cols[COL_VOLUME].text),
                "foreign_net": _parse_int(foreign_text),
                "institution_net": _parse_int(inst_text)
            })

            if len(data) >= days:
                break

        return data

    except Exception:
        return []


def get_stock_name(code: str) -> str:
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        soup = BeautifulSoup(resp.content, "html.parser")
        tag = soup.find("div", {"class": "wrap_company"})
        if tag:
            h2 = tag.find("h2")
            if h2:
                a = h2.find("a")
                name = (a or h2).get_text(strip=True)
                if name:
                    return name
    except Exception:
        pass
    return code


def _parse_krw_text(text: str) -> int:
    """'14조 7,691억' 같은 텍스트를 원 단위 정수로 변환"""
    if not text:
        return 0
    cleaned = text.replace(",", "")
    total = 0
    m = re.search(r"(\d+)조", cleaned)
    if m:
        total += int(m.group(1)) * 10**12
    m = re.search(r"(\d+)억", cleaned)
    if m:
        total += int(m.group(1)) * 10**8
    m = re.search(r"(\d+)만", cleaned)
    if m:
        total += int(m.group(1)) * 10**4
    if total == 0:
        m = re.search(r"(\d+)", cleaned)
        if m:
            total = int(m.group(1))
    return total


def _fetch_stock_day_page(code: str, page: int) -> list:
    url = "https://finance.naver.com/item/sise_day.naver"
    resp = requests.get(url, headers=HEADERS, params={"code": code, "page": page}, timeout=10)
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "html.parser")

    rows = []
    for tr in soup.select("table.type2 tr"):
        tds = tr.find_all("td")
        if len(tds) != 7:
            continue
        date_text = tds[0].get_text(strip=True)
        if not re.match(r"\d{4}\.\d{2}\.\d{2}", date_text):
            continue
        try:
            rows.append({
                "date":   date_text.replace(".", ""),
                "close":  float(tds[1].get_text(strip=True).replace(",", "")),
                "open":   float(tds[3].get_text(strip=True).replace(",", "")),
                "high":   float(tds[4].get_text(strip=True).replace(",", "")),
                "low":    float(tds[5].get_text(strip=True).replace(",", "")),
                "volume": float(tds[6].get_text(strip=True).replace(",", "")),
            })
        except ValueError:
            continue
    return rows


def _fetch_index_day_page(code: str, page: int) -> list:
    url = "https://finance.naver.com/sise/sise_index_day.naver"
    resp = requests.get(url, headers=HEADERS, params={"code": code, "page": page}, timeout=10)
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "html.parser")

    rows = []
    for tr in soup.select("table.type_1 tr"):
        date_td = tr.find("td", class_="date")
        if not date_td:
            continue
        nums = tr.find_all("td", class_="number_1")
        if len(nums) < 3:
            continue
        date_text = date_td.get_text(strip=True)
        try:
            close = float(nums[0].get_text(strip=True).replace(",", ""))
            volume = float(nums[-2].get_text(strip=True).replace(",", ""))
            rows.append({
                "date": date_text.replace(".", ""),
                "open": close, "high": close, "low": close,  # 지수 일별 페이지는 종가만 제공
                "close": close, "volume": volume,
            })
        except ValueError:
            continue
    return rows


def _fetch_page_safe(fetch_page, symbol: str, page: int) -> list:
    """페이지 하나가 실패(네트워크 오류/차단 등)해도 나머지 페이지는 살리기 위한 래퍼.
    실패 원인은 print로 남겨 Render 로그에서 바로 확인할 수 있게 한다."""
    try:
        return fetch_page(symbol, page)
    except Exception as e:
        print(f"[get_daily_ohlcv] page {page} 실패 ({symbol}): {type(e).__name__}: {e}", flush=True)
        return []


def get_daily_ohlcv(symbol: str, count: int = 250) -> list:
    """
    일별 시가/고가/저가/종가/거래량 히스토리. 개별 종목 코드("005930")와 지수 심볼
    ("KOSPI","KOSDAQ")를 모두 지원하며(지수는 종가만 제공), 페이지를 순차적으로 긁어온다.

    yfinance 대신 사용 — 클라우드(Render 등) 배포 환경에서 야후 파이낸스가 데이터센터
    IP를 차단해 타임아웃/502가 나는 문제를 피하기 위함. finance.naver.com의 다른
    스크래핑(get_frgn_data 등)과 같은 도메인이라 배포 환경에서도 동일하게 동작 확인됨
    (fchart.stock.naver.com은 별도 서브도메인이라 배포 환경에서 차단되는 것을 확인해 폐기).

    페이지가 적을 때(3개, 거래량용)는 배포 환경에서 문제없이 동작하는데 페이지가
    많을 때(15개, 기술적분석용)는 실패하는 것을 확인함 — 짧은 시간에 같은 도메인으로
    요청이 몰리면 네이버가 차단하는 것으로 추정. 병렬 대신 약간의 간격을 둔 순차
    요청으로 바꿔 요청 속도를 늦춘다. 페이지 하나가 실패해도 전체를 실패시키지
    않고 나머지 페이지 데이터라도 반환한다.
    """
    is_index = symbol in ("KOSPI", "KOSDAQ")
    fetch_page = _fetch_index_day_page if is_index else _fetch_stock_day_page
    pages = max(1, -(-count // 10))  # ceil(count/10)

    rows_by_date = {}
    for p in range(1, pages + 1):
        for r in _fetch_page_safe(fetch_page, symbol, p):
            rows_by_date[r["date"]] = r
        if p < pages:
            time.sleep(0.25)

    return sorted(rows_by_date.values(), key=lambda r: r["date"])[-count:]


def get_realtime_quote(code: str) -> dict:
    """네이버 실시간 시세 폴링 API — yfinance보다 최신인 당일/최근 거래일 시세"""
    url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        item = (resp.json().get("datas") or [None])[0]
        if not item:
            return {}

        code_dir = (item.get("compareToPreviousPrice") or {}).get("code", "3")
        sign = 1 if code_dir in ("1", "2") else (-1 if code_dir in ("4", "5") else 0)
        change_pct = sign * abs(float(item.get("fluctuationsRatio") or 0))

        return {
            "market":             (item.get("stockExchangeType") or {}).get("nameEng", "KOSPI"),
            "price":              _parse_int(item.get("closePrice", "0")),
            "open":               _parse_int(item.get("openPrice", "0")),
            "high":               _parse_int(item.get("highPrice", "0")),
            "low":                _parse_int(item.get("lowPrice", "0")),
            "change_won":         sign * _parse_int(item.get("compareToPreviousClosePrice", "0")),
            "change_pct":         round(change_pct, 2),
            "up":                 sign >= 0,
            "volume":             _parse_int(item.get("accumulatedTradingVolume", "0")),
            "trading_value_text": item.get("accumulatedTradingValue", ""),
            "trading_value_won":  _parse_krw_text(item.get("accumulatedTradingValue", "")),
            "market_status":      item.get("marketStatus", ""),
            "trade_datetime":     item.get("localTradedAt", ""),
        }
    except Exception:
        return {}


def get_news(code: str, limit: int = 5) -> list:
    """네이버 금융 종목뉴스 제목 크롤링 (제목/날짜/링크만)"""
    url = f"https://finance.naver.com/item/news_news.naver?code={code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")

        news = []
        for row in soup.select("table.type5 tr"):
            a = row.select_one("td.title a")
            if not a:
                continue
            title = a.get_text(strip=True)
            if not title:
                continue
            href = a.get("href", "")
            if href.startswith("/"):
                href = "https://finance.naver.com" + href
            date_td = row.select_one("td.date")
            date = date_td.get_text(strip=True) if date_td else ""
            news.append({"title": title, "date": date, "url": href})
            if len(news) >= limit:
                break
        return news
    except Exception:
        return []


def _parse_pct(text: str):
    if not text:
        return None
    try:
        return float(text.replace("%", "").replace(",", ""))
    except ValueError:
        return None


def _parse_multiple(text: str):
    if not text:
        return None
    try:
        return float(text.replace("배", "").replace(",", ""))
    except ValueError:
        return None


def search_stock_code(query: str) -> dict:
    """종목명(또는 일부 코드)으로 종목코드 검색. 못 찾으면 None. {code, name} 반환."""
    query = (query or "").strip()
    if not query:
        return None
    url = "https://m.stock.naver.com/front-api/search/autoComplete"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8, params={
            "query": query, "target": "stock,index,marketindicator,coin,ipo",
        })
        items = ((resp.json().get("result") or {}).get("items")) or []
        stock_items = [i for i in items if i.get("category") == "stock" and re.match(r"^\d{6}$", i.get("code", ""))]
        if not stock_items:
            return None
        exact = next((i for i in stock_items if i.get("name") == query), None)
        best = exact or stock_items[0]
        return {"code": best["code"], "name": best["name"]}
    except Exception:
        return None


def get_investor_info(code: str) -> dict:
    """
    finance.naver.com 메인 페이지의 '투자의견' 위젯 스크래핑 — 투자의견/목표주가/52주최고·최저.
    m.stock.naver.com 통합 API의 52주최고·최저와 값이 다를 수 있어(서로 다른 산정 기준),
    사용자가 실제로 보는 PC 페이지 기준으로 통일하기 위해 이 위젯 값을 우선 사용한다.
    """
    result = {"opinion": None, "recomm_mean": None, "target_price": None, "high_52w": None, "low_52w": None}
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        table = soup.find("table", {"summary": "투자의견 정보"})
        if not table:
            return result
        rows = table.find_all("tr")

        if len(rows) >= 1:
            ems = rows[0].find_all("em")
            if len(ems) >= 2:
                result["recomm_mean"] = float(ems[0].get_text(strip=True))
                result["target_price"] = _parse_int(ems[1].get_text(strip=True))
                span = rows[0].find("span", class_=lambda c: c and c.startswith("f_"))
                if span:
                    result["opinion"] = re.sub(r"^[\d.]+", "", span.get_text(strip=True)).strip()

        if len(rows) >= 2:
            ems2 = rows[1].find_all("em")
            if len(ems2) >= 2:
                result["high_52w"] = _parse_int(ems2[0].get_text(strip=True))
                result["low_52w"] = _parse_int(ems2[1].get_text(strip=True))

        return result
    except Exception:
        return result


def get_naver_metrics(code: str) -> dict:
    """
    m.stock.naver.com 통합 API — PER/PBR/EPS/BPS/시총/52주 고저 +
    증권사 컨센서스(투자의견/목표주가)를 한 번에 제공.
    yfinance가 KRX 종목에서 PER/PBR을 못 주는 경우의 대체 소스로도 사용.
    """
    url = f"https://m.stock.naver.com/api/stock/{code}/integration"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        data = resp.json()
        info = {i["code"]: i.get("value") for i in (data.get("totalInfos") or [])}

        metrics = {
            "per":            _parse_multiple(info.get("per")),
            "pbr":            _parse_multiple(info.get("pbr")),
            "eps":            _parse_int(info.get("eps", "")) or None,
            "bps":            _parse_int(info.get("bps", "")) or None,
            "market_cap":     _parse_krw_text(info.get("marketValue", "")) or None,
            "foreign_rate":   _parse_pct(info.get("foreignRate")),
            "dividend_yield": _parse_pct(info.get("dividendYieldRatio")),
            "high_52w":       _parse_int(info.get("highPriceOf52Weeks", "")) or None,
            "low_52w":        _parse_int(info.get("lowPriceOf52Weeks", "")) or None,
        }

        consensus = None
        c = data.get("consensusInfo")
        if c and c.get("priceTargetMean"):
            recomm = float(c.get("recommMean") or 0)
            if recomm <= 0:
                label = None
            elif recomm <= 1.5:
                label = "강력매수"
            elif recomm <= 2.5:
                label = "매수"
            elif recomm <= 3.5:
                label = "중립"
            elif recomm <= 4.5:
                label = "비중축소"
            else:
                label = "매도"

            consensus = {
                "recomm_mean":  recomm,
                "opinion":      label,
                "target_price": _parse_int(c.get("priceTargetMean", "0")),
                "date":         c.get("createDate"),
            }

        return {"metrics": metrics, "consensus": consensus}
    except Exception:
        return {"metrics": {}, "consensus": None}
