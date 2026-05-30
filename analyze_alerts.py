#!/usr/bin/env python3
"""
VN Stock - AI Alert Analyzer
Chạy 3 lần/ngày: 8h, 13h, 21h (giờ VN)
- Đọc watchlist từ user_data.json
- Tính TA: RSI, MACD, MA
- Gọi Groq AI phân tích + đưa khuyến cáo
- Ghi kết quả vào alerts_ai.json
"""

import os, json, requests, base64, datetime, time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────
OWNER      = "dohonglongdn-ship-it"
REPO       = "vn-stock"
GROQ_KEY   = os.environ.get("GROQ_API_KEY", "")
GH_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
VN_TZ_OFFSET = 7  # UTC+7

def vn_hour():
    return (datetime.datetime.utcnow().hour + VN_TZ_OFFSET) % 24

def session_label():
    h = vn_hour()
    if h < 10:   return "morning"   # 8h - trước mở cửa
    elif h < 15: return "midday"    # 13h - giữa phiên
    else:        return "evening"   # 21h - sau đóng cửa

# ── GitHub helpers ────────────────────────────────────────────────────
def gh_get(path):
    r = requests.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"},
        timeout=15
    )
    if r.status_code == 404: return None, None
    r.raise_for_status()
    d = r.json()
    raw = base64.b64decode(d["content"]).decode("utf-8").strip()
    if not raw: return None, d["sha"]
    try:
        return json.loads(raw), d["sha"]
    except json.JSONDecodeError:
        print(f"  WARNING: {path} has invalid JSON, treating as empty")
        return None, d["sha"]

def gh_put(path, content_dict, sha, message):
    body = json.dumps(content_dict, ensure_ascii=False, indent=2)
    payload = {
        "message": message,
        "content": base64.b64encode(body.encode("utf-8")).decode("utf-8"),
        "sha": sha
    }
    r = requests.put(
        f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"},
        json=payload, timeout=15
    )
    r.raise_for_status()
    return r.json()["content"]["sha"]

def gh_create(path, content_dict, message):
    body = json.dumps(content_dict, ensure_ascii=False, indent=2)
    payload = {
        "message": message,
        "content": base64.b64encode(body.encode("utf-8")).decode("utf-8"),
    }
    r = requests.put(
        f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"},
        json=payload, timeout=15
    )
    r.raise_for_status()

# ── Load prices.json ──────────────────────────────────────────────────
def load_prices():
    r = requests.get(
        f"https://raw.githubusercontent.com/{OWNER}/{REPO}/main/prices.json",
        timeout=15
    )
    r.raise_for_status()
    return r.json().get("prices", {})

# ── Technical Analysis ────────────────────────────────────────────────
def sma(arr, n):
    if len(arr) < n: return None
    return sum(arr[-n:]) / n

def ema(arr, n):
    if len(arr) < n: return None
    k = 2 / (n + 1)
    e = arr[0]
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return e

def rsi(closes, period=14):
    if len(closes) < period + 1: return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100
    rs = ag / al
    return round(100 - 100 / (1 + rs), 1)

def macd_signal(closes):
    if len(closes) < 35: return None, None
    ema12 = ema(closes[-50:], 12)
    ema26 = ema(closes[-50:], 26)
    if not ema12 or not ema26: return None, None
    macd_line = ema12 - ema26
    # Signal = EMA9 của MACD (simplified: dùng đường MACD so với 0)
    return round(macd_line, 2), round(ema12 - ema26, 2)

