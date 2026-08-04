"""
DART(전자공시시스템) OpenAPI — 최근 공시 목록 조회

무료 API 키 발급: https://opendart.fss.or.kr (회원가입 → 인증키 신청)
.env 파일에 DART_API_KEY=발급받은키 형태로 저장하면 자동으로 사용됨.
키가 없으면 빈 목록을 반환하고, 화면에는 "DART API 키 미설정"으로 안내한다.
"""

import os
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

CORP_CODE_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "dart_corp_codes.json")


def _get_api_key() -> str:
    return os.environ.get("DART_API_KEY", "").strip()


def has_api_key() -> bool:
    return bool(_get_api_key())


def _load_corp_code_map() -> dict:
    """stock_code -> corp_code 매핑을 캐시 파일에서 읽거나, 없으면 DART에서 내려받아 생성"""
    if os.path.exists(CORP_CODE_CACHE):
        try:
            with open(CORP_CODE_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    api_key = _get_api_key()
    if not api_key:
        return {}

    try:
        resp = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": api_key},
            timeout=30,
        )
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_bytes = zf.read("CORPCODE.xml")

        root = ET.fromstring(xml_bytes)
        mapping = {}
        for item in root.findall("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            corp_code = (item.findtext("corp_code") or "").strip()
            if stock_code:
                mapping[stock_code] = corp_code

        os.makedirs(os.path.dirname(CORP_CODE_CACHE), exist_ok=True)
        with open(CORP_CODE_CACHE, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False)

        return mapping
    except Exception:
        return {}


def get_recent_disclosures(stock_code: str, limit: int = 5) -> list:
    api_key = _get_api_key()
    if not api_key:
        return []

    corp_map = _load_corp_code_map()
    corp_code = corp_map.get(stock_code)
    if not corp_code:
        return []

    end_de = datetime.now().strftime("%Y%m%d")
    bgn_de = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

    try:
        resp = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "page_count": limit,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("status") != "000":
            return []

        result = []
        for item in data.get("list", [])[:limit]:
            rcept_no = item.get("rcept_no", "")
            result.append({
                "date":  item.get("rcept_dt", ""),
                "title": item.get("report_nm", ""),
                "url":   f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
            })
        return result
    except Exception:
        return []
