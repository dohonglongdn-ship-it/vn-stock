#!/usr/bin/env python3
"""
fetch_prices.py — VN Stock Intelligence
Cập nhật prices.json với giá EOD + financial ratios (P/E, P/B, ROE, EPS, divYield, marketCap)
Chạy: GitHub Actions 16h T2-T6

Nguồn dữ liệu:
- Giá OHLCV + lịch sử 60 ngày: vnstock (TCBS)
- Financial ratios: vnstock Company().financial_ratio() hoặc finfo-api.vndirect.com.vn
- Fallback: SSI API
"""

import json, os, time, requests
from datetime import datetime, timedelta
from vnstock import Listing, Quote, Company

# ── Config ────────────────────────────────────────────────────────────
OUTPUT_FILE   = 'prices.json'
HISTORY_DAYS  = 90        # số ngày lịch sử lưu vào prices.json
TOP_N         = 200       # lấy top N mã theo thanh khoản cho full history
RATIO_BATCH   = 50        # số mã lấy ratio mỗi lần (tránh bị block)
SLEEP_BETWEEN = 0.3       # giây nghỉ giữa các request

# ── Helpers ───────────────────────────────────────────────────────────
def today():
    return datetime.now().strftime('%Y-%m-%d')

def days_ago(n):
    return (datetime.now() - timedelta(days=n)).strftime('%Y-%m-%d')

def safe_float(v):
    try: return float(v) if v is not None else None
    except: return None

# ── Lấy danh sách mã ─────────────────────────────────────────────────
def get_all_tickers():
    """Lấy toàn bộ danh sách mã từ cả 3 sàn"""
    listing = Listing()
    tickers = []
    for exchange in ['HOSE', 'HNX', 'UPCOM']:
        try:
            df = listing.symbols_by_exchange(exchange=exchange, lang='vi')
            for _, row in df.iterrows():
                tickers.append({
                    'ticker':   row.get('symbol', ''),
                    'name':     row.get('organ_name', row.get('organName', '')),
                    'exchange': exchange,
                    'industry': row.get('icb_name3', row.get('industryName', '')),
                    'sector':   row.get('icb_name1', ''),
                })
        except Exception as e:
            print(f'  [WARN] Listing {exchange}: {e}')
    print(f'  Tổng {len(tickers)} mã từ 3 sàn')
    return tickers

# ── Lấy giá EOD hôm nay ──────────────────────────────────────────────
def get_eod_prices(tickers):
    """Lấy giá đóng cửa hôm nay cho tất cả mã"""
    results = {}
    
    # Dùng finfo-api.vndirect.com.vn — có toàn bộ 3 sàn
    batch_size = 200
    all_syms = [t['ticker'] for t in tickers]
    
    for i in range(0, len(all_syms), batch_size):
        batch = all_syms[i:i+batch_size]
        codes = ','.join(batch)
        url = f'https://finfo-api.vndirect.com.vn/v4/stock_prices?q=code:{codes}&sort=date:desc&size={batch_size}'
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            data = r.json().get('data', [])
            seen = set()
            for item in data:
                code = item.get('code', '')
                if code and code not in seen:
                    seen.add(code)
                    results[code] = {
                        'price':     safe_float(item.get('close')),
                        'open':      safe_float(item.get('open')),
                        'high':      safe_float(item.get('high')),
                        'low':       safe_float(item.get('low')),
                        'volume':    safe_float(item.get('nmVolume')),
                        'changePct': safe_float(item.get('pctChange')),
                        'date':      item.get('date', today()),
                    }
        except Exception as e:
            print(f'  [WARN] EOD batch {i//batch_size}: {e}')
        time.sleep(SLEEP_BETWEEN)
    
    print(f'  Giá EOD: {len(results)} mã')
    return results

# ── Lấy lịch sử OHLCV ────────────────────────────────────────────────
def get_history(ticker, days=HISTORY_DAYS):
    """Lấy lịch sử OHLCV qua vnstock TCBS"""
    try:
        quote = Quote(symbol=ticker, source='TCBS')
        df = quote.history(
            start=days_ago(days + 10),
            end=today(),
            interval='1D'
        )
        if df is None or df.empty:
            return []
        records = []
        for _, row in df.tail(days).iterrows():
            records.append({
                'date':   str(row.get('time', '')).split()[0],
                'open':   safe_float(row.get('open')),
                'high':   safe_float(row.get('high')),
                'low':    safe_float(row.get('low')),
                'close':  safe_float(row.get('close')),
                'volume': safe_float(row.get('volume')),
            })
        return records
    except Exception as e:
        print(f'  [WARN] History {ticker}: {e}')
        return []

