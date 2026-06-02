#!/usr/bin/env python3
"""
fetch_prices.py — VN Stock Intelligence
Chạy hàng ngày 16h T2-T6: cập nhật giá EOD + lịch sử top 200 mã
Financial ratios lấy từ fetch_ratios.py (chạy riêng T7)
"""

import json, os, time, requests
from datetime import datetime, timedelta

OUTPUT_FILE  = 'prices.json'
HISTORY_DAYS = 90
TOP_N        = 200
SLEEP        = 0.2

def today():
    return datetime.now().strftime('%Y-%m-%d')

def days_ago(n):
    return (datetime.now() - timedelta(days=n)).strftime('%Y-%m-%d')

def safe_float(v):
    try: return float(v) if v is not None else None
    except: return None

# ── 1. Danh sách mã ───────────────────────────────────────────────────
def get_all_tickers():
    from vnstock import Listing
    tickers = []
    for exchange in ['HOSE', 'HNX', 'UPCOM']:
        try:
            df = Listing().symbols_by_exchange(exchange=exchange, lang='vi')
            for _, row in df.iterrows():
                tickers.append({
                    'ticker':   row.get('symbol', ''),
                    'name':     row.get('organ_name', row.get('organName', '')),
                    'exchange': exchange,
                    'industry': row.get('icb_name3', row.get('industryName', '')),
                })
        except Exception as e:
            print(f'  [WARN] Listing {exchange}: {e}')
    print(f'  Tổng {len(tickers)} mã')
    return tickers

# ── 2. Giá EOD toàn bộ ───────────────────────────────────────────────
def get_eod_prices(tickers):
    results = {}
    all_syms = [t['ticker'] for t in tickers]
    for i in range(0, len(all_syms), 200):
        batch = all_syms[i:i+200]
        codes = ','.join(batch)
        url = f'https://finfo-api.vndirect.com.vn/v4/stock_prices?q=code:{codes}&sort=date:desc&size=200'
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            seen = set()
            for item in r.json().get('data', []):
                code = item.get('code', '')
                if code and code not in seen:
                    seen.add(code)
                    results[code] = {
                        'price':     safe_float(item.get('close')),
                        'changePct': safe_float(item.get('pctChange')),
                        'open':      safe_float(item.get('open')),
                        'high':      safe_float(item.get('high')),
                        'low':       safe_float(item.get('low')),
                        'volume':    safe_float(item.get('nmVolume')),
                        'date':      item.get('date', today()),
                    }
        except Exception as e:
            print(f'  [WARN] EOD batch {i//200}: {e}')
        time.sleep(SLEEP)
    print(f'  Giá EOD: {len(results)} mã')
    return results

# ── 3. Lịch sử OHLCV top 200 mã ─────────────────────────────────────
def get_history(ticker):
    from vnstock import Quote
    for source in ['VCI', 'TCBS', 'MSN']:
        try:
            df = Quote(symbol=ticker, source=source).history(
                start=days_ago(HISTORY_DAYS + 10), end=today(), interval='1D'
            )
            if df is not None and not df.empty:
                records = []
                for _, row in df.tail(HISTORY_DAYS).iterrows():
                    records.append({
                        'date':   str(row.get('time', '')).split()[0],
                        'open':   safe_float(row.get('open')),
                        'high':   safe_float(row.get('high')),
                        'low':    safe_float(row.get('low')),
                        'close':  safe_float(row.get('close')),
                        'volume': safe_float(row.get('volume')),
                    })
                return records
        except: continue
    print(f'  [WARN] History {ticker}: all sources failed')
    return []

def calc_52w(history):
    if not history: return None, None
    prices = [b['close'] for b in history if b.get('close')]
    return (max(prices), min(prices)) if prices else (None, None)

# ── Main ──────────────────────────────────────────────────────────────
def main():
    print(f'=== fetch_prices.py: {datetime.now()} ===')

    # Load existing
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            existing = json.load(open(OUTPUT_FILE))
            print(f'  Existing: {len(existing)} mã')
        except: pass

    # Danh sách mã
    tickers = get_all_tickers()
    ticker_map = {t['ticker']: t for t in tickers}

    # Giá EOD (~2 phút)
    print('Bước 1: Giá EOD...')
    eod = get_eod_prices(tickers)

    # Top 200 HOSE theo volume để lấy history
    print(f'Bước 2: Lịch sử top {TOP_N} mã...')
    hose = [t['ticker'] for t in tickers if t['exchange'] == 'HOSE']
    top200 = sorted(hose, key=lambda t: eod.get(t, {}).get('volume', 0) or 0, reverse=True)[:TOP_N]

    # Thêm watchlist
    extra = []
    if os.path.exists('user_data.json'):
        try:
            ud = json.load(open('user_data.json'))
            extra = ud.get('watchlist', [])
        except: pass

    history_tickers = list(set(top200 + extra))
    print(f'  {len(history_tickers)} mã cần history')

    histories = {}
    for i, t in enumerate(history_tickers):
        h = get_history(t)
        if h: histories[t] = h
        if (i+1) % 20 == 0: print(f'  {i+1}/{len(history_tickers)}...')
        time.sleep(SLEEP)

    # Ghép kết quả
    print('Bước 3: Ghép dữ liệu...')
    result = {}
    for ticker_info in tickers:
        t = ticker_info['ticker']
        ex = existing.get(t, {})
        price_data = eod.get(t, {})
        history = histories.get(t) or ex.get('history', [])
        high52w, low52w = calc_52w(history)

        result[t] = {
            'name':     ticker_info.get('name', ex.get('name', '')),
            'exchange': ticker_info.get('exchange', ex.get('exchange', '')),
            'industry': ticker_info.get('industry', ex.get('industry', '')),
            'price':    price_data.get('price')    or ex.get('price'),
            'changePct':price_data.get('changePct')or ex.get('changePct'),
            'open':     price_data.get('open')     or ex.get('open'),
            'high':     price_data.get('high')     or ex.get('high'),
            'low':      price_data.get('low')      or ex.get('low'),
            'volume':   price_data.get('volume')   or ex.get('volume'),
            'date':     price_data.get('date', today()),
            'high52w':  high52w or ex.get('high52w'),
            'low52w':   low52w  or ex.get('low52w'),
            # Giữ ratios từ lần chạy trước (fetch_ratios.py cập nhật)
            'pe':       ex.get('pe'),
            'pb':       ex.get('pb'),
            'roe':      ex.get('roe'),
            'eps':      ex.get('eps'),
            'divYield': ex.get('divYield'),
            'marketCap':ex.get('marketCap'),
            'history':  history,
            'updatedAt':today(),
        }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print(f'\n=== Xong: {len(result)} mã, {size_mb:.1f} MB, {datetime.now()} ===')

if __name__ == '__main__':
    main()
