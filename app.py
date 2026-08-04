from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, jsonify, request
import yfinance as yf

from services.market_data import get_market_data
from services.naver_scraper import (
    get_frgn_data, get_stock_name, get_realtime_quote, search_stock_code, get_investor_info,
)
from services.technical import get_technical_data, apply_52w_override
from services.kelly_analyzer import analyze_stock

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # 정적 파일 캐시 비활성화


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stock/resolve")
def stock_resolve():
    q = request.args.get("q", "")
    result = search_stock_code(q)
    if not result:
        return jsonify({"code": None, "name": None}), 404
    return jsonify(result)


@app.route("/api/market")
def market():
    return jsonify(get_market_data())


@app.route("/api/stock/<code>/frgn")
def frgn(code):
    name = get_stock_name(code)
    data = get_frgn_data(code)
    return jsonify({"code": code, "name": name, "data": data})


@app.route("/api/stock/<code>/volume")
def volume(code):
    for suffix in [".KS", ".KQ"]:
        try:
            t = yf.Ticker(code + suffix)
            hist = t.history(period="1mo")
            if not hist.empty:
                data = []
                for dt, row in hist.iterrows():
                    data.append({
                        "date": dt.strftime("%m/%d"),
                        "volume": int(row["Volume"]),
                        "close": round(float(row["Close"]), 0)
                    })
                return jsonify({"code": code, "data": data})
        except Exception:
            continue

    return jsonify({"code": code, "data": []})


@app.route("/api/stock/<code>/technical")
def technical(code):
    data = get_technical_data(code)
    quote = get_realtime_quote(code)
    investor_info = get_investor_info(code)
    data = apply_52w_override(data, investor_info)
    if quote:
        data["current"] = quote.get("price", data.get("current"))
        data["trading_value_text"] = quote.get("trading_value_text")
        data["market_status"] = quote.get("market_status")
        data["trade_datetime"] = quote.get("trade_datetime")
    return jsonify({"code": code, "data": data})


@app.route("/api/kelly/analyze", methods=["POST"])
def kelly_analyze():
    body = request.get_json(force=True)
    result = analyze_stock(
        code=body.get("code", ""),
        seed=float(body.get("seed", 10_000_000)),
        current_price=float(body.get("current_price", 0)),
        target_pct=float(body.get("target_pct", 15)),
    )
    return jsonify(result)


if __name__ == "__main__":
    print("=" * 50)
    print("한국 주식 대시보드 서버 시작")
    print("브라우저에서 http://localhost:5000 접속")
    print("종료하려면 Ctrl+C")
    print("=" * 50)
    app.run(debug=False, host="0.0.0.0", port=5000)
