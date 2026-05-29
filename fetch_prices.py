"""
VN Stock Price Fetcher - GitHub Actions
- Lấy giá hàng ngày từ vnstock (VCI source)
- Lưu vào prices.json để app đọc
"""
import json, sys, time, os
from datetime import datetime, timedelta

# API key từ GitHub Secrets (tăng rate limit từ 20 lên 60 req/phút)
VNSTOCK_API_KEY = os.environ.get('VNSTOCK_API_KEY', '')

TICKERS = [
    'VCB','BID','CTG','MBB','TCB','ACB','VPB','HDB','STB','LPB',
    'SSI','VND','HCM','VIX','MBS','VPS',
    'HPG','HSG','NKG',
    'VNM','MSN','SAB',
    'VIC','VHM','NVL','PDR','KDH','DXG',
    'GAS','PLX','PVD','PVS','OIL',
    'FPT','MWG','FRT','PNJ',
    'HVN','VJC','POW','REE',
    'DHG','VHC','ANV',
]

TODAY = datetime.now().strftime('%Y-%m-%d')
FROM  = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')

print(f"Bắt đầu: {TODAY} | API key: {'✅' if VNSTOCK_API_KEY else '❌ Guest (20 req/min)'}")

# Set API key nếu có
if VNSTOCK_API_KEY:
    os.environ['VNSTOCK_API_KEY'] = VNSTOCK_API_KEY

try:
    from vnstock import Vnstock
    print("✅ vnstock loaded")
except ImportError as e:
    print(f"❌ {e}"); sys.exit(1)


def get_history(ticker, retries=3):
    for attempt in range(retries):
        try:
            stock = Vnstock().stock(symbol=ticker, source='VCI')
            df = stock.quote.history(start=FROM, end=TODAY, interval='1D')
            if df is not None and not df.empty:
                return df
        except Exception as e:
            msg = str(e)
            if 'Rate limit' in msg or 'rate limit' in msg.lower():
                wait = 65 if attempt == 0 else 30
                print(f"  ⏳ Rate limit, chờ {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [VCI] lỗi: {msg[:80]}")
                break
    return None


def fix_price(price):
    """vnstock VCI trả về đơn vị nghìn đồng → nhân 1000"""
    if price and price < 500:  # < 500 nghĩa là đơn vị nghìn
        return price * 1000
    return price


def df_to_record(df):
    # Chuẩn hóa tên cột
    df.columns = [c.lower() for c in df.columns]
    rename = {'time':'date','tradingdate':'date','open':'open','high':'high',
               'low':'low','close':'close','volume':'volume'}
    df = df.rename(columns={k:v for k,v in rename.items() if k in df.columns})

    # Xác định cột date
    date_col = next((c for c in ['date','time'] if c in df.columns), None)
    if date_col:
        df['date'] = df[date_col].astype(str).str[:10]
    else:
        df['date'] = df.index.astype(str).str[:10]

    df = df.sort_values('date').reset_index(drop=True)

    close_col = next((c for c in ['close','price'] if c in df.columns), None)
    if not close_col: return None

    df['close']  = df[close_col].astype(float).apply(fix_price)
    df['open']   = df.get('open',  df['close']).astype(float).apply(fix_price)
    df['high']   = df.get('high',  df['close']).astype(float).apply(fix_price)
    df['low']    = df.get('low',   df['close']).astype(float).apply(fix_price)
    vol_col      = next((c for c in ['volume','totalvolume'] if c in df.columns), None)
    df['volume'] = df[vol_col].astype(float).astype(int) if vol_col else 0

    df = df[df['close'] > 0].tail(90)
    if len(df) < 2: return None

    last, prev = df.iloc[-1], df.iloc[-2]
    chg = (last['close'] - prev['close']) / prev['close'] * 100

    return {
        'price':     float(last['close']),
        'changePct': round(float(chg), 2),
        'high52w':   float(df['close'].max()),
        'low52w':    float(df['close'].min()),
        'volume':    int(last['volume']),
        'history':   [
            {'date':r['date'],'open':float(r['open']),'high':float(r['high']),
             'low':float(r['low']),'close':float(r['close']),'volume':int(r['volume'])}
            for _, r in df.iterrows()
        ],
        'updated': TODAY,
        'source':  'vnstock'
    }


# Lấy dữ liệu
prices, errors = {}, []
DELAY = 2 if VNSTOCK_API_KEY else 4  # Guest cần delay nhiều hơn

for i, ticker in enumerate(TICKERS):
    print(f"\n[{i+1}/{len(TICKERS)}] {ticker}")
    df = get_history(ticker)
    if df is not None:
        record = df_to_record(df)
        if record:
            prices[ticker] = record
            print(f"  ✅ {record['price']:,.0f} đ ({record['changePct']:+.2f}%) — {len(record['history'])} phiên")
        else:
            errors.append(ticker); print("  ⚠ Parse lỗi")
    else:
        errors.append(ticker); print("  ⚠ Không có data")

    # Delay giữa các mã (tránh rate limit)
    if i < len(TICKERS) - 1:
        time.sleep(DELAY)

# Lưu
with open('prices.json', 'w', encoding='utf-8') as f:
    json.dump({'updated':TODAY,'count':len(prices),'total':len(TICKERS),
               'errors':errors,'prices':prices}, f, ensure_ascii=False, indent=2)

print(f"\n{'='*50}")
print(f"✅ {len(prices)}/{len(TICKERS)} mã | Lỗi: {errors or 'không có'}")

if len(prices) == 0:
    print("❌ Không lấy được mã nào!"); sys.exit(1)
