# -*- coding: utf-8 -*-
"""
每日前向測試 — A加z分數 + T原版 (50/50) — 雲端版
================================================================
跟現行 crypto_combo_forward 的差異:
  A腿在原本的4象限方向上, 乘上「CB溢價偏離90日常態的z分數強度」(0~100%, 不加槓桿)
  T腿完全不變(SMA50二元開關)
這是統計上跟A加z+T加z/A半Z+T半Z等版本無法區分的候選之一, 選它是因為改動最少(只碰A腿)。
純訊號+模擬帳本, 不接真實下單。先觀察forward表現, 之後再決定要不要接bot。
"""
import warnings, csv, os, numpy as np, pandas as pd, requests, time
warnings.filterwarnings('ignore')

FORWARD_START = '2026-07-13'          # 這條z分數track的起算日 (絕對不可往回調)
CAPITAL = 10000
WA = 0.5
A_COINS = ['BTC','ETH','SOL','LTC','LINK','ADA','DOGE','XLM']
T_COINS = ['BTC','ETH','SOL']
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'combo_forward_log.csv')

BN_HOSTS = ['https://data-api.binance.vision', 'https://api.binance.com']
def fetch_bn(sym, days=1200):
    end=int(time.time()*1000); start=end-days*86400*1000; rows=[]; cur=start
    while cur < end:
        r=None
        for host in BN_HOSTS:
            try:
                resp=requests.get(host+'/api/v3/klines',
                    params=dict(symbol=sym,interval='1d',startTime=cur,limit=1000),timeout=20).json()
                if isinstance(resp,list): r=resp; break
            except: continue
        if not isinstance(r,list) or not r: break
        rows+=r; cur=r[-1][0]+1
        if len(r)<1000: break
    if not rows: return None
    df=pd.DataFrame(rows,columns=list('tohlcv')+['ct','qv','n','tb','tq','ig'])
    df['t']=pd.to_datetime(df['t'],unit='ms'); df['c']=df['c'].astype(float)
    return df.drop_duplicates('t').set_index('t')['c']

def fetch_cb(prod, days=1200):
    end=int(time.time()); start=end-days*86400; rows=[]; cur=start
    while cur<end:
        seg=min(cur+250*86400,end)
        try:
            r=requests.get(f'https://api.exchange.coinbase.com/products/{prod}/candles',
                params=dict(granularity=86400,start=pd.to_datetime(cur,unit='s').isoformat(),
                            end=pd.to_datetime(seg,unit='s').isoformat()),timeout=20).json()
        except: r=None
        if isinstance(r,list): rows+=r
        cur=seg; time.sleep(0.1)
    if not rows: return None
    df=pd.DataFrame(rows,columns=['t','l','h','o','c','v']); df['t']=pd.to_datetime(df['t'],unit='s')
    return df.drop_duplicates('t').sort_values('t').set_index('t')['c'].astype(float)

def pos_A_sign(prem,fng):
    """原本4象限的方向(不含z分數縮放), 用來顯示訊號方向"""
    cbL=prem>0; greed=fng>60; p=pd.Series(0.0,index=prem.index)
    p[cbL&greed]=1.0; p[(~cbL)&greed]=-0.5; p[cbL&(~greed)]=0.5; p[(~cbL)&(~greed)]=-1.0
    return p

def z_magnitude(prem, window=90):
    """CB溢價偏離90日常態的z分數, 轉成0~1的倉位強度(2個標準差封頂在1, 不加槓桿)"""
    z=(prem-prem.rolling(window).mean())/prem.rolling(window).std()
    return (z.abs().clip(0,2)/2).fillna(0)

TODAY = pd.Timestamp.utcnow().tz_localize(None).normalize()

r=requests.get('https://api.alternative.me/fng/?limit=0&format=json',timeout=20).json()
fng=pd.DataFrame(r['data']); fng['value']=fng['value'].astype(int)
fng['date']=pd.to_datetime(fng['timestamp'].astype(int),unit='s').dt.normalize()
fng=fng.sort_values('date').set_index('date')['value']

# --- 引擎A (加z分數強度縮放) ---
A_rets={}; A_hit={}; A_sig=[]; candle=None
for c in A_COINS:
    bn=fetch_bn(c+'USDT'); cb=fetch_cb(c+'-USD')
    if bn is None or cb is None: print(f"  A {c} 資料失敗跳過"); continue
    d=pd.DataFrame({'p':bn}).dropna()
    d['prem']=((cb.reindex(d.index,method='ffill')/d['p']-1)*10000).rolling(7).mean()
    d['fng']=fng.reindex(d.index.normalize()).fillna(50); d=d.dropna()
    d=d[d.index<TODAY]
    sign=pos_A_sign(d['prem'],d['fng'])
    mag=z_magnitude(d['prem'])
    pos=sign*mag
    ret=d['p'].pct_change().fillna(0); pl=pos.shift(1).fillna(0)
    A_rets[c]=ret*pl - pl.diff().abs().fillna(0)*0.001
    A_hit[c]=(np.sign(pl)==np.sign(ret)).astype(float)
    A_sig.append((c,d['prem'].iloc[-1],d['fng'].iloc[-1],sign.iloc[-1],mag.iloc[-1],pos.iloc[-1]))
    candle=d.index[-1]