def compute_ta(history):
    if not history or len(history) < 20:
        return {}
    closes = [h["close"] for h in history if h.get("close")]
    if len(closes) < 20:
        return {}
    cur = closes[-1]
    ma20 = sma(closes, 20)
    ma50 = sma(closes, min(50, len(closes)))
    rsi14 = rsi(closes)
    macd_v, _ = macd_signal(closes)

    # Trend
    trend = "up" if ma20 and cur > ma20 else "down"

    # RSI signal
    rsi_signal = "oversold" if rsi14 and rsi14 < 30 else "overbought" if rsi14 and rsi14 > 70 else "neutral"

    # MA cross (5 ngày gần nhất)
    ma_cross = None
    if len(closes) >= 21 and ma50:
        prev_ma20 = sma(closes[:-1], 20)
        if prev_ma20 and prev_ma20 < ma50 and ma20 and ma20 > ma50:
            ma_cross = "golden"   # MA20 cắt lên MA50
        elif prev_ma20 and prev_ma20 > ma50 and ma20 and ma20 < ma50:
            ma_cross = "death"    # MA20 cắt xuống MA50

    # Giá so với 52w
    high52 = max(closes[-min(252, len(closes)):])
    low52  = min(closes[-min(252, len(closes)):])
    pct_from_high = round((cur - high52) / high52 * 100, 1)

    return {
        "price": cur,
        "ma20": round(ma20, 0) if ma20 else None,
        "ma50": round(ma50, 0) if ma50 else None,
        "rsi": rsi14,
        "macd": macd_v,
        "trend": trend,
        "rsi_signal": rsi_signal,
        "ma_cross": ma_cross,
        "high52": high52,
        "low52": low52,
        "pct_from_high": pct_from_high,
    }

def rule_signal(ta, chg_pct):
    """Rule cứng → BUY / SELL / WATCH / HOLD"""
    if not ta: return "HOLD", "low"
    score = 0
    reasons = []

    if ta.get("rsi_signal") == "oversold":
        score += 2; reasons.append("RSI quá bán")
    elif ta.get("rsi_signal") == "overbought":
        score -= 2; reasons.append("RSI quá mua")

    if ta.get("ma_cross") == "golden":
        score += 2; reasons.append("MA20 cắt lên MA50 (golden cross)")
    elif ta.get("ma_cross") == "death":
        score -= 2; reasons.append("MA20 cắt xuống MA50 (death cross)")

    if ta.get("trend") == "up":
        score += 1; reasons.append("Xu hướng tăng")
    else:
        score -= 1; reasons.append("Xu hướng giảm")

    if ta.get("macd") and ta["macd"] > 0:
        score += 1; reasons.append("MACD dương")
    elif ta.get("macd") and ta["macd"] < 0:
        score -= 1; reasons.append("MACD âm")

    if chg_pct and chg_pct < -5:
        score -= 1; reasons.append(f"Giảm mạnh {chg_pct:.1f}% hôm nay")
    elif chg_pct and chg_pct > 5:
        score += 1; reasons.append(f"Tăng mạnh {chg_pct:.1f}% hôm nay")

    if score >= 3:   return "BUY",   "high",   reasons
    elif score >= 1: return "WATCH", "medium", reasons
    elif score <= -3: return "SELL", "high",   reasons
    elif score <= -1: return "HOLD", "medium", reasons
    else:             return "HOLD", "low",    reasons

# ── Groq AI explanation ───────────────────────────────────────────────
def groq_explain(ticker, name, ta, signal, confidence, rule_reasons, session, market_ctx=""):
    prompt = f"""Phân tích cổ phiếu VN cho nhà đầu tư cá nhân. Trả về JSON.

Mã: {ticker} ({name})
Phiên: {session} {"(trước mở cửa)" if session=="morning" else "(giữa phiên)" if session=="midday" else "(sau đóng cửa - dự báo ngày mai)"}
Tín hiệu kỹ thuật (rule-based): {signal} | Độ tin cậy: {confidence}
Lý do rule: {", ".join(rule_reasons) if rule_reasons else "Không rõ ràng"}
Dữ liệu TA:
- Giá hiện tại: {ta.get("price")} | MA20: {ta.get("ma20")} | MA50: {ta.get("ma50")}
- RSI(14): {ta.get("rsi")} ({ta.get("rsi_signal")}) | MACD: {ta.get("macd")}
- Cách đỉnh 52 tuần: {ta.get("pct_from_high")}%
{f"Bối cảnh thị trường: {market_ctx}" if market_ctx else ""}

Trả về JSON (KHÔNG có text ngoài JSON):
{{
  "action": "MUA|BÁN|THEO DÕI|GIỮ",
  "summary": "1 câu ngắn gọn lý do chính (tối đa 15 từ)",
  "detail": "Phân tích 2-3 câu: TA + bối cảnh + rủi ro",
  "entry": "Vùng giá nên mua (nếu MUA/THEO DÕI, không thì null)",
  "stoploss": "Mức cắt lỗ đề xuất (nếu có, không thì null)",
  "timeframe": "Ngắn hạn|Trung hạn|Dài hạn"
}}"""

    try:
        r = requests.post(GROQ_URL, json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "Bạn là chuyên gia phân tích kỹ thuật chứng khoán VN. Trả lời bằng JSON thuần túy, không markdown."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 400,
            "response_format": {"type": "json_object"}
        }, headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}, timeout=20)
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"  Groq error for {ticker}: {e}")
        return {
            "action": {"BUY":"MUA","SELL":"BÁN","WATCH":"THEO DÕI"}.get(signal, "GIỮ"),
            "summary": ", ".join(rule_reasons[:2]) if rule_reasons else "Không đủ dữ liệu",
            "detail": "Phân tích dựa trên chỉ số kỹ thuật.",
            "entry": None, "stoploss": None, "timeframe": "Ngắn hạn"
        }

