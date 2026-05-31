#!/usr/bin/env python3
"""
VN Stock - Fetch Prices
Cập nhật hàng ngày lúc 16h (GitHub Actions)
- Lấy giá tất cả 1530 mã (price + changePct)
- Lưu thêm history 60 ngày cho top 200 mã (dùng cho screener)
"""

import json, os, datetime
from pathlib import Path

try:
    from vnstock import stock_historical_data, listing_companies
    VNSTOCK_OK = True
except ImportError:
    VNSTOCK_OK = False
    print("vnstock not available")

# ── Top 200 mã cần history cho screener ──────────────────────────────
TOP200 = [
    # Ngân hàng
    'VCB','BID','CTG','MBB','TCB','ACB','VPB','HDB','STB','LPB',
    'MSB','EIB','TPB','SHB','OCB','VIB','BAB','BVB','KLB','PGB',
    # Chứng khoán
    'SSI','VND','HCM','VIX','MBS','VPS','AGR','BSI','CTS','SHS',
    # Thực phẩm & Tiêu dùng
    'VNM','MSN','SAB','MCH','ANV','ABT','BBC','CAN','HAG','KDC',
    # Bất động sản
    'VIC','VHM','NVL','PDR','KDH','DXG','CEO','CII','DIG','HDC',
    'HHV','IJC','ITA','LDG','NLG','NTL','PTL','QCG','SCR','SJS',
    # Dầu khí & Năng lượng
    'GAS','PLX','PVD','PVS','BSR','OIL','PVC','PVI','PVT','CNG',
    'PGS','GAS','ACV','PPC','REE','POW','NT2','VSH','TBC','SBA',
    # Công nghệ
    'FPT','CMG','VGI','ELC','SAM','ITD','TST','VTC',
    # Bán lẻ & Tiêu dùng
    'MWG','FRT','PNJ','DGW','HAX','HHS','VGT','TNG','MSH','STK',
    # Thép & Vật liệu
    'HPG','HSG','NKG','TLH','SMC','VGS','HMC','DTL','TVN','VIS',
    # Hàng không & Vận tải
    'HVN','VJC','GMD','HAH','VSC','PHP','STG','VOS','MVN','SFI',
    # Xây dựng & Hạ tầng
    'CTD','HBC','VCG','FCN','LCG','PC1','C4G','CCP','TV2','PVX',
    # Bảo hiểm & Tài chính
    'BVH','BMI','MIG','PTI','PVI','BIC','ABI',
    # Phân bón & Hóa chất
    'DCM','DPM','BFC','SFG','DDV','CSV','DGC','HVT','LAS','PMB',
    # Cao su & Nông nghiệp
    'GVR','PHR','TRC','DPR','SVR','HRC','TPC','VPH','HAG','HNG',
    # Dệt may
    'VGT','TNG','MSH','STK','TCM','ADS','GIL','KMR',
    # Khác
    'VRE','VGC','AAA','ASM','CHP','DHC','EVF','GEX','HDG','IMP',
]
# Loại trùng lặp, giữ 200
TOP200 = list(dict.fromkeys(TOP200))[:200]

def get_today():
    return datetime.date.today().strftime('%Y-%m-%d')

def get_date_range(days=65):
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')

def fetch_history(ticker, days=65):
    """Lấy lịch sử giá cho 1 mã"""
    if not VNSTOCK_OK:
        return []
    try:
        start, end = get_date_range(days)
        df = stock_historical_data(ticker, start, end, '1D', 'stock')
        if df is None or df.empty:
            return []
        bars = []
        for _, row in df.iterrows():
            try:
                bars.append({
                    'date':  str(row.get('time', row.get('date', '')))[:10],
                    'open':  float(row.get('open', 0)),
                    'high':  float(row.get('high', 0)),
                    'low':   float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume':int(row.get('volume', 0))
                })
            except: pass
        return [b for b in bars if b['close'] > 0]
    except Exception as e:
        print(f"  History error {ticker}: {e}")
        return []

def fetch_all_prices():
    """Lấy giá tất cả mã từ vnstock"""
    if not VNSTOCK_OK:
        return {}
    try:
        from vnstock import trading_price_board
        # Lấy danh sách tất cả mã
        companies = listing_companies()
        all_tickers = companies['ticker'].tolist() if companies is not None else []
        
        prices = {}
        # Lấy giá theo batch
        batch_size = 50
        for i in range(0, len(all_tickers), batch_size):
            batch = all_tickers[i:i+batch_size]
            try:
                board = trading_price_board(batch)
                if board is not None and not board.empty:
                    for _, row in board.iterrows():
                        t = str(row.get('ticker', '')).upper()
                        if not t: continue
                        price = float(row.get('match_price', row.get('close', 0)) or 0)
                        ref = float(row.get('ref_price', 0) or 0)
                        change_pct = ((price - ref) / ref * 100) if ref > 0 else 0
                        if price > 0:
                            prices[t] = {
                                'price': price,
                                'changePct': round(change_pct, 2),
                                'name': str(row.get('full_name', t)),
                                'exchange': str(row.get('exchange', '')),
                            }
            except Exception as e:
                print(f"  Batch {i//batch_size} error: {e}")
        return prices
    except Exception as e:
        print(f"fetch_all_prices error: {e}")
        return {}

def main():
    print(f"=== VN Stock Price Updater | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    
    # Load existing prices.json nếu có
    prices_file = Path('prices.json')
    existing = {}
    if prices_file.exists():
        try:
            with open(prices_file) as f:
                existing = json.load(f)
            print(f"Loaded existing: {len(existing.get('prices', {}))} mã")
        except: pass

    existing_prices = existing.get('prices', {})

    # 1. Lấy giá tất cả mã
    print("\n1. Fetching all prices...")
    all_prices = fetch_all_prices()
    if not all_prices:
        print("  No prices fetched, keeping existing")
        all_prices = existing_prices

    print(f"  Got {len(all_prices)} mã")

    # 2. Lấy history cho top 200
    print(f"\n2. Fetching history for top {len(TOP200)} tickers...")
    history_count = 0
    for i, ticker in enumerate(TOP200):
        print(f"  [{i+1}/{len(TOP200)}] {ticker}...", end=' ')
        bars = fetch_history(ticker)
        if bars:
            if ticker not in all_prices:
                all_prices[ticker] = {}
            all_prices[ticker]['history'] = bars[-60:]  # Giữ 60 ngày gần nhất
            # Update giá từ history nếu không có từ board
            if not all_prices[ticker].get('price') and bars:
                last = bars[-1]
                prev = bars[-2] if len(bars) > 1 else last
                all_prices[ticker]['price'] = last['close']
                all_prices[ticker]['changePct'] = round(
                    (last['close'] - prev['close']) / prev['close'] * 100, 2
                ) if prev['close'] > 0 else 0
            history_count += 1
            print(f"OK ({len(bars)} bars)")
        else:
            # Giữ history cũ nếu có
            if ticker in existing_prices and 'history' in existing_prices[ticker]:
                if ticker not in all_prices:
                    all_prices[ticker] = {}
                all_prices[ticker]['history'] = existing_prices[ticker]['history']
                print("kept existing")
            else:
                print("no data")

    # 3. Ghi prices.json
    output = {
        'updated': get_today(),
        'count': len(all_prices),
        'top200_history': history_count,
        'prices': all_prices
    }

    with open(prices_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = prices_file.stat().st_size / 1024 / 1024
    print(f"\n✅ prices.json updated: {len(all_prices)} mã, history: {history_count} mã, size: {size_mb:.1f}MB")

if __name__ == '__main__':
    main()
