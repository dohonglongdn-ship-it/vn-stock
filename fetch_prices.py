"""
VN Stock Price Fetcher - GitHub Actions
Tự động lấy danh sách toàn bộ mã niêm yết từ vnstock
Không cần cập nhật code khi thêm mã mới
"""
import json, sys, time, os
from datetime import datetime, timedelta

VNSTOCK_API_KEY = os.environ.get('VNSTOCK_API_KEY', '')
TODAY = datetime.now().strftime('%Y-%m-%d')
FROM  = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')

print(f"Bắt đầu: {TODAY} | API key: {'✅' if VNSTOCK_API_KEY else '❌ Guest (20 req/min)'}")
if VNSTOCK_API_KEY:
    os.environ['VNSTOCK_API_KEY'] = VNSTOCK_API_KEY

try:
    from vnstock import Vnstock
    print("✅ vnstock loaded")
except ImportError as e:
    print(f"❌ {e}"); sys.exit(1)

# ── Lấy danh sách mã tự động từ vnstock ─────────────────────────────
def get_all_tickers():
    """Lấy toàn bộ mã niêm yết HOSE + HNX + UPCOM"""
    all_tickers = []
    try:
        from vnstock.api.listing import Listing
        df = Listing().all_symbols()
        if df is not None and not df.empty:
            col = next((c for c in ['symbol','ticker','code'] if c in df.columns), None)
            if col:
                all_tickers = df[col].str.upper().tolist()
                print(f"✅ Tự động lấy {len(all_tickers)} mã từ vnstock listing")
                return all_tickers
    except Exception as e:
        print(f"⚠ Không lấy được listing tự động: {e}")

    # Fallback: danh sách cố định nếu API listing không hoạt động
    print("→ Dùng danh sách mặc định")
    return [
        # Ngân hàng
        'VCB','BID','CTG','MBB','TCB','ACB','VPB','HDB','STB','LPB',
        'MSB','OCB','TPB','VIB','SHB','NAB','BAB','VBB','SSB','KLB',
        # Chứng khoán
        'SSI','VND','HCM','VIX','MBS','VPS','VCI','TVS','SBS','BSI','AGR',
        # Thép - Vật liệu
        'HPG','HSG','NKG','TLH','SMC','POM','VGS',
        # Thực phẩm - Tiêu dùng
        'VNM','MSN','SAB','MCH','KDC','BBC','SBT','QNS','ANV','VHC','IDI','MPC',
        # Bất động sản
        'VIC','VHM','NVL','PDR','KDH','DXG','BCM','DIG','CEO','SCR',
        'IJC','NLG','TDH','PTL','HDC','CII','SJS','LDG','SGR','QCG',
        # Dầu khí
        'GAS','PLX','PVD','PVS','OIL','BSR','PGD','CNG','PVC','PXS',
        # Công nghệ
        'FPT','CMG','ELC','SAM','VGI','ITD',
        # Bán lẻ
        'MWG','FRT','PNJ','DGW','HAH',
        # Hàng không - Logistics
        'HVN','VJC','ACV','GMD','VSC','TMS','STG','VOS',
        # Điện - Năng lượng
        'POW','REE','PC1','NT2','VSH','SHP','TMP','GEG','PPC','HND',
        'EVN','PGV','QTP','CHP','TBC','DRL',
        # Dược phẩm - Y tế
        'DHG','IMP','DMC','TRA','DBD','SPM','PME','LDP',
        # Phân bón - Hóa chất
        'DPM','DCM','BFC','LAS','PMB','CSV',
        # Cao su
        'PHR','DPR','TRC','GVR','HRC',
        # Vật liệu xây dựng
        'VGC','HT1','BCC','HOM','BTP','TCX',
        # Bảo hiểm
        'BVH','BMI','PRE','PTI','MIG',
        # Xây dựng
        'CTD','HBC','VCG','FCN','DPG','PXL','SCI',
        # Dệt may
        'MSH','STK','TNG','TCM','VGT','GIL',
        # Thủy điện - Môi trường
        'BWE','TDM','PMW','HTI',
    ]

TICKERS = get_all_tickers()
# Giới hạn nếu không có API key (tránh timeout GitHub Actions)
if not VNSTOCK_API_KEY and len(TICKERS) > 80:
    print(f"⚠ Guest mode: giới hạn 80 mã đầu (có API key để lấy tất cả)")
    TICKERS = TICKERS[:80]

DELAY = 2 if VNSTOCK_API_KEY else 4
print(f"Sẽ lấy {len(TICKERS)} mã | delay {DELAY}s/mã")

# ── Hàm lấy dữ liệu ──────────────────────────────────────────────────
def fix_price(p):
    return p * 1000 if p and 0 < p < 500 else p

def get_history(ticker, retries=3):
    for attempt in range(retries):
        try:
            stock = Vnstock().stock(symbol=ticker, source='VCI')
            df = stock.quote.history(start=FROM, end=TODAY, interval='1D')
            if df is not None and not df.empty:
                return df
        except Exception as e:
            if 'Rate limit' in str(e) or 'rate limit' in str(e).lower():
                wait = 65 if attempt == 0 else 30
                print(f"  ⏳ Rate limit, chờ {wait}s...")
                time.sleep(wait)
            else:
                break
    return None

def df_to_record(df):
    df.columns = [c.lower() for c in df.columns]
    rename = {'time':'date','tradingdate':'date'}
    df = df.rename(columns={k:v for k,v in rename.items() if k in df.columns})
    date_col = next((c for c in ['date','time'] if c in df.columns), None)
    df['date'] = df[date_col].astype(str).str[:10] if date_col else df.index.astype(str).str[:10]
    df = df.sort_values('date').reset_index(drop=True)
    close_col = next((c for c in ['close','price'] if c in df.columns), None)
    if not close_col: return None
    df['close']  = df[close_col].astype(float).apply(fix_price)
    df['open']   = df.get('open', df['close']).astype(float).apply(fix_price)
    df['high']   = df.get('high', df['close']).astype(float).apply(fix_price)
    df['low']    = df.get('low',  df['close']).astype(float).apply(fix_price)
    vol_col = next((c for c in ['volume','totalvolume'] if c in df.columns), None)
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
        'history':   [{'date':r['date'],'open':float(r['open']),'high':float(r['high']),
                       'low':float(r['low']),'close':float(r['close']),'volume':int(r['volume'])}
                      for _,r in df.iterrows()],
        'updated': TODAY, 'source': 'vnstock'
    }

# ── Lấy dữ liệu ──────────────────────────────────────────────────────
prices, errors = {}, []
for i, ticker in enumerate(TICKERS):
    print(f"[{i+1}/{len(TICKERS)}] {ticker}", end=' ')
    df = get_history(ticker)
    if df is not None:
        rec = df_to_record(df)
        if rec:
            prices[ticker] = rec
            print(f"✅ {rec['price']:,.0f}đ ({rec['changePct']:+.2f}%)")
        else:
            errors.append(ticker); print("⚠ parse lỗi")
    else:
        errors.append(ticker); print("⚠ no data")
    if i < len(TICKERS)-1:
        time.sleep(DELAY)

# ── Lưu ──────────────────────────────────────────────────────────────
with open('prices.json','w',encoding='utf-8') as f:
    json.dump({'updated':TODAY,'count':len(prices),'total':len(TICKERS),
               'errors':errors,'prices':prices}, f, ensure_ascii=False, indent=2)

print(f"\n✅ {len(prices)}/{len(TICKERS)} mã | Lỗi: {errors or 'không có'}")
if len(prices) == 0:
    print("❌ Không lấy được mã nào!"); sys.exit(1)
