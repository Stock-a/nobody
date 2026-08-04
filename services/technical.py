import pandas as pd

from services.naver_scraper import get_daily_ohlcv, get_realtime_quote


def _to_list(series, decimals=0):
    return [None if pd.isna(v) else round(float(v), decimals) for v in series]


def _find_support_resistance(high_series, low_series, current_price, window=5, lookback=120, max_levels=2):
    """
    최근 lookback 거래일 내 스윙 고점/저점(좌우 ±window일 내 지역 최댓값/최솟값)을 찾아
    현재가 기준 가장 가까운 저항선(위)·지지선(아래)을 반환한다.
    가격의 0.5% 단위로 묶어서 근접한 레벨은 하나로 합친다.
    """
    if not current_price or current_price <= 0:
        return [], []

    h = high_series.tail(lookback).reset_index(drop=True)
    l = low_series.tail(lookback).reset_index(drop=True)
    n = len(h)
    if n <= window * 2:
        return [], []

    swing_highs, swing_lows = [], []
    for i in range(window, n - window):
        seg_h = h.iloc[i - window:i + window + 1]
        if h.iloc[i] == seg_h.max():
            swing_highs.append(float(h.iloc[i]))
        seg_l = l.iloc[i - window:i + window + 1]
        if l.iloc[i] == seg_l.min():
            swing_lows.append(float(l.iloc[i]))

    bucket = max(current_price * 0.005, 1)

    def cluster(levels):
        return sorted({round(round(x / bucket) * bucket) for x in levels})

    resistances = [x for x in cluster(swing_highs) if x > current_price]
    supports = sorted((x for x in cluster(swing_lows) if x < current_price), reverse=True)

    return resistances[:max_levels], supports[:max_levels]


def get_technical_data(code: str) -> dict:
    rows = get_daily_ohlcv(code, count=200)
    if not rows or len(rows) < 30:
        return {"error": "데이터 없음"}

    quote = get_realtime_quote(code)
    market = quote.get("market", "KOSPI") if quote else "KOSPI"

    hist = pd.DataFrame(rows)
    hist["Date"] = pd.to_datetime(hist["date"], format="%Y%m%d")
    hist = hist.set_index("Date").sort_index()
    hist = hist.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
    })

    close = hist["Close"]
    volume = hist["Volume"]
    high_series = hist["High"]
    low_series = hist["Low"]

    # 이동평균선
    ma5   = close.rolling(5).mean()
    ma20  = close.rolling(20).mean()
    ma60  = close.rolling(60).mean()
    ma120 = close.rolling(120).mean()

    # 볼린저밴드 (20일, 2σ)
    bb_mid   = close.rolling(20).mean()
    bb_std   = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    # RSI (14일, Wilder 방식)
    delta    = close.diff()
    gain     = delta.where(delta > 0, 0.0)
    loss     = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    ema12       = close.ewm(span=12, adjust=False).mean()
    ema26       = close.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist   = macd_line - signal_line

    # 이격도 (Disparity): 종가/이동평균×100 — 한국 투자자들이 많이 사용
    disp20 = (close / ma20 * 100)
    disp60 = (close / ma60 * 100)

    # 거래량 이동평균 (20일)
    vol_ma20 = volume.rolling(20).mean()

    # 52주 고/저 위치 (종가가 아닌 장중 고가/저가 기준 — 네이버 증권과 동일 기준)
    high_52w = float(high_series.max())
    low_52w  = float(low_series.min())
    current  = float(close.iloc[-1])
    position_52w = (
        round((current - low_52w) / (high_52w - low_52w) * 100, 1)
        if high_52w != low_52w else 50
    )

    n = 120  # 최근 120 거래일 반환
    dates = [d.strftime("%y.%m.%d") for d in close.index[-n:]]

    resistance_levels, support_levels = _find_support_resistance(high_series, low_series, current)

    # 수급 요약 (외인/기관 5일 합계 → naver_scraper 쪽에서 처리, 여기선 skip)
    return {
        "market":      market,
        "dates":       dates,
        "open":        _to_list(hist["Open"][-n:], 0),
        "high":        _to_list(high_series[-n:], 0),
        "low":         _to_list(low_series[-n:], 0),
        "close":       _to_list(close[-n:], 0),
        "ma5":         _to_list(ma5[-n:], 0),
        "ma20":        _to_list(ma20[-n:], 0),
        "ma60":        _to_list(ma60[-n:], 0),
        "ma120":       _to_list(ma120[-n:], 0),
        "bb_upper":    _to_list(bb_upper[-n:], 0),
        "bb_mid":      _to_list(bb_mid[-n:], 0),
        "bb_lower":    _to_list(bb_lower[-n:], 0),
        "rsi":         _to_list(rsi[-n:], 1),
        "macd":        _to_list(macd_line[-n:], 2),
        "macd_signal": _to_list(signal_line[-n:], 2),
        "macd_hist":   _to_list(macd_hist[-n:], 2),
        "disp20":      _to_list(disp20[-n:], 2),
        "disp60":      _to_list(disp60[-n:], 2),
        "volume":      [int(v) if not pd.isna(v) else 0 for v in volume[-n:]],
        "vol_ma20":    _to_list(vol_ma20[-n:], 0),
        # 요약 값 (현재 시점)
        "high_52w":       round(high_52w, 0),
        "low_52w":        round(low_52w, 0),
        "current":        round(current, 0),
        "position_52w":   position_52w,
        "resistance_levels": resistance_levels,
        "support_levels":    support_levels,
        "current_rsi":    round(float(rsi.iloc[-1]), 1)  if not pd.isna(rsi.iloc[-1])    else None,
        "current_disp20": round(float(disp20.iloc[-1]), 2) if not pd.isna(disp20.iloc[-1]) else None,
        "current_disp60": round(float(disp60.iloc[-1]), 2) if not pd.isna(disp60.iloc[-1]) else None,
        "current_ma5":    round(float(ma5.iloc[-1]), 0)  if not pd.isna(ma5.iloc[-1])   else None,
        "current_ma20":   round(float(ma20.iloc[-1]), 0) if not pd.isna(ma20.iloc[-1])  else None,
        "current_ma60":   round(float(ma60.iloc[-1]), 0) if not pd.isna(ma60.iloc[-1])  else None,
        "current_ma120":  round(float(ma120.iloc[-1]), 0) if not pd.isna(ma120.iloc[-1]) else None,
    }


def apply_52w_override(tech: dict, naver_metrics: dict) -> dict:
    """네이버 증권이 제공하는 52주 최고/최저(더 정확한 공식 값)로 교체하고 52주 위치를 재계산"""
    if not tech or "error" in tech or not naver_metrics:
        return tech

    high = naver_metrics.get("high_52w")
    low = naver_metrics.get("low_52w")
    if not high or not low:
        return tech

    tech = dict(tech)
    tech["high_52w"] = high
    tech["low_52w"] = low
    current = tech.get("current")
    if current and high != low:
        tech["position_52w"] = round((current - low) / (high - low) * 100, 1)
    return tech
