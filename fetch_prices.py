#!/usr/bin/env python3
"""
fetch_prices.py — VN Stock Intelligence
Nguồn: TCBS public API (không cần key, không bị rate limit từ GitHub Actions)
"""

import json, os, sys, time, math, requests
from datetime import datetime, timedelta

OUTPUT_FILE  = 'prices.json'
HISTORY_DAYS = 90
TOP_N        = 200
SLEEP        = 0.15

def today():
    return datetime.now().strftime('%Y-%m-%d')

def days_ago(n):
    return (datetime.now() - timedelta(days=n)).strftime('%Y-%m-%d')

def safe_float(v):
    try:
        f = float(v) if v is not None else None
        if f is None: return None
        return None if math.isnan(f) or math.isinf(f) else f
    except: return None

def sanitize(obj):
    if isinstance(obj, dict):  return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return None
    return obj

# ── 1. Danh sách mã ───────────────────────────────────────────────────
def get_all_tickers():
    """Lấy danh sách mã từ TCBS (không cần vnstock)"""
    tickers = []
    # TCBS có endpoint trả toàn bộ mã niêm yết
    try:
        r = requests.get(
            'https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/ticker-list',
            headers={'User-Agent': 'Mozilla/5.0'}, timeout=15
        )
        if r.ok:
            data = r.json()
            items = data if isinstance(data, list) else data.get('data', [])
            for item in items:
                sym = item.get('ticker', '')
                if sym:
                    tickers.append({
                        'ticker':   sym,
                        'name':     item.get('organName', item.get('companyName', '')),
                        'exchange': item.get('exchange', ''),
                        'industry': item.get('industryName', ''),
                    })
            print(f'  TCBS ticker list: {len(tickers)} mã')
            if tickers: return tickers
    except Exception as e:
        print(f'  [WARN] TCBS ticker list: {e}')

    # Fallback: vnstock listing (chỉ dùng listing, không lấy history)
    try:
        from vnstock import Listing
        for exchange in ['HOSE', 'HNX', 'UPCOM']:
            try:
                df = Listing().symbols_by_exchange(exchange=exchange, lang='vi')
                for _, row in df.iterrows():
                    tickers.append({
                        'ticker':   row.get('symbol', ''),
                        'name':     row.get('organ_name', ''),
                        'exchange': exchange,
                        'industry': row.get('icb_name3', ''),
                    })
            except: pass
        print(f'  vnstock listing: {len(tickers)} mã')
    except Exception as e:
        print(f'  [WARN] vnstock listing: {e}')

    return tickers

# ── 2. Giá real-time từ TCBS batch ───────────────────────────────────
def get_tcbs_prices(tickers):
    """TCBS second-tc-price — batch, nhanh, đúng đơn vị VND"""
    results = {}
    syms = [t['ticker'] for t in tickers]

    for i in range(0, len(syms), 100):
        batch = syms[i:i+100]
        try:
            r = requests.get(
                'https://apipubaws.tcbs.com.vn/stock-insight/v2/stock/second-tc-price',
                params={'tickers': ','.join(batch)},
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=15
            )
            items = r.json() if r.ok else []
            if not isinstance(items, list):
                items = items.get('data', [])
            for item in items:
                t = item.get('ticker', '')
                price = safe_float(item.get('p') or item.get('lastPrice') or item.get('close'))
                ref   = safe_float(item.get('r') or item.get('refPrice') or item.get('basicPrice'))
                vol   = safe_float(item.get('vol') or item.get('totalVolume'))
                chg   = round((price-ref)/ref*100, 2) if price and ref and ref > 0 else None
                if t and price:
                    results[t] = {'price': price, 'changePct': chg, 'volume': vol, 'date': today()}
        except Exception as e:
            print(f'  [WARN] TCBS price batch {i//100}: {e}')
        time.sleep(SLEEP)

    print(f'  TCBS prices: {len(results)} mã')
    return results

# ── 3. Lịch sử OHLCV từ TCBS (từng mã, top N) ───────────────────────
def get_tcbs_history(ticker):
    """TCBS history API — không qua vnstock, không rate limit"""
    try:
        # TCBS chart API
        to_ts   = int(datetime.now().timestamp())
        from_ts = int((datetime.now() - timedelta(days=HISTORY_DAYS+10)).timestamp())
        r = requests.get(
            f'https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/bars-long-term',
            params={'ticker': ticker, 'type': 'stock', 'resolution': 'D',
                    'from': from_ts, 'to': to_ts},
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=10
        )
        if not r.ok: return []
        d = r.json()
        times  = d.get('t', [])
        closes = d.get('c', [])
        opens  = d.get('o', [])
        highs  = d.get('h', [])
        lows   = d.get('l', [])
        vols   = d.get('v', [])
        records = []
        for i, ts in enumerate(times):
            c = safe_float(closes[i] if i < len(closes) else None)
            if c and c > 0:
                records.append({
                    'date':   datetime.fromtimestamp(ts).strftime('%Y-%m-%d'),
                    'open':   safe_float(opens[i]  if i < len(opens)  else None),
                    'high':   safe_float(highs[i]  if i < len(highs)  else None),
                    'low':    safe_float(lows[i]   if i < len(lows)   else None),
                    'close':  c,
                    'volume': safe_float(vols[i]   if i < len(vols)   else None),
                })
        return records[-HISTORY_DAYS:]
    except: return []

