#!/usr/bin/env python3
"""
fetch_ratios.py — Cập nhật financial ratios vào prices.json
Chỉ lấy HOSE (~400 mã) để tránh timeout GitHub Actions
TCBS batch API thay vì từng mã một
"""

import json, os, time, requests
from datetime import datetime

OUTPUT_FILE = 'prices.json'

def safe_float(v):
    try: return float(v) if v is not None else None
    except: return None

def get_ratios_batch_tcbs(tickers):
    """
    TCBS screening API — lấy nhiều mã cùng lúc
    Trả về dict {ticker: {pe, pb, roe, eps, ...}}
    """
    # TCBS có endpoint lấy danh sách với ratios
    url = 'https://apipubaws.tcbs.com.vn/stock-insight/v2/stock/second-tc-price'
    results = {}
    
    # Batch 50 mã/request
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i+50]
        params = {'tickers': ','.join(batch)}
        try:
            r = requests.get(url, params=params,
                           headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if not r.ok: continue
            data = r.json()
            items = data if isinstance(data, list) else data.get('data', [])
            for item in items:
                t = item.get('ticker', '')
                if t:
                    results[t] = {
                        'pe':  safe_float(item.get('pe')),
                        'pb':  safe_float(item.get('pb')),
                        'roe': safe_float(item.get('roe')),
                        'eps': safe_float(item.get('eps')),
                    }
        except Exception as e:
            print(f'  [WARN] TCBS batch {i//50}: {e}')
        time.sleep(0.3)
    
    return results

def get_ratio_single(ticker):
    """Single ticker fallback"""
    url = f'https://apipubaws.tcbs.com.vn/tcanalysis/v1/ticker/{ticker}/financialratio?yearly=0&isAll=false'
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
        if not r.ok: return {}
        d = r.json()
        item = d[0] if isinstance(d, list) and d else d
        if not item or not isinstance(item, dict): return {}
        return {
            'pe':  safe_float(item.get('pe')),
            'pb':  safe_float(item.get('pb')),
            'roe': safe_float(item.get('roe')),
            'eps': safe_float(item.get('eps')),
        }
    except: return {}

def main():
    print(f'=== fetch_ratios.py: {datetime.now()} ===')

    if not os.path.exists(OUTPUT_FILE):
        print('Lỗi: prices.json chưa có.')
        return

    with open(OUTPUT_FILE) as f:
        raw = json.load(f)

    data = {k: v for k, v in raw.items() if isinstance(v, dict)}
    print(f'  {len(data)} mã hợp lệ trong prices.json')

    # Chỉ xử lý HOSE để tránh timeout (~400 mã)
    hose = [t for t, v in data.items() if v.get('exchange') == 'HOSE']
    hnx  = [t for t, v in data.items() if v.get('exchange') == 'HNX']
    print(f'  HOSE: {len(hose)} | HNX: {len(hnx)} mã')

    # Thử batch API trước
    print('Bước 1: TCBS batch API...')
    all_tickers = hose + hnx[:100]  # HOSE + 100 mã HNX lớn nhất
    batch_results = get_ratios_batch_tcbs(all_tickers)
    print(f'  Batch: {len(batch_results)} mã có data')

    # Với mã HOSE chưa có PE → single request
    missing = [t for t in hose if not batch_results.get(t, {}).get('pe')]
    print(f'Bước 2: Single request cho {len(missing)} mã HOSE thiếu PE...')
    
    for i, ticker in enumerate(missing):
        r = get_ratio_single(ticker)
        if r:
            batch_results[ticker] = batch_results.get(ticker, {})
            batch_results[ticker].update({k: v for k, v in r.items() if v})
        if (i+1) % 50 == 0:
            print(f'  {i+1}/{len(missing)}...')
        time.sleep(0.2)

    # Merge vào prices.json
    updated = 0
    for ticker, ratios in batch_results.items():
        if ticker not in data: continue
        changed = False
        for field in ['pe', 'pb', 'roe', 'eps']:
            if ratios.get(field) is not None:
                data[ticker][field] = ratios[field]
                changed = True
        if changed: updated += 1

    raw.update(data)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False, separators=(',', ':'))

    pe  = sum(1 for v in data.values() if v.get('pe'))
    pb  = sum(1 for v in data.values() if v.get('pb'))
    roe = sum(1 for v in data.values() if v.get('roe'))
    print(f'\n=== Xong: updated={updated} | PE={pe} PB={pb} ROE={roe} mã ===')
    print(f'  {datetime.now()}')

if __name__ == '__main__':
    main()