# ── Lấy Financial Ratios ──────────────────────────────────────────────
def get_financial_ratios_vndirect(tickers_batch):
    """
    Lấy P/E, P/B, ROE, EPS, divYield, marketCap từ finfo-api.vndirect.com.vn
    Trả về dict {ticker: {pe, pb, roe, eps, divYield, marketCap}}
    """
    results = {}
    codes = ','.join(tickers_batch)
    url = f'https://finfo-api.vndirect.com.vn/v4/ratio/latest?q=code:{codes}&fields=priceToEarning,priceToBook,returnOnEquity,earningPerShare,dividendYield,marketCap&size={len(tickers_batch)}'
    try:
        r = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.vndirect.com.vn/'
        }, timeout=15)
        data = r.json().get('data', [])
        for item in data:
            code = item.get('code', '')
            if code:
                results[code] = {
                    'pe':        safe_float(item.get('priceToEarning')),
                    'pb':        safe_float(item.get('priceToBook')),
                    'roe':       safe_float(item.get('returnOnEquity')),
                    'eps':       safe_float(item.get('earningPerShare')),
                    'divYield':  safe_float(item.get('dividendYield')),
                    'marketCap': safe_float(item.get('marketCap')),
                }
    except Exception as e:
        print(f'  [WARN] Ratio VNDirect: {e}')
    return results

def get_financial_ratios_vnstock(ticker):
    """
    Fallback: dùng vnstock Company().financial_ratio()
    """
    try:
        company = Company(symbol=ticker, source='TCBS')
        df = company.financial_ratio(period='quarter', lang='vi')
        if df is None or df.empty:
            return {}
        latest = df.iloc[-1]
        return {
            'pe':        safe_float(latest.get('P/E') or latest.get('pe')),
            'pb':        safe_float(latest.get('P/B') or latest.get('pb')),
            'roe':       safe_float(latest.get('ROE') or latest.get('roe')),
            'eps':       safe_float(latest.get('EPS') or latest.get('eps')),
            'divYield':  None,
            'marketCap': None,
        }
    except:
        return {}

def get_all_ratios(all_tickers):
    """Lấy ratio cho tất cả mã, VNDirect batch trước, fallback vnstock"""
    all_syms = [t['ticker'] for t in all_tickers]
    ratios = {}
    
    print(f'  Lấy ratios VNDirect ({len(all_syms)} mã)...')
    for i in range(0, len(all_syms), RATIO_BATCH):
        batch = all_syms[i:i+RATIO_BATCH]
        batch_ratios = get_financial_ratios_vndirect(batch)
        ratios.update(batch_ratios)
        time.sleep(SLEEP_BETWEEN)
        if i % 500 == 0 and i > 0:
            print(f'    {i}/{len(all_syms)} mã...')
    
    print(f'  VNDirect ratios: {len(ratios)} mã có dữ liệu')
    
    # Fallback vnstock cho mã HOSE quan trọng còn thiếu
    missing_hose = [
        t['ticker'] for t in all_tickers
        if t['exchange'] == 'HOSE'
        and t['ticker'] not in ratios
        or not ratios.get(t['ticker'], {}).get('pe')
    ][:100]  # giới hạn để tránh quá lâu
    
    if missing_hose:
        print(f'  Fallback vnstock cho {len(missing_hose)} mã HOSE thiếu PE...')
        for ticker in missing_hose[:50]:  # lấy 50 mã đầu
            r = get_financial_ratios_vnstock(ticker)
            if r:
                if ticker not in ratios:
                    ratios[ticker] = {}
                for k, v in r.items():
                    if v and not ratios[ticker].get(k):
                        ratios[ticker][k] = v
            time.sleep(0.5)
    
    return ratios

# ── Lấy 52w High/Low ─────────────────────────────────────────────────
def calc_52w(history):
    """Tính 52w high/low từ lịch sử"""
    if not history:
        return None, None
    prices = [b['close'] for b in history if b.get('close')]
    if not prices:
        return None, None
    return max(prices), min(prices)