# ── Main ──────────────────────────────────────────────────────────────
def main():
    print(f'=== fetch_prices.py: {datetime.now()} ===')

    # Load existing
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            raw = json.load(open(OUTPUT_FILE))
            existing = raw.get('prices', raw)
            if not isinstance(existing, dict): existing = {}
            print(f'  Existing: {len(existing)} mã')
        except: pass

    # 1. Danh sách mã
    print('Bước 1: Danh sách mã...')
    tickers = get_all_tickers()
    if not tickers:
        print('Không lấy được danh sách mã — dùng existing')
        tickers = [{'ticker': k, 'name': v.get('name',''), 'exchange': v.get('exchange',''), 'industry': v.get('industry','')}
                   for k, v in existing.items() if isinstance(v, dict)]

    ticker_map = {t['ticker']: t for t in tickers}

    # 2. Giá real-time tất cả mã
    print('Bước 2: Giá real-time TCBS...')
    prices = get_tcbs_prices(tickers)

    # 3. Lịch sử top N HOSE + watchlist
    print(f'Bước 3: Lịch sử top {TOP_N} mã...')
    watchlist = []
    if os.path.exists('user_data.json'):
        try:
            ud = json.load(open('user_data.json'))
            watchlist = ud.get('watchlist', [])
        except: pass

    hose_by_vol = sorted(
        [t['ticker'] for t in tickers if 'HOSE' in t.get('exchange','').upper()],
        key=lambda t: prices.get(t, {}).get('volume', 0) or 0,
        reverse=True
    )[:TOP_N]

    history_tickers = list(set(hose_by_vol + watchlist))
    print(f'  {len(history_tickers)} mã cần history')

    histories = {}
    for i, t in enumerate(history_tickers):
        h = get_tcbs_history(t)
        if h: histories[t] = h
        if (i+1) % 50 == 0:
            print(f'  {i+1}/{len(history_tickers)} | ok={len(histories)}')
        time.sleep(SLEEP)

    print(f'  History: {len(histories)} mã')

    # 4. Ghép kết quả
    print('Bước 4: Ghép dữ liệu...')
    result = {}
    for ticker_info in tickers:
        t = ticker_info['ticker']
        ex = existing.get(t, {})
        if not isinstance(ex, dict): ex = {}

        price_data = prices.get(t, {})
        history    = histories.get(t, [])

        # Giá: TCBS real-time > existing
        price = price_data.get('price') or ex.get('price')
        chg   = price_data.get('changePct') if price_data.get('price') else ex.get('changePct')
        vol   = price_data.get('volume') or ex.get('volume')

        # 52w từ history
        if history:
            closes = [b['close'] for b in history if b.get('close')]
            high52w = max(closes) if closes else ex.get('high52w')
            low52w  = min(closes) if closes else ex.get('low52w')
        else:
            high52w = ex.get('high52w')
            low52w  = ex.get('low52w')

        result[t] = {
            'name':      ticker_info.get('name') or ex.get('name', ''),
            'exchange':  ticker_info.get('exchange') or ex.get('exchange', ''),
            'industry':  ticker_info.get('industry') or ex.get('industry', ''),
            'price':     price,
            'changePct': chg,
            'high52w':   high52w,
            'low52w':    low52w,
            'volume':    vol,
            'date':      today() if price_data.get('price') else ex.get('date', ''),
            # Giữ ratios
            'pe':        ex.get('pe'),
            'pb':        ex.get('pb'),
            'roe':       ex.get('roe'),
            'eps':       ex.get('eps'),
            'divYield':  ex.get('divYield'),
            'marketCap': ex.get('marketCap'),
            'history':   history or ex.get('history', []),
            'updatedAt': today(),
        }

    result = sanitize(result)
    output = {'prices': result, 'updated': today(), 'count': len(result)}

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

    has_price = sum(1 for v in result.values() if v.get('price'))
    size_mb   = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print(f'\n=== Xong: {len(result)} mã | {has_price} có giá | {size_mb:.1f} MB ===')

if __name__ == '__main__':
    main()