# ── Main ──────────────────────────────────────────────────────────────
def main():
    print(f"=== VN Stock AI Analyzer | {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC ===")
    session = session_label()
    print(f"Session: {session} (VN hour: {vn_hour()}h)")

    if not GROQ_KEY:
        print("ERROR: GROQ_API_KEY not set"); return
    if not GH_TOKEN:
        print("ERROR: GITHUB_TOKEN not set"); return

    # 1. Load watchlist
    user_data, _ = gh_get("user_data.json")
    watchlist = user_data.get("watchlist", []) if user_data else []
    if not watchlist:
        print("Watchlist empty, skip"); return
    print(f"Watchlist: {watchlist}")

    # 2. Load prices.json
    prices = load_prices()
    print(f"Prices loaded: {len(prices)} mã")

    # 3. Load alerts_ai.json hiện tại (nếu có)
    existing_alerts, alerts_sha = gh_get("alerts_ai.json")
    if not existing_alerts:
        existing_alerts = {}

    # 4. Phân tích từng mã
    results = {}
    for ticker in watchlist:
        print(f"  Analyzing {ticker}...")
        p = prices.get(ticker, {})
        history = p.get("history", [])
        chg_pct = p.get("changePct")
        name = p.get("name", ticker)
        ta = compute_ta(history)

        if not ta:
            print(f"    → Not enough data")
            results[ticker] = {
                "ticker": ticker, "name": name,
                "signal": "HOLD", "confidence": "low",
                "action": "GIỮ", "summary": "Không đủ dữ liệu lịch sử",
                "detail": "", "entry": None, "stoploss": None,
                "timeframe": "Ngắn hạn", "ta": {},
                "session": session, "updatedAt": datetime.datetime.utcnow().isoformat()
            }
            continue

        signal, confidence, rule_reasons = rule_signal(ta, chg_pct)
        print(f"    → Rule: {signal} ({confidence}) | RSI:{ta.get('rsi')} MA:{ta.get('trend')}")

        ai = groq_explain(ticker, name, ta, signal, confidence, rule_reasons, session)
        time.sleep(0.5)  # Rate limit

        results[ticker] = {
            "ticker": ticker,
            "name": name,
            "signal": signal,
            "confidence": confidence,
            "rule_reasons": rule_reasons,
            "action": ai.get("action", "GIỮ"),
            "summary": ai.get("summary", ""),
            "detail": ai.get("detail", ""),
            "entry": ai.get("entry"),
            "stoploss": ai.get("stoploss"),
            "timeframe": ai.get("timeframe", "Ngắn hạn"),
            "ta": ta,
            "session": session,
            "updatedAt": datetime.datetime.utcnow().isoformat()
        }
        print(f"    → AI: {ai.get('action')} | {ai.get('summary','')[:50]}")

    # 5. Ghi alerts_ai.json
    output = {
        "updatedAt": datetime.datetime.utcnow().isoformat(),
        "session": session,
        "alerts": results
    }

    try:
        if alerts_sha:
            gh_put("alerts_ai.json", output, alerts_sha,
                   f"🤖 AI alerts update [{session}] {datetime.date.today()}")
        else:
            gh_create("alerts_ai.json", output,
                      f"🤖 AI alerts init [{session}] {datetime.date.today()}")
        print(f"✅ alerts_ai.json updated ({len(results)} mã)")
    except Exception as e:
        print(f"ERROR writing alerts_ai.json: {e}")

if __name__ == "__main__":
    main()
