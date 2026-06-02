#!/usr/bin/env python3
"""
fetch_prices.py — VN Stock Intelligence
Lấy giá từ vnstock (VCI/TCBS) - đây là nguồn cho giá đúng
Thêm financial ratios từ TCBS
"""

import json, os, sys, time, math
from datetime import datetime, timedelta

OUTPUT_FILE  = 'prices.json'
HISTORY_DAYS = 90
TOP_N        = 200
SLEEP        = 0.5

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
    try:
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
    except Exception as e:
        print(f'  [ERROR] Listing: {e}')
        return []

# ── 2. Lịch sử giá từ vnstock (VCI ưu tiên) ──────────────────────────
def get_history(ticker):
    """Dùng vnstock VCI/TCBS - giá đúng đơn vị"""
    try:
        from vnstock import Quote
    except ImportError:
        return [], None

    for source in ['VCI', 'TCBS']:
        for attempt in range(2):  # retry 1 lần
            try:
                df = Quote(symbol=ticker, source=source).history(
                    start=days_ago(HISTORY_DAYS + 10),
                    end=today(),
                    interval='1D'
                )
                if df is not None and not df.empty:
                    records = []
                    for _, row in df.tail(HISTORY_DAYS).iterrows():
                        c = safe_float(row.get('close'))
                        if c and c > 0:
                            records.append({
                                'date':   str(row.get('time', '')).split()[0],
                                'open':   safe_float(row.get('open')),
                                'high':   safe_float(row.get('high')),
                                'low':    safe_float(row.get('low')),
                                'close':  c,
                                'volume': safe_float(row.get('volume')),
                            })
                    if records:
                        return records, source
                break  # empty df → không retry
            except Exception as e:
                msg = str(e).lower()
                if 'rate' in msg or 'limit' in msg or '429' in msg:
                    time.sleep(2)  # rate limit → chờ lâu hơn
                elif attempt == 0:
                    time.sleep(0.5)
    return [], None

# ── 3. Giá EOD hàng loạt (nhanh, không có history) ───────────────────
def get_eod_batch(tickers_without_history, existing):
    """Dùng TCBS batch API - không bị block từ GitHub Actions"""
    import requests
    results = {}
    syms = [t['ticker'] for t in tickers_without_history]

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
                price = safe_float(item.get('p') or item.get('lastPrice'))
                ref   = safe_float(item.get('r') or item.get('refPrice'))
                chg   = round((price-ref)/ref*100, 2) if price and ref and ref > 0 else None
                if t and price:
                    results[t] = {'price': price, 'changePct': chg,
                                  'volume': safe_float(item.get('vol')), 'date': today()}
        except Exception as e:
            print(f'  [WARN] TCBS batch {i//100}: {e}')

        # Fallback existing cho mã vẫn thiếu
        for sym in batch:
            if sym not in results and isinstance(existing.get(sym), dict) and existing[sym].get('price'):
                ex = existing[sym]
                results[sym] = {'price': ex.get('price'), 'changePct': ex.get('changePct'),
                                'date': ex.get('date', today())}
        time.sleep(0.2)

    print(f'  EOD: {len(results)} mã')
    return results

# ── Main ──────────────────────────────────────────────────────────────
def main():
    print(f'=== fetch_prices.py: {datetime.now()} ===')

    # Load existing để giữ lại ratios và data cũ
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            raw = json.load(open(OUTPUT_FILE))
            # Đọc đúng format {prices: {...}, updated: ..., count: ...}
            existing = raw.get('prices', raw)
            if not isinstance(existing, dict):
                existing = {}
            print(f'  Existing: {len(existing)} mã')
        except: pass

    # Danh sách mã
    tickers = get_all_tickers()
    if not tickers:
        print('Không lấy được danh sách mã — exit')
        sys.exit(1)

    ticker_map = {t['ticker']: t for t in tickers}

    # Lấy history cho top HOSE + watchlist
    print(f'Lấy lịch sử {HISTORY_DAYS} ngày...')

    # Watchlist từ user_data.json
    watchlist = []
    if os.path.exists('user_data.json'):
        try:
            ud = json.load(open('user_data.json'))
            watchlist = ud.get('watchlist', [])
            print(f'  Watchlist: {watchlist}')
        except: pass

    # Top HOSE theo volume từ existing
    hose_by_vol = sorted(
        [t['ticker'] for t in tickers if t['exchange'] == 'HOSE'],
        key=lambda t: existing.get(t, {}).get('volume', 0) or 0,
        reverse=True
    )[:TOP_N]

    history_tickers = list(set(hose_by_vol + watchlist))
    print(f'  Lấy history cho {len(history_tickers)} mã...')

    histories = {}
    success = 0
    for i, t in enumerate(history_tickers):
        records, src = get_history(t)
        if records:
            histories[t] = records
            success += 1
        if (i+1) % 30 == 0:
            print(f'  {i+1}/{len(history_tickers)} | ok={success}')
        time.sleep(SLEEP)

    print(f'  History: {success}/{len(history_tickers)} mã')

    # Lấy giá EOD cho các mã không có history
    no_history = [t for t in tickers if t['ticker'] not in histories]
    print(f'Lấy giá EOD cho {len(no_history)} mã còn lại...')
    eod_prices = get_eod_batch(no_history, existing)
    print(f'  EOD: {len(eod_prices)} mã')

    # Ghép kết quả
    print('Ghép dữ liệu...')
    result = {}
    for ticker_info in tickers:
        t = ticker_info['ticker']
        ex = existing.get(t, {})
        history = histories.get(t, [])

        # Giá từ vnstock history (đúng nhất)
        if history:
            last  = history[-1]
            prev  = history[-2] if len(history) > 1 else last
            price = last.get('close')
            chg   = round((last['close'] - prev['close']) / prev['close'] * 100, 2) if prev['close'] else None
            high52w = max(b['close'] for b in history if b.get('close'))
            low52w  = min(b['close'] for b in history if b.get('close'))
            vol   = last.get('volume')
        else:
            # Fallback: EOD batch hoặc existing
            eod = eod_prices.get(t, {})
            price   = eod.get('price')   or ex.get('price')
            chg     = eod.get('changePct') or ex.get('changePct')
            high52w = ex.get('high52w')
            low52w  = ex.get('low52w')
            vol     = ex.get('volume')

        result[t] = {
            'name':      ticker_info.get('name', ex.get('name', '')),
            'exchange':  ticker_info.get('exchange', ex.get('exchange', '')),
            'industry':  ticker_info.get('industry', ex.get('industry', '')),
            'price':     price,
            'changePct': chg,
            'high52w':   high52w,
            'low52w':    low52w,
            'volume':    vol,
            'date':      today(),
            # Giữ ratios từ lần chạy trước (fetch_ratios.py cập nhật)
            'pe':        ex.get('pe'),
            'pb':        ex.get('pb'),
            'roe':       ex.get('roe'),
            'eps':       ex.get('eps'),
            'divYield':  ex.get('divYield'),
            'marketCap': ex.get('marketCap'),
            'history':   history,
            'updatedAt': today(),
        }

    result = sanitize(result)

    output = {
        'prices':  result,
        'updated': today(),
        'count':   len(result),
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    has_price = sum(1 for v in result.values() if v.get('price'))
    print(f'\n=== Xong: {len(result)} mã | {has_price} có giá | {size_mb:.1f} MB ===')

if __name__ == '__main__':
    main()
