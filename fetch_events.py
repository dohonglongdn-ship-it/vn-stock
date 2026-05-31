#!/usr/bin/env python3
"""
VN Stock - Fetch Events
Chạy mỗi sáng 8h (GitHub Actions)
- Fetch sự kiện cổ tức, ĐHCĐ, chốt quyền cho tất cả mã trong watchlist
- Ghi vào events.json
- So sánh với lần trước → đánh dấu sự kiện mới
"""

import json, os, requests, datetime, base64
from pathlib import Path

OWNER    = "dohonglongdn-ship-it"
REPO     = "vn-stock"
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
EVENTS_FILE = "events.json"

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
    try: return json.loads(raw), d["sha"]
    except: return None, d["sha"]

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

def fetch_events_vndirect(ticker):
    """Fetch sự kiện từ VNDirect"""
    try:
        r = requests.get(
            f"https://finfo-api.vndirect.com.vn/v4/events?q=code:{ticker}&size=10&sort=eventDate:desc",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Origin": "https://www.vndirect.com.vn",
                "Referer": "https://www.vndirect.com.vn/"
            },
            timeout=10
        )
        if r.ok:
            d = r.json()
            if d.get("data"):
                return [{
                    "date":   e.get("eventDate") or e.get("exRightDate", ""),
                    "type":   e.get("eventName") or e.get("eventType", ""),
                    "detail": e.get("eventDesc") or str(e.get("ratio", "")),
                    "source": "vndirect"
                } for e in d["data"]]
    except Exception as e:
        print(f"    VNDirect error: {e}")

    # Fallback: CafeF
    try:
        now = datetime.date.today()
        r = requests.get(
            f"https://s.cafef.vn/Ajax/PageNew/DataHistory/HistoryEvent.ashx?Symbol={ticker}&PageIndex=1&PageSize=10",
            headers={"Referer": "https://cafef.vn/", "User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if r.ok:
            d = r.json()
            if d.get("Data"):
                return [{
                    "date":   e.get("Ngay", ""),
                    "type":   e.get("LoaiSuKien", ""),
                    "detail": e.get("NoiDung", ""),
                    "source": "cafef"
                } for e in d["Data"]]
    except Exception as e:
        print(f"    CafeF error: {e}")

    return []

def is_upcoming(date_str, days=30):
    """Kiểm tra sự kiện có trong vòng N ngày tới không"""
    if not date_str: return False
    try:
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"]:
            try:
                d = datetime.datetime.strptime(date_str[:10], fmt[:len(date_str[:10])])
                delta = (d.date() - datetime.date.today()).days
                return -7 <= delta <= days  # Bao gồm cả sự kiện trong 7 ngày qua
            except: continue
    except: pass
    return False

def main():
    print(f"=== VN Stock Events | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    if not GH_TOKEN:
        print("ERROR: GITHUB_TOKEN not set"); return

    # 1. Load watchlist
    user_data, _ = gh_get("user_data.json")
    watchlist = user_data.get("watchlist", []) if user_data else []
    if not watchlist:
        print("Watchlist empty"); return
    print(f"Watchlist: {watchlist}")

    # 2. Load events.json cũ
    old_events, events_sha = gh_get(EVENTS_FILE)
    old_map = {}
    if old_events:
        for ticker, data in old_events.get("events", {}).items():
            old_map[ticker] = {e["date"] + e["type"] for e in data.get("items", [])}

    # 3. Fetch sự kiện cho từng mã
    today = datetime.date.today().isoformat()
    all_events = {}
    new_events = []  # Sự kiện mới xuất hiện

    for ticker in watchlist:
        print(f"  Fetching {ticker}...")
        events = fetch_events_vndirect(ticker)
        upcoming = [e for e in events if is_upcoming(e["date"])]
        print(f"    → {len(events)} events, {len(upcoming)} upcoming")

        # Detect sự kiện mới
        old_keys = old_map.get(ticker, set())
        for e in upcoming:
            key = e["date"] + e["type"]
            if key not in old_keys:
                new_events.append({"ticker": ticker, **e})

        all_events[ticker] = {
            "items": upcoming,
            "updatedAt": today
        }

    # 4. Ghi events.json
    output = {
        "updatedAt": today,
        "newEvents": new_events,
        "events": all_events
    }

    try:
        if events_sha:
            gh_put(EVENTS_FILE, output, events_sha,
                   f"📅 Events update {today} ({len(new_events)} new)")
        else:
            gh_create(EVENTS_FILE, output,
                      f"📅 Events init {today}")
        print(f"✅ events.json updated | {len(new_events)} new events")
        if new_events:
            for e in new_events:
                print(f"   🔔 {e['ticker']}: {e['type']} - {e['date']}")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    main()
