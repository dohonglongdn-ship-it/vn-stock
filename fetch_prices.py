import json
from datetime import datetime, timedelta

# Danh sách mã theo dõi - thêm bao nhiêu tùy ý
TICKERS = [
    # Ngân hàng
    'VCB','BID','CTG','MBB','TCB','ACB','VPB','HDB','STB','LPB',
    # Chứng khoán
    'SSI','VND','HCM','VIX','MBS','VPS',
    # Thép - Vật liệu
    'HPG','HSG','NKG',
    # Thực phẩm - Tiêu dùng
    'VNM','MSN','SAB',
    # Bất động sản
    'VIC','VHM','NVL','PDR','KDH','DXG',
    # Dầu khí (kể cả UPCOM)
    'GAS','PLX','PVD','PVS','OIL','BSR',
    # Công nghệ - Bán lẻ
    'FPT','MWG','FRT','PNJ',
    # Hàng không - Điện
    'HVN','VJC','POW','REE',
    # Dược - Thủy sản
    'DHG','VHC','ANV',
]

today = datetime.now().strftime('%Y-%m-%d')
from_date = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')

prices = {}
errors = []

for ticker in TICKERS:
    try:
        from vnstock import Vnstock
        stock = Vnstock().stock(symbol=ticker, source='VCI')
        hist = stock.quote.history(start=from_date, end=today, interval='1D')
        
        if hist is None or hist.empty:
            # Thử nguồn SSI
            stock2 = Vnstock().stock(symbol=ticker, source='TCBS')
            hist = stock2.quote.history(start=from_date, end=today, interval='1D')
        
        if hist is not None and not hist.empty:
            last = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else last
            chg_pct = (last['close'] - prev['close']) / prev['close'] * 100
            
            # Lưu lịch sử 90 ngày gần nhất (cho chart)
            hist_90 = hist.tail(90)
            history = []
            for _, row in hist_90.iterrows():
                history.append({
                    'date': str(row.get('time', row.name))[:10],
                    'open':   float(row['open'])   if row['open']   else None,
                    'high':   float(row['high'])   if row['high']   else None,
                    'low':    float(row['low'])    if row['low']    else None,
                    'close':  float(row['close'])  if row['close']  else None,
                    'volume': int(row['volume'])   if row['volume'] else 0,
                })
            
            prices[ticker] = {
                'price':     float(last['close']),
                'changePct': round(float(chg_pct), 2),
                'high52w':   float(hist['high'].max()),
                'low52w':    float(hist['low'].min()),
                'volume':    int(last['volume']),
                'history':   history,
                'updated':   today,
                'source':    'vnstock'
            }
            print(f'✅ {ticker}: {last["close"]:,.0f} ({chg_pct:+.2f}%)')
        else:
            errors.append(ticker)
            print(f'⚠ {ticker}: Không có dữ liệu')
            
    except Exception as e:
        errors.append(ticker)
        print(f'❌ {ticker}: {e}')

# Lưu file
output = {
    'updated': today,
    'count': len(prices),
    'errors': errors,
    'prices': prices
}

with open('prices.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f'\n✅ Hoàn thành: {len(prices)}/{len(TICKERS)} mã')
if errors:
    print(f'⚠ Lỗi: {errors}')