# --- 引擎B (SMA50趨勢, 完全不變) ---
T_rets={}; T_hit={}; T_sig=[]
for c in T_COINS:
    px=fetch_bn(c+'USDT')
    if px is None: print(f"  T {c} 資料失敗跳過"); continue
    px=px[px.index<TODAY]
    ma=px.rolling(50).mean(); pos=(px>ma).astype(float); pos.iloc[:50]=0
    ret=px.pct_change().fillna(0); pl=pos.shift(1).fillna(0)
    T_rets[c]=ret*pl - pl.diff().abs().fillna(0)*0.0004
    nz=pl!=0
    T_hit[c]=(np.sign(pl)==np.sign(ret)).where(nz)
    T_sig.append((c,px.iloc[-1],ma.iloc[-1],pos.iloc[-1]))

if not A_rets or not T_rets:
    print("資料抓取失敗, 結束"); raise SystemExit

A=pd.DataFrame(A_rets); Aret=A.div((~A.isna()).sum(axis=1),axis=0).fillna(0).sum(axis=1)
T=pd.DataFrame(T_rets); Tret=T.mean(axis=1)
J=pd.concat([Aret.rename('A'),Tret.rename('T')],axis=1).dropna()
J['C']=WA*J['A']+(1-WA)*J['T']

fs=pd.Timestamp(FORWARD_START)
def eq(series):
    s=series[series.index>=fs]; return (1+s).prod()
days_fwd=(J.index[-1]-fs).days if J.index[-1]>=fs else 0
eqA,eqT,eqC=eq(J['A']),eq(J['T']),eq(J['C'])

def light(h):
    return '🟢綠燈' if h>=52 else '🟡黃燈' if h>=48 else '🔴紅燈'
hitA=np.nanmean([A_hit[c].tail(90).mean()*100 for c in A_hit])
hitT=np.nanmean([T_hit[c].tail(90).mean()*100 for c in T_hit])

def sharpe(s,b=365):
    s=s.dropna(); return (s.mean()*b)/(s.std()*np.sqrt(b)) if s.std()>0 else 0
def se(SR,years):
    return np.sqrt((1+0.5*SR**2)/years) if years>0 else float('inf')
SR_bt=sharpe(J['C']); yrs_bt=len(J)/365; se_bt=se(SR_bt,yrs_bt)
fwd=J['C'][J.index>=fs]; SR_fw=sharpe(fwd) if len(fwd)>2 else float('nan')
yrs_fw=days_fwd/365; se_fw=se(SR_fw if not np.isnan(SR_fw) else 1.0, yrs_fw)

print('='*64)
print(f"  【z分數track】A加z分數{int(WA*100)}% + SMA50趨勢原版{int((1-WA)*100)}%  |  日K: {candle.date()}")
print('='*64)
print(f"\n【引擎A 8幣訊號】溢價7d / FNG / 方向 / z強度 / 實際倉位")
for c,pr,fv,sg,mg,ps in A_sig:
    lsd='滿多' if sg==1 else '半多' if sg==0.5 else '半空' if sg==-0.5 else '滿空'
    print(f"  {c:5}{pr:>8.1f}bp{fv:>5.0f}  方向{sg:+.1f}({lsd})  強度{mg*100:>3.0f}%  →實際{ps:+.2f}")
print(f"\n【引擎B 趨勢訊號】價格 vs SMA50 (不變)")
for c,px_,ma_,ps in T_sig:
    print(f"  {c:5} {'價>均→做多' if ps==1 else '價<均→現金':}  (px {px_:.2f} / ma {ma_:.2f})")

print(f"\n--- 模擬金 (本金 ${CAPITAL:,}, 起始 {FORWARD_START}, 已 {days_fwd} 天) ---")
print(f"  純A(加z分數): ${CAPITAL*eqA:,.0f}  ({(eqA-1)*100:+.1f}%)")
print(f"  純趨勢(不變) : ${CAPITAL*eqT:,.0f}  ({(eqT-1)*100:+.1f}%)")
print(f"  50/50組合    : ${CAPITAL*eqC:,.0f}  ({(eqC-1)*100:+.1f}%)   ← 主策略")

print(f"\n--- 健康度 (90日命中率) ---")
print(f"  引擎A(CB溢價加z): {hitA:.1f}%  {light(hitA)}")
print(f"  引擎B(趨勢原版) : {hitT:.1f}%  {light(hitT)}")

print(f"\n--- Sharpe 可信度 ---")
print(f"  回測(此腳本近{yrs_bt:.1f}年資料): Sharpe {SR_bt:.2f} ± {se_bt:.2f}")
if yrs_fw>0.05 and not np.isnan(SR_fw):
    print(f"  Forward : Sharpe {SR_fw:.2f} ± {se_fw:.1f}  (才{yrs_fw:.2f}年 → 誤差巨大, 現在的數字沒意義)")
else:
    print(f"  Forward : 才 {days_fwd} 天, 樣本太少")
print(f"  ★ 這是平行對照track, 目的是觀察真實forward表現, 不接真實下單")

key=str(candle.date()); existing=set()
if os.path.exists(LOG):
    with open(LOG,encoding='utf-8-sig') as f:
        for row in csv.reader(f):
            if len(row)>1: existing.add(row[0])
if key in existing:
    print(f"\n(日K {key} 已記錄, 略過寫入 — 正常去重)")
else:
    newfile=not os.path.exists(LOG)
    with open(LOG,'a',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f)
        if newfile:
            w.writerow(['日K基準','執行UTC','組合$','純A$','純趨勢$','A命中率','趨勢命中率','A燈','趨勢燈','forward天數'])
        now=pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M')
        w.writerow([key,now,round(CAPITAL*eqC),round(CAPITAL*eqA),round(CAPITAL*eqT),
                    round(hitA,1),round(hitT,1),light(hitA),light(hitT),days_fwd])
    print(f"\n✅ 已記錄日K {key} 到 combo_forward_log.csv")
