"""
한국 주식 켈리 포지션 사이징 분석기 (V2)

일반적인 켈리 공식(f* = p - (1-p)/b)을 그대로 쓰지 않고,
① 종목 적합성 등급(A+~D) ② Kelly Score(0~100)+투자비중표 ③ 분할매수(1~3차)
④ 상승 시 추가매수(불타기) 조건 ⑤ 종목유형별 손절 ⑥ 단계별 익절
⑦ 거래대금 분석 ⑧ 핵심 이벤트/시나리오/결론
을 종합하는 한국형 실전 자금관리 로직으로 구성한다.

서술형 항목(뉴스/공시/시나리오/결론)은 LLM 호출 없이, 실제 수집된 수치를
바탕으로 한 규칙 기반 템플릿으로 생성한다.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from services.technical import get_technical_data, apply_52w_override
from services.naver_scraper import (
    get_frgn_data, get_stock_name, get_realtime_quote,
    get_naver_metrics, get_investor_info, get_news, get_daily_ohlcv,
)
from services.dart_client import get_recent_disclosures, has_api_key as has_dart_key
from services.events import get_next_fomc, get_next_earnings


# ──────────────────────────────────────────
# 재무 데이터 — 네이버 통합 API 기반
# ──────────────────────────────────────────
#
# 예전에는 yfinance로 매출성장률/영업이익률/부채비율까지 가져왔으나, 야후 파이낸스가
# 클라우드 호스팅(Render 등) IP를 차단해 배포 환경에서 타임아웃 → 502로 이어지는
# 문제가 있어 전량 제거했다. PER/PBR/ROE/시가총액은 네이버 통합 API로 대체되고,
# 매출성장률/영업이익률/부채비율은 현재 대체 소스가 없어 비어 있는 채로(None) 처리된다
# (프런트/스코어링 쪽은 이미 None을 "데이터 없음"으로 안전하게 처리하도록 되어 있음).

def _merge_financial(naver: dict) -> dict:
    m = (naver or {}).get("metrics") or {}
    roe = round(m["eps"] / m["bps"], 4) if m.get("eps") and m.get("bps") else None
    return {
        "current_price":    None,
        "per":              m.get("per"),
        "pbr":              m.get("pbr"),
        "roe":              roe,
        "market_cap":       m.get("market_cap"),
        "beta":             None,
        "52w_high":         m.get("high_52w"),
        "52w_low":          m.get("low_52w"),
        "revenue_growth":   None,
        "operating_margin": None,
        "debt_ratio":       None,
    }


# ──────────────────────────────────────────
# 축별 점수 계산 (각 0~100)
# ──────────────────────────────────────────

def _score_technical(tech: dict) -> dict:
    score = 0
    items = []

    rsi = tech.get("current_rsi")
    if rsi is not None:
        if rsi < 25:
            score += 28; items.append(("positive", f"RSI {rsi} — 강한 과매도, 반등 기대"))
        elif rsi < 35:
            score += 22; items.append(("positive", f"RSI {rsi} — 과매도 구간 (매수 신호)"))
        elif rsi < 50:
            score += 14; items.append(("neutral", f"RSI {rsi} — 중립 하단"))
        elif rsi < 65:
            score += 8;  items.append(("neutral", f"RSI {rsi} — 중립 구간"))
        elif rsi < 75:
            score += 3;  items.append(("neutral", f"RSI {rsi} — 과매수 근접 (신중)"))
        else:
            items.append(("negative", f"RSI {rsi} — 과매수, 매수 자제"))

    disp = tech.get("current_disp20")
    if disp is not None:
        if disp < 88:
            score += 28; items.append(("positive", f"이격도 {disp} — 20일 이평 대비 크게 저평가"))
        elif disp < 95:
            score += 20; items.append(("positive", f"이격도 {disp} — 20일 이평 대비 저평가"))
        elif disp < 103:
            score += 12; items.append(("neutral", f"이격도 {disp} — 20일 이평 근접 (중립)"))
        elif disp < 108:
            score += 4;  items.append(("neutral", f"이격도 {disp} — 소폭 고평가"))
        else:
            items.append(("negative", f"이격도 {disp} — 과열 구간, 매수 자제"))

    macd_list = tech.get("macd", [])
    sig_list  = tech.get("macd_signal", [])
    if len(macd_list) >= 2 and len(sig_list) >= 2:
        m0, m1 = macd_list[-1], macd_list[-2]
        s0      = sig_list[-1]
        if m0 is not None and m1 is not None and s0 is not None:
            if m1 < sig_list[-2] and m0 > s0:
                score += 28; items.append(("positive", "MACD 골든크로스 발생 — 강한 상승 전환 신호!"))
            elif m0 > s0:
                score += 16; items.append(("positive", "MACD > Signal — 상승 추세"))
            elif m0 < s0 and m0 > -abs(s0) * 0.3:
                score += 6;  items.append(("neutral",  "MACD < Signal — 약한 하락 (회복 중 가능)"))
            else:
                items.append(("negative", "MACD < Signal — 하락 추세"))

    pos52 = tech.get("position_52w", 50)
    if pos52 < 25:
        score += 16; items.append(("positive", f"52주 위치 {pos52}% — 연저점 근처, 낙폭과대"))
    elif pos52 < 45:
        score += 10; items.append(("positive", f"52주 위치 {pos52}% — 중하단 구간"))
    elif pos52 < 65:
        score += 6;  items.append(("neutral",  f"52주 위치 {pos52}% — 중간 구간"))
    elif pos52 < 80:
        score += 2;  items.append(("neutral",  f"52주 위치 {pos52}% — 상단 구간"))
    else:
        items.append(("negative", f"52주 위치 {pos52}% — 고점 근처, 신중 매수"))

    # 이동평균 골든/데드크로스(20일선-60일선) — 교차 자체보다 거래량 동반 여부로 신뢰도 차등
    ma20_list = tech.get("ma20") or []
    ma60_list = tech.get("ma60") or []
    vol_list = tech.get("volume") or []
    vol_ma20_list = tech.get("vol_ma20") or []
    if len(ma20_list) >= 2 and len(ma60_list) >= 2:
        m20_0, m20_1 = ma20_list[-1], ma20_list[-2]
        m60_0, m60_1 = ma60_list[-1], ma60_list[-2]
        if None not in (m20_0, m20_1, m60_0, m60_1):
            vol_confirmed = bool(
                vol_list and vol_ma20_list and vol_list[-1] and vol_ma20_list[-1]
                and vol_list[-1] > vol_ma20_list[-1] * 1.2
            )
            if m20_1 <= m60_1 and m20_0 > m60_0:
                if vol_confirmed:
                    score += 18; items.append(("positive", "20일선이 60일선을 상향 돌파(골든크로스)하며 거래량 증가 동반 — 신뢰도 있는 상승 신호"))
                else:
                    score += 8; items.append(("positive", "20일선이 60일선을 상향 돌파(골든크로스), 다만 거래량 증가 미동반으로 신뢰도 제한적"))
            elif m20_1 >= m60_1 and m20_0 < m60_0:
                if vol_confirmed:
                    score -= 10; items.append(("negative", "20일선이 60일선을 하향 돌파(데드크로스)하며 거래량 증가 동반 — 신뢰도 있는 하락 신호"))
                else:
                    items.append(("negative", "20일선이 60일선을 하향 돌파(데드크로스), 다만 거래량 증가 미동반으로 신뢰도 제한적"))

    return {"score": min(100, score), "items": items}


def _score_supply(frgn: list) -> dict:
    if not frgn:
        return {"score": 50, "items": [("neutral", "수급 데이터 없음 (중립 처리)")], "f5": 0, "i5": 0}

    r5 = frgn[:5]
    f5 = sum(d["foreign_net"] for d in r5)
    i5 = sum(d["institution_net"] for d in r5)
    score = 50
    items = []

    if f5 > 0:
        score += 22; items.append(("positive", f"외국인 5일 합계 +{f5:,}주 (순매수)"))
    elif f5 < 0:
        score -= 18; items.append(("negative", f"외국인 5일 합계 {f5:,}주 (순매도)"))

    if i5 > 0:
        score += 14; items.append(("positive", f"기관 5일 합계 +{i5:,}주 (순매수)"))
    elif i5 < 0:
        score -= 10; items.append(("negative", f"기관 5일 합계 {i5:,}주 (순매도)"))

    if f5 > 0 and i5 > 0:
        score += 14; items.append(("positive", "외인+기관 동반 순매수 — 강한 수급 신호!"))
    elif f5 < 0 and i5 < 0:
        score -= 14; items.append(("negative", "외인+기관 동반 순매도 — 수급 악화"))

    return {"score": max(0, min(100, score)), "items": items, "f5": f5, "i5": i5}


def _score_fundamental(fin: dict) -> dict:
    if not fin:
        return {"score": 50, "items": [("neutral", "재무 데이터 없음 (중립 처리)")]}

    score = 50
    items = []

    rg = fin.get("revenue_growth")
    if rg is not None:
        if rg > 20:
            score += 18; items.append(("positive", f"매출 성장률 +{rg}% — 고성장"))
        elif rg > 5:
            score += 10; items.append(("positive", f"매출 성장률 +{rg}% — 성장"))
        elif rg >= -3:
            score += 4;  items.append(("neutral",  f"매출 성장률 {rg}% — 보합"))
        else:
            score -= 12; items.append(("negative", f"매출 성장률 {rg}% — 역성장 주의"))

    om = fin.get("operating_margin")
    if om is not None:
        if om > 20:
            score += 20; items.append(("positive", f"영업이익률 {om}% — 고수익 구조"))
        elif om > 10:
            score += 12; items.append(("positive", f"영업이익률 {om}% — 양호"))
        elif om > 3:
            score += 4;  items.append(("neutral",  f"영업이익률 {om}% — 낮은 이익"))
        else:
            score -= 15; items.append(("negative", f"영업이익률 {om}% — 적자 또는 손익분기점 근접 주의"))

    dr = fin.get("debt_ratio")
    if dr is not None:
        if dr < 40:
            score += 16; items.append(("positive", f"부채비율 {dr}% — 재무 우량"))
        elif dr < 100:
            score += 8;  items.append(("positive", f"부채비율 {dr}% — 보통 수준"))
        elif dr < 200:
            score += 2;  items.append(("neutral",  f"부채비율 {dr}% — 다소 높음, 모니터링 필요"))
        else:
            score -= 12; items.append(("negative", f"부채비율 {dr}% — 과다 부채 주의!"))

    per = fin.get("per")
    if per is not None:
        if per < 0:
            score -= 15; items.append(("negative", f"PER 음수 ({per:.1f}x) — 적자 기업"))
        elif per < 8:
            score += 16; items.append(("positive", f"PER {per:.1f}x — 매우 저평가"))
        elif per < 15:
            score += 10; items.append(("positive", f"PER {per:.1f}x — 저평가"))
        elif per < 25:
            score += 5;  items.append(("neutral",  f"PER {per:.1f}x — 적정 수준"))
        elif per < 40:
            score += 1;  items.append(("neutral",  f"PER {per:.1f}x — 다소 고평가"))
        else:
            score -= 5;  items.append(("negative", f"PER {per:.1f}x — 고평가"))

    pbr = fin.get("pbr")
    if pbr is not None:
        if pbr < 0.7:
            score += 16; items.append(("positive", f"PBR {pbr:.2f}x — 자산 대비 매우 저평가"))
        elif pbr < 1.2:
            score += 8;  items.append(("positive", f"PBR {pbr:.2f}x — 저평가"))
        elif pbr < 2.5:
            score += 3;  items.append(("neutral",  f"PBR {pbr:.2f}x — 적정"))
        else:
            items.append(("neutral",  f"PBR {pbr:.2f}x — 고평가"))

    roe = fin.get("roe")
    if roe is not None:
        roe_pct = round(roe * 100, 1)
        if roe_pct > 20:
            score += 10; items.append(("positive", f"ROE {roe_pct}% — 높은 자기자본이익률"))
        elif roe_pct > 10:
            score += 5;  items.append(("positive", f"ROE {roe_pct}% — 양호"))
        elif roe_pct < 0:
            score -= 10; items.append(("negative", f"ROE {roe_pct}% — 자본 잠식 위험"))

    return {"score": max(0, min(100, score)), "items": items}


def _score_consensus(consensus: dict, current_price: float) -> dict:
    if not consensus or not consensus.get("target_price") or not current_price:
        return {"score": 50, "items": [("neutral", "컨센서스 데이터 없음 (중립 처리)")],
                "target_price": None, "opinion": None, "upside_pct": None}

    target = consensus["target_price"]
    upside = round((target / current_price - 1) * 100, 1)
    opinion = consensus.get("opinion")
    score = 50
    items = []

    if upside >= 30:
        score += 30; items.append(("positive", f"목표주가 대비 +{upside}% 상승여력 — 컨센서스 매우 낙관적"))
    elif upside >= 15:
        score += 20; items.append(("positive", f"목표주가 대비 +{upside}% 상승여력"))
    elif upside >= 5:
        score += 10; items.append(("positive", f"목표주가 대비 +{upside}% 상승여력"))
    elif upside >= -5:
        items.append(("neutral", f"현재가가 목표주가 근접 ({upside}%)"))
    else:
        score -= 15; items.append(("negative", f"현재가가 목표주가를 이미 {abs(upside)}% 상회 — 상승여력 제한적"))

    op_type = "neutral"
    if opinion in ("강력매수", "매수"):
        op_type = "positive"
    elif opinion in ("비중축소", "매도"):
        op_type = "negative"
    items.append((op_type, f"증권사 컨센서스: {opinion or '—'} (목표주가 {target:,}원)"))

    return {"score": max(0, min(100, score)), "items": items,
            "target_price": target, "opinion": opinion, "upside_pct": upside}


def _score_trading_value(tech: dict, quote: dict, market_cap) -> dict:
    close = tech.get("close") or []
    vol   = tech.get("volume") or []

    avg_tv = 0
    if len(close) >= 20 and len(vol) >= 20:
        pairs = list(zip(close[-20:], vol[-20:]))
        vals = [c * v for c, v in pairs if c and v]
        if vals:
            avg_tv = sum(vals) / len(vals)

    today_tv = (quote or {}).get("trading_value_won") or (close[-1] * vol[-1] if close and vol else 0)
    ratio = round(today_tv / avg_tv, 2) if avg_tv > 0 else None
    turnover = round(today_tv / market_cap * 100, 2) if market_cap else None

    score = 50
    items = []
    if ratio is not None:
        if ratio >= 3:
            score += 30; items.append(("positive", f"거래대금 20일 평균 대비 {ratio}배 — 강한 수급 유입"))
        elif ratio >= 1.5:
            score += 15; items.append(("positive", f"거래대금 20일 평균 대비 {ratio}배 — 관심 증가"))
        elif ratio >= 0.7:
            items.append(("neutral", f"거래대금 20일 평균 수준 ({ratio}배)"))
        else:
            score -= 10; items.append(("negative", f"거래대금 20일 평균 대비 {ratio}배 — 관심 저조"))
    else:
        items.append(("neutral", "거래대금 데이터 부족 (중립 처리)"))

    if turnover is not None:
        if turnover >= 3:
            score += 10; items.append(("positive", f"시가총액 대비 회전율 {turnover}% — 매우 활발"))
        elif turnover >= 1:
            items.append(("neutral", f"회전율 {turnover}%"))

    return {"score": max(0, min(100, score)), "items": items,
            "today_value": round(today_tv), "avg_value": round(avg_tv),
            "ratio": ratio, "turnover_pct": turnover}


def _score_relative_strength(tech: dict) -> dict:
    close = tech.get("close") or []
    if len(close) < 21:
        return {"score": 50, "items": [("neutral", "데이터 부족 (중립 처리)")],
                "stock_return": None, "index_return": None, "market_label": None}

    stock_ret = round((close[-1] / close[-21] - 1) * 100, 2)
    market = tech.get("market", "KOSPI")
    label = "코스닥" if market == "KOSDAQ" else "코스피"

    idx_ret = 0.0
    try:
        idx_rows = get_daily_ohlcv(market, count=40)
        idx_close = [r["close"] for r in idx_rows]
        if len(idx_close) >= 21:
            idx_ret = round((idx_close[-1] / idx_close[-21] - 1) * 100, 2)
    except Exception:
        pass

    diff = round(stock_ret - idx_ret, 2)
    score = max(0, min(100, round(50 + diff * 2)))
    items = []
    if diff >= 10:
        items.append(("positive", f"{label} 대비 상대강도 +{diff}%p — 시장 대비 뚜렷한 강세"))
    elif diff >= 3:
        items.append(("positive", f"{label} 대비 상대강도 +{diff}%p — 시장 대비 강세"))
    elif diff >= -3:
        items.append(("neutral", f"{label} 대비 상대강도 {diff}%p — 시장과 유사"))
    else:
        items.append(("negative", f"{label} 대비 상대강도 {diff}%p — 시장 대비 약세"))

    return {"score": score, "items": items, "stock_return": stock_ret,
            "index_return": idx_ret, "market_label": label}


def _score_risk_reward(b: float, tech: dict) -> dict:
    # b = 1차 목표 수익률 ÷ 손절폭. 1차 목표는 보수적인 실전 익절 기준(기본 10%대)이라
    # 손절폭(6~11%)과 비교하면 자연스럽게 1.0 안팎으로 나온다 — 과거 코드가 "최종 목표"(30%대)를
    # 기준으로 삼던 시절의 임계값(2.5/1.8/1.2)을 그대로 쓰면 항상 낮은 점수만 나오므로,
    # 1차 목표 기준 손익비의 실제 분포에 맞춰 하향 재조정했다.
    score = 50
    items = []

    if b >= 1.5:
        score += 25; items.append(("positive", f"손익비 {b} — 1차 목표 대비 손절폭이 작아 우수"))
    elif b >= 1.1:
        score += 15; items.append(("positive", f"손익비 {b} — 양호"))
    elif b >= 0.8:
        score += 5;  items.append(("neutral", f"손익비 {b} — 보통"))
    else:
        score -= 15; items.append(("negative", f"손익비 {b} — 1차 목표 대비 손절폭이 커 불리"))

    high = tech.get("high_52w")
    low  = tech.get("low_52w")
    range_pct = None
    if high and low and low > 0:
        range_pct = round((high - low) / low * 100, 1)
        if range_pct > 100:
            score -= 10; items.append(("negative", f"52주 변동폭 {range_pct}% — 변동성 매우 큼"))
        elif range_pct > 60:
            score -= 3;  items.append(("neutral", f"52주 변동폭 {range_pct}% — 변동성 다소 큼"))
        else:
            items.append(("neutral", f"52주 변동폭 {range_pct}% — 변동성 보통"))

    return {"score": max(0, min(100, score)), "items": items, "range_pct": range_pct}


# ──────────────────────────────────────────
# 등급 / Kelly Score → 투자비중
# ──────────────────────────────────────────

def _grade_label(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B+"
    if score >= 60: return "B"
    if score >= 50: return "C"
    return "D"


#
# 임계값 근거: 실제 시가총액 상위 20개 종목(삼성전자·SK하이닉스·NAVER·카카오·현대차 등)을
# 스크리닝한 결과 Kelly Score 분포가 대략 50~75점 사이에 몰려 있고 75점을 넘는 종목이
# 하나도 없었다. 원래 기준(95/90/85/80/75)은 이 분포와 맞지 않아 항상 "관망"만 나오는
# 문제가 있었으므로, 관측된 분포의 상위 구간에 맞춰 하향 재조정했다.
KELLY_BRACKETS = [
    (78, "★★★★★", 50, "강력매수"),
    (74, "★★★★☆", 40, "매수(적극)"),
    (70, "★★★★",  30, "매수"),
    (65, "★★★☆",  20, "매수(소극)"),
    (60, "★★★",   10, "분할 소량매수"),
    (0,  "—",       0, "관망"),
]


def _kelly_bracket(score: float) -> dict:
    for min_s, stars, pct, label in KELLY_BRACKETS:
        if score >= min_s:
            return {"stars": stars, "position_pct": pct, "label": label}
    return {"stars": "—", "position_pct": 0, "label": "관망"}


# ──────────────────────────────────────────
# 분할매수 (1~3차)
# ──────────────────────────────────────────

def _derive_split_buy_plan(tech: dict, s_res: dict, current_price: float, budget: float) -> dict:
    ma20  = tech.get("current_ma20")
    ma60  = tech.get("current_ma60")
    resistance_levels = tech.get("resistance_levels") or []
    support_levels = tech.get("support_levels") or []

    nearest_resistance = resistance_levels[0] if resistance_levels else tech.get("high_52w")
    nearest_support = support_levels[0] if support_levels else ma20

    near_support = bool(nearest_support and current_price and abs(current_price - nearest_support) / current_price <= 0.03)
    near_resistance = bool(nearest_resistance and current_price and (nearest_resistance - current_price) / current_price <= 0.02)
    supply_positive = s_res.get("score", 50) >= 60

    if near_resistance and not near_support:
        ratios = [0.20, 0.30, 0.50]
        reason = f"저항선({round(nearest_resistance):,}원) 근접 구간 — 돌파 실패 시 되돌림 위험이 있어 초기 비중을 낮추고 지지선 확인 후 대응합니다."
    elif near_support and supply_positive:
        ratios = [0.45, 0.30, 0.25]
        reason = f"지지선({round(nearest_support):,}원) 근접 + 수급 우호적 — 초기 비중을 높여 대응합니다."
    else:
        ratios = [0.30, 0.35, 0.35]
        reason = "뚜렷한 지지/저항 근접 신호 없는 박스권/중립 구간 — 3회에 걸쳐 균등하게 분할매수합니다."

    p1 = current_price
    p2 = round(min(nearest_support or ma20 or current_price * 0.95, current_price * 0.97, p1))
    second_support = support_levels[1] if len(support_levels) > 1 else None
    p3 = round(min(second_support or ma60 or current_price * 0.90, p2 * 0.99))

    # 회차별 배분금이 해당 회차 가격보다 작아 1주도 못 사는 경우가 있다(예산이 작을 때).
    # 비율대로 쪼개서 0주가 나오더라도, 아직 쓰지 않은 예산으로 1주라도 살 수 있으면 사도록
    # 남은 예산을 다음 회차로 이월(top-up)한다 — 안 그러면 "10% 매수" 추천인데 3회 모두 0주가
    # 되는, 실제로는 매수 불가능한 계획이 나온다.
    stages = []
    total_qty = 0
    total_cost = 0.0
    remaining = budget
    for i, (ratio, price) in enumerate(zip(ratios, [p1, p2, p3])):
        allocated = budget * ratio
        qty = int(allocated / price) if price > 0 else 0
        if qty == 0 and price > 0 and remaining >= price:
            qty = 1
        actual = qty * price
        remaining -= actual
        stages.append({
            "round": i + 1,
            "price": round(price),
            "ratio_pct": round(ratio * 100),
            "allocated": round(allocated),
            "qty": qty,
            "actual": round(actual),
        })
        total_qty += qty
        total_cost += actual

    avg_price = round(total_cost / total_qty) if total_qty > 0 else 0

    reason_note = ""
    if total_qty > 0 and any(s["qty"] > 0 and s["allocated"] < s["actual"] for s in stages):
        reason_note = " (예산이 작아 일부 회차는 비율보다 실제 매수금액이 큽니다 — 남은 예산에서 1주를 우선 배정)"

    return {
        "reason": reason + reason_note,
        "stages": stages,
        "total_qty": total_qty,
        "total_cost": round(total_cost),
        "avg_price": avg_price,
        "insufficient": total_qty == 0,
    }


# ──────────────────────────────────────────
# 상승 시 추가매수 (불타기)
# ──────────────────────────────────────────

def _check_pyramid_conditions(tech: dict, frgn: list, quote: dict, tv_res: dict) -> dict:
    vol = tech.get("volume") or []
    vol_ma20 = tech.get("vol_ma20") or []
    support_levels = tech.get("support_levels") or []
    current = tech.get("current")

    # 최근 저항선이 지지선으로 바뀌어 있으면(=현재가 바로 아래 지지 레벨이 있으면) 직전에
    # 그 저항을 돌파했다는 뜻 — 단순히 52주 고점 근접보다 더 정확한 "돌파" 판정
    broke_resistance = bool(
        current and support_levels and (current - support_levels[0]) / current <= 0.02
    )

    r3 = frgn[:3] if frgn else []
    f3 = sum(d["foreign_net"] for d in r3) if r3 else 0
    i3 = sum(d["institution_net"] for d in r3) if r3 else 0

    conditions = [
        ("거래대금 증가", bool(tv_res.get("ratio") and tv_res["ratio"] >= 1.5)),
        ("외국인 순매수 지속", f3 > 0),
        ("기관 순매수 지속", i3 > 0),
        ("저항선(전고점) 돌파", broke_resistance),
        ("거래량 증가", bool(vol and vol_ma20 and vol_ma20[-1] and vol[-1] > vol_ma20[-1] * 1.3)),
        ("정배열 유지(5>20>60)", bool(
            tech.get("current_ma5") and tech.get("current_ma20") and tech.get("current_ma60") and
            tech["current_ma5"] > tech["current_ma20"] > tech["current_ma60"]
        )),
    ]
    met = sum(1 for _, ok in conditions if ok)

    prev_close = None
    gap_pct = 0.0
    if quote and quote.get("price") is not None and quote.get("change_won") is not None:
        prev_close = quote["price"] - quote["change_won"]
        if prev_close and quote.get("open"):
            gap_pct = round((quote["open"] - prev_close) / prev_close * 100, 2)

    if gap_pct >= 3:
        verdict = "금지"
        detail = f"당일 갭상승 +{gap_pct}% — 갭상승 추격매수는 원칙적으로 금지합니다."
        add_pct = "0%"
    elif met >= 4:
        verdict = "가능"
        detail = f"{met}/6개 조건 충족 — 기존 보유금액의 15~20%까지 추가매수를 검토할 수 있습니다."
        add_pct = "15~20%"
    elif met >= 2:
        verdict = "조건부(소량)"
        detail = f"{met}/6개 조건만 충족 — 눌림목 확인 후 10% 이내 소량만 검토하세요."
        add_pct = "0~10%"
    else:
        verdict = "금지"
        detail = f"{met}/6개 조건 충족 — 추가매수 조건 미충족, 신규 비중 확대는 자제합니다."
        add_pct = "0%"

    return {"conditions": conditions, "met_count": met, "verdict": verdict,
            "detail": detail, "add_pct": add_pct, "gap_pct": gap_pct}


# ──────────────────────────────────────────
# 종목 유형 분류 + 손절가
# ──────────────────────────────────────────

def _classify_stock_type(fin: dict, tech: dict) -> dict:
    """종목 유형(우량주/성장주/고위험주) 분류 — 손절 기준(%) 자동 산정.
    avg_price(분할매수 평균단가)에 의존하지 않아 Kelly Score 계산 전에도 호출 가능."""
    market_cap = fin.get("market_cap")
    per = fin.get("per")
    op_margin = fin.get("operating_margin")
    high = tech.get("high_52w")
    low = tech.get("low_52w")
    range_pct = round((high - low) / low * 100, 1) if high and low else None

    is_loss = (per is not None and per < 0) or (op_margin is not None and op_margin < 0)
    is_small = market_cap is not None and market_cap < 300_000_000_000
    is_volatile = range_pct is not None and range_pct > 80

    if is_loss or is_small or is_volatile:
        stock_type, stop_range, stop_pct = "고위험주", "10~12%", 11
    elif market_cap and market_cap >= 5_000_000_000_000 and not is_loss:
        stock_type, stop_range, stop_pct = "우량주", "5~7%", 6
    else:
        stock_type, stop_range, stop_pct = "성장주", "7~10%", 8

    return {"stock_type": stock_type, "stop_range": stop_range, "stop_pct": stop_pct, "range_pct": range_pct}


def _compute_stop_price(tech: dict, avg_price: float, classify: dict) -> dict:
    """분할매수 평균단가가 확정된 뒤, 종목유형별 손절%와 최근 지지선 중 더 타이트한 값으로 손절가 확정"""
    stop_pct = classify["stop_pct"]
    stop_by_pct = avg_price * (1 - stop_pct / 100) if avg_price else 0
    support_candidates = [x for x in [
        tech.get("current_ma20"),
        min(tech["close"][-20:]) if len(tech.get("close", [])) >= 20 else None,
        (tech.get("support_levels") or [None])[0],
    ] if x]
    support_based = max(support_candidates) if support_candidates else None

    if support_based and avg_price and support_based < avg_price:
        stop_price = round(max(stop_by_pct, support_based))
    else:
        stop_price = round(stop_by_pct)

    return {
        **classify,
        "stop_price": stop_price,
        "reason": f"{classify['stock_type']} 분류(손절 기준 {classify['stop_range']}) — 퍼센트 기준가와 최근 지지선(20일 이평/저점/스윙저점) 중 더 타이트한 값을 적용",
    }


# ──────────────────────────────────────────
# 단계별 익절
# ──────────────────────────────────────────

def _take_profit_plan(avg_price: float, target_pct: float) -> dict:
    # 1차는 사용자가 입력한 목표 수익률을 그대로 사용하고, 2차/3차는 그 값을 기준으로
    # 배분해 재계산한다 (2배/3배) — 사용자가 지정한 숫자가 무시되지 않도록.
    t1_pct = target_pct
    t2_pct = target_pct * 2
    t3_pct = target_pct * 3

    return {
        "stage1": {"pct": t1_pct, "price": round(avg_price * (1 + t1_pct / 100)), "sell_pct": 30,
                   "note": "1차 목표(입력한 목표 수익률) 도달 시 보유물량의 30% 매도"},
        "stage2": {"pct": t2_pct, "price": round(avg_price * (1 + t2_pct / 100)), "sell_pct": 30,
                   "note": "2차 목표(1차의 2배) 도달 시 누적 60%까지 추가 매도"},
        "stage3": {"pct": t3_pct, "price": round(avg_price * (1 + t3_pct / 100)), "sell_pct": 40,
                   "note": "잔여 40%는 종가가 5일선 이탈하거나 MACD 데드크로스 발생 전까지 추세 추종 보유"},
    }


# ──────────────────────────────────────────
# 시나리오 / 결론 (규칙 기반 템플릿)
# ──────────────────────────────────────────

def _build_scenarios(current_price, tp_plan, stop_info, tv_res, split_plan) -> dict:
    support = split_plan["stages"][1]["price"] if len(split_plan["stages"]) > 1 else None
    bull = (
        f"거래대금이 20일 평균 대비 {tv_res.get('ratio') or '—'}배 이상으로 유지되고 외국인·기관 동반 순매수가 이어지면, "
        f"1차 목표가 {tp_plan['stage1']['price']:,}원을 우선 시도할 수 있습니다. "
        f"정배열이 유지되는 한 최종 목표 {tp_plan['stage3']['price']:,}원까지 홀딩 관점이 유효합니다."
    )
    neutral = (
        f"뚜렷한 방향성 없이 박스권 등락이 예상되며, {support:,}원 부근 눌림목에서 분할매수로 대응하는 것이 유효합니다. "
        f"방향성이 확인되기 전까지 신규 비중 확대는 자제하는 것이 합리적입니다."
    )
    bear = (
        f"손절가 {stop_info['stop_price']:,}원을 이탈하면 추가 하락 리스크가 커지므로 원칙대로 즉시 손절 대응이 필요합니다. "
        f"외국인·기관 동반 순매도가 이어지면 반등 시도도 제한적일 수 있습니다."
    )
    return {"bull": bull, "neutral": neutral, "bear": bear}


def _build_verdict(kelly_score: float, current_price: float) -> str:
    if kelly_score >= 85:
        return f"현재가 {current_price:,}원 기준 기대수익이 손절 리스크보다 커, 분할매수 관점에서 합리적인 진입 구간으로 판단됩니다."
    if kelly_score >= 75:
        return "기대수익 대비 리스크가 중립적인 수준이라, 소규모 분할매수로 대응할 수 있는 구간입니다."
    return "현재 지표상 기대수익 대비 리스크가 낮아, 지금 가격에서의 신규 진입은 관망하는 것이 합리적입니다."


# ──────────────────────────────────────────
# 메인 분석 함수
# ──────────────────────────────────────────

def analyze_stock(code: str, seed: float, current_price: float,
                  target_pct: float = 15.0) -> dict:

    with ThreadPoolExecutor(max_workers=8) as ex:
        f_tech   = ex.submit(get_technical_data, code)
        f_frgn   = ex.submit(get_frgn_data, code, 10)
        f_name   = ex.submit(get_stock_name, code)
        f_quote  = ex.submit(get_realtime_quote, code)
        f_naver  = ex.submit(get_naver_metrics, code)
        f_invest = ex.submit(get_investor_info, code)
        f_news   = ex.submit(get_news, code, 3)
        f_disc   = ex.submit(get_recent_disclosures, code, 3)

    tech   = f_tech.result()
    frgn   = f_frgn.result()
    name   = f_name.result()
    quote  = f_quote.result()
    naver  = f_naver.result()
    invest = f_invest.result()
    news   = f_news.result()
    disclosures = f_disc.result()

    fin = _merge_financial(naver)
    # 52주최고/최저는 m.stock API보다 사용자가 실제로 보는 finance.naver.com 페이지 기준으로 통일
    tech = apply_52w_override(tech, invest)
    # 컨센서스도 같은 페이지 값이 있으면 우선 사용 (없으면 m.stock 값으로 대체)
    consensus = invest if invest.get("target_price") else naver.get("consensus")

    # 현재가: 네이버 실시간 시세 → 기술적 데이터 종가 → 사용자 입력
    if not current_price or current_price <= 0:
        current_price = quote.get("price") or tech.get("current") or fin.get("current_price") or 0

    if not current_price:
        return {"name": name, "code": code, "error": "현재가를 조회할 수 없습니다. 종목코드를 확인하세요."}

    # ── 축별 점수 ──
    t_res    = _score_technical(tech)
    s_res    = _score_supply(frgn)
    f_res    = _score_fundamental(fin)
    cons_res = _score_consensus(consensus, current_price)
    tv_res   = _score_trading_value(tech, quote, fin.get("market_cap"))
    rel_res  = _score_relative_strength(tech)

    # 손절 기준을 먼저 자동 분류(우량주/성장주/고위험주)해 손익비(b) 계산에 사용
    stock_class = _classify_stock_type(fin, tech)
    b = round(target_pct / stock_class["stop_pct"], 3)
    rr_res = _score_risk_reward(b, tech)

    # ① 종목 적합성 등급
    grade_score = round(
        f_res["score"] * 0.35 + t_res["score"] * 0.20 + s_res["score"] * 0.20 +
        cons_res["score"] * 0.15 + tv_res["score"] * 0.10, 1
    )
    grade = _grade_label(grade_score)

    # ② Kelly Score
    kelly_score = round(
        t_res["score"] * 0.30 + s_res["score"] * 0.25 +
        rel_res["score"] * 0.20 + rr_res["score"] * 0.25, 1
    )
    bracket = _kelly_bracket(kelly_score)
    position_pct = bracket["position_pct"]
    budget = round(seed * position_pct / 100)

    # ④ 분할매수 (Kelly Score로 축소된 투자비중 기준 — 종합점수/의견에 연동됨)
    split_plan = _derive_split_buy_plan(tech, s_res, current_price, budget)

    # ④-2 분할매수 (시드 전액 기준 — 종합점수/Kelly 의견과 무관한 별도 참고표)
    # 주가가 비싼데 Kelly 비중이 낮으면(budget이 작으면) 위 표는 회차별 배분금이
    # 1주 가격보다도 작아 전부 0주가 되는 경우가 많다. "실시간 가격에 시드 전액을
    # 투입한다면"이라는 가정의 별도 표를 항상 함께 제공해 실제로 몇 주를 살 수
    # 있는지 확인할 수 있게 한다.
    full_seed_split_plan = _derive_split_buy_plan(tech, s_res, current_price, seed)

    # ⑤ 상승 시 추가매수(불타기)
    pyramid = _check_pyramid_conditions(tech, frgn, quote, tv_res)

    # ⑥ 손절가 (분할매수 평균단가 기준)
    avg_price = split_plan["avg_price"] or current_price
    stop_info = _compute_stop_price(tech, avg_price, stock_class)

    # ⑦ 단계별 익절
    tp_plan = _take_profit_plan(avg_price, target_pct)

    # ⑨ 시나리오 / 결론
    scenarios = _build_scenarios(current_price, tp_plan, stop_info, tv_res, split_plan)
    verdict = _build_verdict(kelly_score, current_price)

    # 핵심 이벤트
    events = {
        "earnings": get_next_earnings(code),
        "fomc": get_next_fomc(),
        "relative_strength": rel_res,
        "news": news,
        "disclosures": disclosures,
        "dart_key_missing": not has_dart_key(),
    }

    return {
        "name": name,
        "code": code,
        "current_price": current_price,
        "quote": quote,
        "seed": seed,
        "target_pct": target_pct,

        "grade": grade,
        "grade_score": grade_score,

        "kelly_score": kelly_score,
        "stars": bracket["stars"],
        "opinion": bracket["label"],
        "position_pct": position_pct,
        "budget": budget,

        "split_buy": split_plan,
        "full_seed_split_buy": full_seed_split_plan,
        "pyramid": pyramid,
        "stop": stop_info,
        "take_profit": tp_plan,
        "scenarios": scenarios,
        "verdict": verdict,
        "events": events,

        "scores": {
            "technical":   t_res,
            "supply":      s_res,
            "fundamental": f_res,
            "consensus":   cons_res,
            "trading_value": tv_res,
            "relative_strength": rel_res,
            "risk_reward": rr_res,
        },
        "fin_summary": {
            "revenue_growth":    fin.get("revenue_growth"),
            "operating_margin":  fin.get("operating_margin"),
            "debt_ratio":        fin.get("debt_ratio"),
            "per":               fin.get("per"),
            "pbr":               fin.get("pbr"),
            "roe":               fin.get("roe"),
            "market_cap":        fin.get("market_cap"),
        },
        "supply_summary": {
            "foreign_5d": s_res.get("f5", 0),
            "institution_5d": s_res.get("i5", 0),
        },
    }
