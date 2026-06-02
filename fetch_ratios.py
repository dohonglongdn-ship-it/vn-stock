#!/usr/bin/env python3
"""
fetch_ratios.py — Cập nhật financial ratios vào prices.json
Nguồn: TCBS (HOSE) + SSI (HNX/UPCOM)
"""

import json, os, time, requests
from datetime import datetime

OUTPUT_FILE = 'prices.json'
SLEEP       = 0.4

def safe_float(v):
    try: return float(v) if v is not None else None
    except: return None

def get_ratio_tcbs(ticker):
    """TCBS — chủ yếu HOSE, ổn định từ GitHub Actions"""
    for url in [
        f'https://apipubaws.tcbs.com.vn/tcanalysis/v1/ticker/{ticker}/financialratio?yearly=0&isAll=false',
        f'https://apipubaws.tcbs.com.vn/tcanalysis/v1/ticker/{ticker}/fundamental',
    ]:
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
            if not r.ok: continue
            d = r.json()
            item = d[0] if isinstance(d, list) and d else d
            if not item: continue
            result = {
                'pe':        safe_float(item.get('pe')),
                'pb':        safe_float(item.get('pb')),
                'roe':       safe_float(item.get('roe')),
                'eps':       safe_float(item.get('eps')),
                'divYield':  safe_float(item.get('dividendYield') or item.get('divYield')),
                'marketCap': safe_float(item.get('marketCap')),
            }
            if any(v for v in result.values()):
                return result
        except: continue
    return {}

def get_ratio_ssi(ticker):
    """SSI Data — fallback cho HNX/UPCOM"""
    url = f'https://fc.ssi.com.vn/utilities/StockDetail?symbol={ticker}'
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
        if not r.ok: return {}
        d = r.json().get('data', {}) or {}
        return {
            'pe':  safe_float(d.get('pe')  or d.get('PeRatio')),
            'pb':  safe_float(d.get('pb')  or d.get('PbRatio')),
            'roe': safe_float(d.get('roe') or d.get('Roe')),
            'eps': safe_float(d.get('eps') or d.get('Eps')),
        }
    except: return {}

def main():
    print(f'=== fetch_ratios.py: {datetime.now()} ===')

    if not os.path.exists(OUTPUT_FILE):
        print('Lỗi: prices.json chưa có.')
        return

    with open(OUTPUT_FILE) as f:
        raw = json.load(f)

    # Chỉ xử lý entry là dict
    data = {k: v for k, v in raw.items() if isinstance(v, dict)}
    print(f'  {len(data)} mã hợp lệ')

    # Sắp xếp: HOSE trước
    def ex_order(t):
        return {'HOSE': 0, 'HNX': 1, 'UPCOM': 2}.get(data[t].get('exchange',''), 3)
    tickers = sorted(data.keys(), key=ex_order)

    updated = failed = 0
    for i, ticker in enumerate(tickers):
        ex = data[ticker].get('exchange', '')

        # HOSE → TCBS, HNX/UPCOM → SSI
        if ex == 'HOSE':
            ratios = get_ratio_tcbs(ticker)
        else:
            ratios = get_ratio_ssi(ticker)
            if not any(v for v in ratios.values()):
                ratios = get_ratio_tcbs(ticker)  # fallback

        if any(v is not None for v in ratios.values()):
            for f in ['pe','pb','roe','eps','divYield','marketCap']:
                if ratios.get(f) is not None:
                    data[ticker][f] = ratios[f]
            updated += 1
        else:
            failed += 1

        if (i+1) % 100 == 0:
            print(f'  {i+1}/{len(tickers)} | ok={updated} fail={failed}')
        time.sleep(SLEEP)

    # Ghi lại
    raw.update(data)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False, separators=(',', ':'))

    pe = sum(1 for v in data.values() if v.get('pe'))
    pb = sum(1 for v in data.values() if v.get('pb'))
    print(f'\n=== Xong: updated={updated} fail={failed} | PE={pe} PB={pb} mã ===')

if __name__ == '__main__':
    main()