# ── Main ──────────────────────────────────────────────────────────────
def main():
    print(f'=== fetch_prices.py bắt đầu: {datetime.now()} ===')
    
    # 1. Load existing prices.json để merge
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                existing = json.load(f)
            print(f'  Loaded existing: {len(existing)} mã')
        except:
            pass
    
    # 2. Lấy danh sách mã
    print('Bước 1: Lấy danh sách mã...')
    tickers = get_all_tickers()
    ticker_map = {t['ticker']: t for t in tickers}
    
    # 3. Giá EOD
    print('Bước 2: Lấy giá EOD...')
    eod = get_eod_prices(tickers)
    
    # 4. Financial ratios (tất cả mã)
    print('Bước 3: Lấy financial ratios...')
    ratios = get_all_ratios(tickers)
    
    # 5. Lịch sử OHLCV cho top N mã HOSE (theo volume)
    print(f'Bước 4: Lấy lịch sử {HISTORY_DAYS} ngày cho top {TOP_N} mã...')
    # Sắp xếp theo volume để lấy top N
    hose_tickers = [t['ticker'] for t in tickers if t['exchange'] == 'HOSE']
    top_by_volume = sorted(
        hose_tickers,
        key=lambda t: eod.get(t, {}).get('volume', 0) or 0,
        reverse=True
    )[:TOP_N]
    
    # Thêm tất cả mã trong watchlist từ file user_data.json nếu có
    watchlist_tickers = []
    if os.path.exists('user_data.json'):
        try:
            ud = json.load(open('user_data.json'))
            watchlist_tickers = ud.get('watchlist', [])
        except: pass
    
    history_tickers = list(set(top_by_volume + watchlist_tickers))
    print(f'  Lấy lịch sử cho {len(history_tickers)} mã...')
    
    histories = {}
    for i, ticker in enumerate(history_tickers):
        h = get_history(ticker)
        if h:
            histories[ticker] = h
        if i % 50 == 0 and i > 0:
            print(f'    {i}/{len(history_tickers)} mã...')
        time.sleep(SLEEP_BETWEEN)
    
    # 6. Ghép tất cả lại thành prices.json
    print('Bước 5: Ghép dữ liệu...')
    result = {}
    
    for ticker_info in tickers:
        t = ticker_info['ticker']
        price_data = eod.get(t, {})
        ratio_data = ratios.get(t, {})
        history = histories.get(t, [])
        high52w, low52w = calc_52w(history or existing.get(t, {}).get('history', []))
        
        entry = {
            # Thông tin cơ bản
            'name':     ticker_info.get('name', ''),
            'exchange': ticker_info.get('exchange', ''),
            'industry': ticker_info.get('industry', ''),
            'sector':   ticker_info.get('sector', ''),
            # Giá EOD
            'price':     price_data.get('price'),
            'changePct': price_data.get('changePct'),
            'open':      price_data.get('open'),
            'high':      price_data.get('high'),
            'low':       price_data.get('low'),
            'volume':    price_data.get('volume'),
            'date':      price_data.get('date', today()),
            # 52w
            'high52w':   high52w or existing.get(t, {}).get('high52w'),
            'low52w':    low52w  or existing.get(t, {}).get('low52w'),
            # Financial ratios ← THÊM MỚI
            'pe':        ratio_data.get('pe')        or existing.get(t, {}).get('pe'),
            'pb':        ratio_data.get('pb')        or existing.get(t, {}).get('pb'),
            'roe':       ratio_data.get('roe')       or existing.get(t, {}).get('roe'),
            'eps':       ratio_data.get('eps')       or existing.get(t, {}).get('eps'),
            'divYield':  ratio_data.get('divYield')  or existing.get(t, {}).get('divYield'),
            'marketCap': ratio_data.get('marketCap') or existing.get(t, {}).get('marketCap'),
            # Lịch sử OHLCV (chỉ lưu nếu có)
            'history':   history or existing.get(t, {}).get('history', []),
            # Metadata
            'updatedAt': today(),
        }
        
        result[t] = entry
    
    # 7. Ghi file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))
    
    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    count_with_pe = sum(1 for v in result.values() if v.get('pe'))
    count_with_pb = sum(1 for v in result.values() if v.get('pb'))
    
    print(f'\n=== Hoàn thành ===')
    print(f'  Tổng mã: {len(result)}')
    print(f'  Có P/E:  {count_with_pe}')
    print(f'  Có P/B:  {count_with_pb}')
    print(f'  File size: {size_mb:.1f} MB')
    print(f'  Thời gian: {datetime.now()}')

if __name__ == '__main__':
    main()
