#!/usr/bin/env python3
"""
VN Stock - Fetch Prices (version gốc đang hoạt động)
Cập nhật hàng ngày lúc 16h (GitHub Actions)
- Lấy giá tất cả mã niêm yết từ vnstock board
- Lưu history 60 ngày cho top 200 mã HOSE
- Format: {updated, count, prices: {ticker: {price, changePct, history?, ...}}}
"""

import json, os, sys, time, math
from datetime import datetime, timedelta
from pathlib import Path

OUTPUT_FILE = 'prices.json'

def get_today():
    return datetime.now().strftime('%Y-%m-%d')

def get_from_date(days=400):
    return (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

def safe_float(v):
    try:
        f = float(v) if v is not None else None
        if f is None: return None
        return None if math.isnan(f) or math.isinf(f) else f
    except: return None

def sanitize(obj):
    if isinstance(obj, dict): return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list): return [sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return None
    return obj

print(f"=== fetch_prices.py bắt đầu: {datetime.now()} ===")

try:
    from vnstock import Vnstock
    print("✅ vnstock loaded")
except ImportError as e:
    print(f"❌ vnstock import failed: {e}")
    sys.exit(1)

# ── 1. Lấy danh sách tất cả mã ───────────────────────────────────────
def get_all_symbols():
    symbols = []
    for exchange in ['HOSE', 'HNX', 'UPCOM']:
        try:
            stock = Vnstock().stock(symbol='VCB', source='VCI')
            df = stock.listing.symbols_by_exchange(exchange=exchange)
            if df is not None and not df.empty:
                col = next((c for c in ['symbol','ticker','code'] if c in df.columns), None)
                if col:
                    for _, row in df.iterrows():
                        sym = str(row[col]).strip().upper()
                        if sym:
                            symbols.append({
                                'ticker':   sym,
                                'name':     str(row.get('organ_name', row.get('organName', ''))),
                                'exchange': exchange,
                                'industry': str(row.get('icb_name3', row.get('industryName', ''))),
                            })
                    print(f"  {exchange}: {len(df)} mã")
        except Exception as e:
            print(f"  [WARN] {exchange}: {e}")
    print(f"  Tổng: {len(symbols)} mã")
    return symbols

# ── 2. Lấy giá tất cả mã từ bảng giá VCI ────────────────────────────
def get_board_prices(symbols):
    """Lấy giá realtime từ VCI board — nhanh, 1 request cho tất cả"""
    prices = {}
    try:
        stock = Vnstock().stock(symbol='VCB', source='VCI')
        # Thử lấy bảng giá toàn thị trường
        for exchange in ['HOSE', 'HNX', 'UPCOM']:
            try:
                df = stock.trading.price_board(symbols_list=[
                    s['ticker'] for s in symbols if s['exchange'] == exchange
                ][:500])
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        t = str(row.get('symbol', row.get('ticker', ''))).upper()
                        close = safe_float(row.get('close') or row.get('match_price') or row.get('price'))
                        ref   = safe_float(row.get('ref_price') or row.get('reference'))
                        if t and close:
                            chg = round((close - ref) / ref * 100, 2) if ref and ref > 0 else None
                            prices[t] = {
                                'price':     close,
                                'changePct': chg,
                                'volume':    safe_float(row.get('match_volume') or row.get('volume')),
                            }
            except Exception as e:
                print(f"  [WARN] board {exchange}: {e}")
    except Exception as e:
        print(f"  [WARN] board prices: {e}")
    print(f"  Board prices: {len(prices)} mã")
    return prices

# ── 3. Lấy lịch sử cho top 200 mã ───────────────────────────────────
def get_history(ticker, days=60):
    """Lấy lịch sử OHLCV — thử VCI trước, TCBS fallback"""
    from_date = get_from_date(days + 10)
    today = get_today()
    for source in ['VCI', 'TCBS']:
        try:
            stock = Vnstock().stock(symbol=ticker, source=source)
            df = stock.quote.history(start=from_date, end=today, interval='1D')
            if df is not None and not df.empty and len(df) >= 10:
                records = []
                for _, row in df.tail(days).iterrows():
                    c = safe_float(row.get('close'))
                    if c and c > 0:
                        records.append({
                            'date':   str(row.get('time', row.name))[:10],
                            'open':   safe_float(row.get('open')),
                            'high':   safe_float(row.get('high')),
                            'low':    safe_float(row.get('low')),
                            'close':  c,
                            'volume': safe_float(row.get('volume')),
                        })
                if records:
                    return records
        except: continue
    return []

# ── 4. Lấy P/B, ROE, EPS từ vnstock financials ──────────────────────
def get_financials(ticker):
    """Lấy chỉ số tài chính — không bắt buộc, lỗi thì bỏ qua"""
    try:
        stock = Vnstock().stock(symbol=ticker, source='TCBS')
        df = stock.finance.ratio(period='quarter', lang='vi', dropna=True)
        if df is None or df.empty: return {}
        latest = df.iloc[-1]
        return {
            'pe':  safe_float(latest.get('P/E') or latest.get('pe')),
            'pb':  safe_float(latest.get('P/B') or latest.get('pb')),
            'roe': safe_float(latest.get('ROE') or latest.get('roe')),
            'eps': safe_float(latest.get('EPS') or latest.get('eps')),
        }
    except: return {}

# ── Main ─────────────────────────────────────────────────────────────
def main():
    # Load existing để giữ data
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            raw = json.load(open(OUTPUT_FILE))
            existing = raw.get('prices', {})
            if not isinstance(existing, dict): existing = {}
            print(f"  Existing: {len(existing)} mã")
        except: pass

    # 1. Danh sách mã
    print("Bước 1: Danh sách mã...")
    symbols = get_all_symbols()
    if not symbols:
        print("Không lấy được danh sách — dùng existing")
        symbols = [{'ticker': k, **{f: v.get(f,'') for f in ['name','exchange','industry']}}
                   for k, v in existing.items() if isinstance(v, dict)]

    # 2. Giá board (nhanh)
    print("Bước 2: Giá board...")
    board = get_board_prices(symbols)

    # 3. Watchlist từ user_data.json
    watchlist = []
    if os.path.exists('user_data.json'):
        try:
            ud = json.load(open('user_data.json'))
            watchlist = ud.get('watchlist', [])
        except: pass

    # Bổ sung: lấy giá trực tiếp từ TCBS cho watchlist (đảm bảo có giá đúng)
    if watchlist:
        import requests as req
        print(f"  TCBS price cho watchlist {watchlist}...")
        try:
            r = req.get(
                'https://apipubaws.tcbs.com.vn/stock-insight/v2/stock/second-tc-price',
                params={'tickers': ','.join(watchlist)},
                headers={'User-Agent': 'Mozilla/5.0'}, timeout=10
            )
            if r.ok:
                items = r.json() if isinstance(r.json(), list) else r.json().get('data', [])
                for item in items:
                    t = item.get('ticker', '')
                    price = safe_float(item.get('p') or item.get('lastPrice'))
                    ref   = safe_float(item.get('r') or item.get('refPrice'))
                    if t and price:
                        chg = round((price-ref)/ref*100, 2) if ref and ref > 0 else None
                        board[t] = {'price': price, 'changePct': chg,
                                    'volume': safe_float(item.get('vol')), 'source': 'tcbs'}
                        print(f"    TCBS {t}: {price:,.0f} ({chg:+.2f}%)" if chg else f"    TCBS {t}: {price:,.0f}")
        except Exception as e:
            print(f"  [WARN] TCBS watchlist: {e}")

    # Top 200 HOSE theo volume
    hose_syms = [s['ticker'] for s in symbols if s.get('exchange') == 'HOSE']
    top200 = sorted(hose_syms,
        key=lambda t: board.get(t, {}).get('volume') or existing.get(t, {}).get('volume') or 0,
        reverse=True)[:200]
    history_list = list(set(top200 + watchlist))
    print(f"Bước 3: Lịch sử {len(history_list)} mã...")

    histories = {}
    history_count = 0
    for i, t in enumerate(history_list):
        h = get_history(t)
        if h:
            histories[t] = h
            history_count += 1
        if (i + 1) % 30 == 0:
            print(f"  {i+1}/{len(history_list)} | ok={history_count}")
        time.sleep(0.4)
    print(f"  History xong: {history_count} mã")

    # 4. Ghép tất cả
    print("Bước 4: Ghép dữ liệu...")
    all_prices = {}
    sym_map = {s['ticker']: s for s in symbols}

    for s in symbols:
        t = s['ticker']
        ex = existing.get(t, {})
        if not isinstance(ex, dict): ex = {}
        bd = board.get(t, {})
        h  = histories.get(t, [])

        price = bd.get('price') or ex.get('price')
        chg   = bd.get('changePct') if bd.get('price') else ex.get('changePct')
        vol   = bd.get('volume') or ex.get('volume')

        closes = [b['close'] for b in h if b.get('close')]
        high52 = max(closes) if closes else ex.get('high52w')
        low52  = min(closes) if closes else ex.get('low52w')

        all_prices[t] = {
            'name':      s.get('name') or ex.get('name', ''),
            'exchange':  s.get('exchange') or ex.get('exchange', ''),
            'industry':  s.get('industry') or ex.get('industry', ''),
            'price':     price,
            'changePct': chg,
            'volume':    vol,
            'high52w':   high52,
            'low52w':    low52,
            'history':   h or ex.get('history', []),
            # Giữ ratios từ existing
            'pe':        ex.get('pe'),
            'pb':        ex.get('pb'),
            'roe':       ex.get('roe'),
            'eps':       ex.get('eps'),
            'divYield':  ex.get('divYield'),
            'marketCap': ex.get('marketCap'),
            'date':      get_today() if bd.get('price') else ex.get('date', ''),
            'updatedAt': get_today(),
        }

    all_prices = sanitize(all_prices)
    output = {
        'updated':        get_today(),
        'count':          len(all_prices),
        'top200_history': history_count,
        'prices':         all_prices,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    has_price = sum(1 for v in all_prices.values() if v.get('price'))
    print(f"\n=== Xong: {len(all_prices)} mã | {has_price} có giá | history: {history_count} | {size_mb:.1f}MB ===")

if __name__ == '__main__':
    main()
