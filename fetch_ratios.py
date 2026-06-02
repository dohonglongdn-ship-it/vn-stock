#!/usr/bin/env python3
"""
fetch_ratios.py — Cập nhật financial ratios vào prices.json
Chạy T7 hàng tuần (không cần chạy mỗi ngày vì ratio thay đổi theo quý)
Tách riêng để không làm chậm fetch_prices.py hàng ngày
"""

import json, os, time, requests
from datetime import datetime

OUTPUT_FILE = 'prices.json'
BATCH_SIZE  = 100   # mã/request
SLEEP       = 0.3   # giây giữa requests

def safe_float(v):
    try: return float(v) if v is not None else None
    except: return None

def get_ratios_vndirect(codes_batch):
    """Lấy ratios từ VNDirect finfo API (server-side, không bị CORS)"""
    codes = ','.join(codes_batch)
    url = (f'https://finfo-api.vndirect.com.vn/v4/ratio/latest'
           f'?q=code:{codes}'
           f'&fields=priceToEarning,priceToBook,returnOnEquity,earningPerShare,dividendYield,marketCap'
           f'&size={len(codes_batch)}')
    try:
        r = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://www.vndirect.com.vn/',
        }, timeout=20)
        results = {}
        for item in r.json().get('data', []):
            code = item.get('code')
            if not code: continue
            results[code] = {
                'pe':        safe_float(item.get('priceToEarning')),
                'pb':        safe_float(item.get('priceToBook')),
                'roe':       safe_float(item.get('returnOnEquity')),
                'eps':       safe_float(item.get('earningPerShare')),
                'divYield':  safe_float(item.get('dividendYield')),
                'marketCap': safe_float(item.get('marketCap')),
            }
        return results
    except Exception as e:
        print(f'  [WARN] VNDirect batch: {e}')
        return {}

def get_ratios_tcbs(ticker):
    """Fallback: TCBS API cho mã HOSE quan trọng"""
    url = f'https://apipubaws.tcbs.com.vn/tcanalysis/v1/ticker/{ticker}/financialratio?yearly=0&isAll=false'
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        data = r.json()
        if not data: return {}
        # Lấy quý gần nhất
        latest = data[0] if isinstance(data, list) else data
        return {
            'pe':       safe_float(latest.get('pe')),
            'pb':       safe_float(latest.get('pb')),
            'roe':      safe_float(latest.get('roe')),
            'eps':      safe_float(latest.get('eps')),
            'divYield': safe_float(latest.get('dividendYield')),
        }
    except:
        return {}

def main():
    print(f'=== fetch_ratios.py: {datetime.now()} ===')

    # Load prices.json
    if not os.path.exists(OUTPUT_FILE):
        print('Lỗi: prices.json chưa có. Chạy fetch_prices.py trước.')
        return

    with open(OUTPUT_FILE) as f:
        data = json.load(f)
    print(f'  Loaded {len(data)} mã từ prices.json')

    all_tickers = list(data.keys())

    # Batch fetch VNDirect
    print(f'Lấy ratios VNDirect ({len(all_tickers)} mã, batch {BATCH_SIZE})...')
    all_ratios = {}
    for i in range(0, len(all_tickers), BATCH_SIZE):
        batch = all_tickers[i:i+BATCH_SIZE]
        ratios = get_ratios_vndirect(batch)
        all_ratios.update(ratios)
        if (i+BATCH_SIZE) % 500 == 0:
            print(f'  {i+BATCH_SIZE}/{len(all_tickers)} mã...')
        time.sleep(SLEEP)

    print(f'  VNDirect: {len(all_ratios)} mã có data')

    # Fallback TCBS cho mã HOSE thiếu PE
    missing = [
        t for t in all_tickers
        if data[t].get('exchange') == 'HOSE'
        and (not all_ratios.get(t) or not all_ratios[t].get('pe'))
    ]
    print(f'  Fallback TCBS cho {len(missing)} mã HOSE thiếu PE...')
    for t in missing[:100]:  # giới hạn 100
        r = get_ratios_tcbs(t)
        if r:
            if t not in all_ratios:
                all_ratios[t] = {}
            for k, v in r.items():
                if v and not all_ratios[t].get(k):
                    all_ratios[t][k] = v
        time.sleep(0.4)

    # Merge ratios vào prices.json
    updated = 0
    for ticker, ratios in all_ratios.items():
        if ticker not in data: continue
        for field in ['pe', 'pb', 'roe', 'eps', 'divYield', 'marketCap']:
            if ratios.get(field) is not None:
                data[ticker][field] = ratios[field]
        updated += 1

    # Ghi lại
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    pe_count  = sum(1 for v in data.values() if v.get('pe'))
    pb_count  = sum(1 for v in data.values() if v.get('pb'))
    roe_count = sum(1 for v in data.values() if v.get('roe'))

    print(f'\n=== Xong ===')
    print(f'  Cập nhật ratios: {updated} mã')
    print(f'  Có P/E: {pe_count} | P/B: {pb_count} | ROE: {roe_count}')
    print(f'  {datetime.now()}')

if __name__ == '__main__':
    main()
