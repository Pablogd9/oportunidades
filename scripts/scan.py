#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor del escaner de oportunidades - version 11.

Novedades vs v10:
  - 13 sectores: +Agua, +Energia Limpia, +Cobre, +Genomica
  - Curva de tipos (DGS10-DGS2) en deteccion de regimen
  - Umbral minimo score 48 con fallback a IWDA
  - Correlacion entre sectores para seleccion del Top2
  - Earnings revision momentum (EPS estimado actual vs hace 3M)
  - Diario automatizado de senales (history.json)
  - Nuevos perfiles macro: water_scarcity, clean_energy, copper_transition
"""

import json, math, os, urllib.request, datetime, time

ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI     = os.path.join(ROOT, "universe.json")
MACRO   = os.path.join(ROOT, "data", "macro.json")
OUT     = os.path.join(ROOT, "data", "output.json")
HISTORY = os.path.join(ROOT, "data", "history.json")
UA      = {"User-Agent": "Mozilla/5.0 (compatible; QuantScanner/11.0)"}
WARN    = []

CARTERA = [
    {"id":"SEMI","symbol":"SEMI.AS","name":"iShares MSCI Global Semiconductors","sector":"Semiconductores"},
    {"id":"BTC", "symbol":"BTC-EUR", "name":"Bitcoin",                           "sector":"Bitcoin y Cripto"},
]

W_TECH_BASE = {"rel_strength":0.25,"ema200":0.25,"mom6m":0.20,"entry":0.20,"consistency":0.10}
W_FINAL     = {"tech":0.85,"macro":0.15}
MIN_HISTORY_DAYS = 756
MIN_AUM_BN       = 0.5
SCORE_FALLBACK   = 48
SCORE_WEAK       = 55
MAX_CORRELATION  = 0.70

ETF_HOLDINGS = {
    "WTAI": ["NVDA","MSFT","GOOGL","META","AMZN","TSM","AVGO","ORCL","PLTR","CRM",
              "SNOW","AMAT","KLAC","ASML","AMD","INTC","QCOM","TXN","NOW","ADSK"],
    "ROBO": ["ISRG","ABB","FANUC","KEYB","IRBT","BRKS","MKSI","NOVT","NDSN","TRMB",
              "ROP","AZTA","ONTO","LRCX","GTLS","ITRI","XYL","FLOW","REXR","BRKR"],
    "ITA":  ["RTX","LMT","NOC","GD","BA","L3H","HII","TDG","HEI","TXT",
              "LDOS","SAIC","CACI","BAH","MOOG","AXON","KTOS","AVAV","SPR","DRS"],
    "INDA": ["INFY","WIPRO","HDB","IBN","WIT","AXBK","HDFCB","RELIANCE","BHARTIARTL","TCS",
              "HINDUNILVR","ICICIBC","SBIN","LT","KOTAKBANK","BAJFINANCE","ASIANPAINT","ULTRACEMCO","TITAN","NESTLEIND"],
    "FLIN": ["INFY","HDB","IBN","RELIANCE","HDFCB","WIT","TCS","BHARTIARTL","ICICIBC","SBIN",
              "KOTAKBANK","BAJFINANCE","LT","ASIANPAINT","ULTRACEMCO","TITAN","NESTLEIND","POWERGRID","NTPC","COALINDIA"],
    "COPX": ["FCX","SCCO","BHP","RIO","GLEN","TECK","FM","HBM","CMMC","ERO",
              "LUNR","IVN","ANTO","CS","TGB","GEX","NGEX","MTAL","CU","FQVLF"],
    "GNOM": ["ILMN","PACB","RXRX","CRSP","EDIT","NTLA","BEAM","VERV","IONS","ALNY",
              "MRNA","REGN","VRTX","BMRN","FATE","BLUE","SGMO","ARCT","TBIO","BLUE"],
    "PHO":  ["XYL","AWK","PRIM","ARIS","MSEX","SJW","AWR","CWT","NI","GHM",
              "ITRI","WATTS","GWW","ARTNA","XYLEM","WTR","LAYNE","GWCO","YORW","MUELLER"],
    "ICLN": ["NEE","ENPH","FSLR","BEP","SEDG","CWEN","PLUG","HASI","AY","ARRY",
              "MAXN","SPWR","RUN","AMRC","NOVA","NEP","ORSTED","VESTAS","RWE","BEPC"],
}

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_history(symbol, rng="5y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d"
    try:
        d=_get(url); res=d["chart"]["result"][0]
        ts=res.get("timestamp") or []
        cls=(res.get("indicators") or {}).get("quote",[{}])[0].get("close") or []
        pairs={}
        for t,c in zip(ts,cls):
            if c is None: continue
            pairs[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")]=float(c)
        series=sorted(pairs.items())
        return [c for _,c in series],[d for d,_ in series]
    except Exception as e:
        WARN.append(f"{symbol}: {e}"); return None,None

def fetch_history_weekly(symbol, rng="5y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1wk"
    try:
        d=_get(url); res=d["chart"]["result"][0]
        ts=res.get("timestamp") or []
        cls=(res.get("indicators") or {}).get("quote",[{}])[0].get("close") or []
        pairs={}
        for t,c in zip(ts,cls):
            if c is None: continue
            pairs[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")]=float(c)
        series=sorted(pairs.items())
        return [c for _,c in series],[d for d,_ in series]
    except Exception as e:
        WARN.append(f"{symbol}_weekly: {e}"); return None,None

def fetch_close_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d"
    try:
        d=_get(url); res=d["chart"]["result"][0]
        ts=res.get("timestamp") or []
        cls=(res.get("indicators") or {}).get("quote",[{}])[0].get("close") or []
        pairs={}
        for t,c in zip(ts,cls):
            if c is None: continue
            pairs[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")]=float(c)
        series=sorted(pairs.items())
        return [c for _,c in series]
    except: return None

def fetch_fundamentals(symbol):
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=summaryDetail,defaultKeyStatistics,financialData"
    try:
        d=_get(url); r=d["quoteSummary"]["result"][0]
        sd=r.get("summaryDetail",{}); ks=r.get("defaultKeyStatistics",{}); fd=r.get("financialData",{})
        pe_t=(sd.get("trailingPE") or {}).get("raw")
        pe_f=(sd.get("forwardPE") or {}).get("raw") or (ks.get("forwardPE") or {}).get("raw")
        beta=(ks.get("beta") or {}).get("raw") or (sd.get("beta") or {}).get("raw")
        dy=(sd.get("dividendYield") or {}).get("raw")
        ge=(fd.get("earningsGrowth") or {}).get("raw") or (fd.get("revenueGrowth") or {}).get("raw")
        eps_f=(ks.get("forwardEps") or {}).get("raw")
        eps_t=(ks.get("trailingEps") or {}).get("raw")
        return {"pe":round(pe_t,1) if pe_t else None,"pe_forward":round(pe_f,1) if pe_f else None,
                "beta":round(beta,2) if beta else None,"dy":round(dy*100,2) if dy else None,
                "growth_est":round(ge*100,1) if ge else None,
                "eps_forward":round(eps_f,2) if eps_f else None,
                "eps_trailing":round(eps_t,2) if eps_t else None}
    except: return {"pe":None,"pe_forward":None,"beta":None,"dy":None,"growth_est":None,"eps_forward":None,"eps_trailing":None}

def ema_n(prices,n):
    if len(prices)<n: return None
    k=2.0/(n+1); ema=sum(prices[:n])/n
    for p in prices[n:]: ema=p*k+ema*(1-k)
    return ema

def ret_n(prices,n):
    if len(prices)<n+1: return None
    p0,p1=prices[-(n+1)],prices[-1]
    return (p1/p0-1)*100 if p0>0 else None

def vol_annual(prices,n=60):
    if len(prices)<n+1: return None
    rets=[prices[i]/prices[i-1]-1 for i in range(max(1,len(prices)-n),len(prices))]
    if len(rets)<5: return None
    mean=sum(rets)/len(rets)
    sd=math.sqrt(sum((r-mean)**2 for r in rets)/(len(rets)-1))
    return sd*math.sqrt(252)*100

def vol_std(prices,n=252): return vol_annual(prices,min(n,len(prices)-1)) or 20.0

def drawdown_from_max(prices,n=252):
    if len(prices)<2: return None
    window=prices[-min(n,len(prices)):]; peak=max(window)
    return round((prices[-1]/peak-1)*100,2) if peak>0 else None

def drawdown_alltime(prices):
    if len(prices)<2: return None
    peak=max(prices)
    return round((prices[-1]/peak-1)*100,2) if peak>0 else None

def ann_ret(prices,n=252):
    actual=min(n,len(prices)-1)
    if actual<20: return None
    return round((prices[-1]/prices[-actual-1])**(252/actual)*100-100,1)

def consistency_6m(prices):
    if len(prices)<130: return None
    monthly=[]
    for i in range(6):
        start=-(21*(i+1)+1); end=-(21*i+1) if i>0 else -1
        if abs(start)>=len(prices): continue
        p0=prices[start]; p1=prices[end]
        if p0>0: monthly.append(p1/p0-1)
    if len(monthly)<4: return None
    return round(sum(1 for r in monthly if r>0)/len(monthly)*100,0)

def percentile_in_own_history(value,series):
    if value is None or not series: return 50.0
    return round(sum(1 for v in series if v<=value)/len(series)*100,1)

def compute_correlation_matrix(sector_prices_dict, n_months=12):
    n_days=n_months*21; monthly_rets={}
    for sector,prices in sector_prices_dict.items():
        if not prices or len(prices)<n_days+21: continue
        rets=[]
        for i in range(n_months):
            start=-(n_days-i*21+1); end=-(n_days-(i+1)*21+1) if i<n_months-1 else -1
            if abs(start)>=len(prices): continue
            p0=prices[start]; p1=prices[end]
            if p0>0: rets.append((p1/p0-1)*100)
        if len(rets)>=6: monthly_rets[sector]=rets
    correlations={}
    sectors=list(monthly_rets.keys())
    for i,sa in enumerate(sectors):
        for sb in sectors[i+1:]:
            ra=monthly_rets[sa]; rb=monthly_rets[sb]
            n=min(len(ra),len(rb))
            if n<6: continue
            ra_n=ra[-n:]; rb_n=rb[-n:]
            ma=sum(ra_n)/n; mb=sum(rb_n)/n
            cov=sum((ra_n[j]-ma)*(rb_n[j]-mb) for j in range(n))/n
            sa_std=math.sqrt(sum((r-ma)**2 for r in ra_n)/n)
            sb_std=math.sqrt(sum((r-mb)**2 for r in rb_n)/n)
            if sa_std>0 and sb_std>0:
                corr=round(cov/(sa_std*sb_std),3)
                correlations[(sa,sb)]=corr; correlations[(sb,sa)]=corr
    return correlations

def get_correlation(correlations,sector_a,sector_b):
    return correlations.get((sector_a,sector_b),0.0)

def compute_earnings_revision(fund, history_rec=None):
    eps_now=fund.get("eps_forward")
    if eps_now is None: return 0,"Sin datos EPS forward"
    if history_rec and "eps_forward" in history_rec:
        eps_prev=history_rec["eps_forward"]
        if eps_prev and eps_prev!=0:
            chg=(eps_now-eps_prev)/abs(eps_prev)*100
            if chg>5: return 5,f"EPS forward +{chg:.1f}% — analistas revisan al alza"
            elif chg>2: return 2,f"EPS forward ligeramente al alza (+{chg:.1f}%)"
            elif chg<-5: return -5,f"EPS forward {chg:.1f}% — analistas revisan a la baja"
            elif chg<-2: return -2,f"EPS forward ligeramente a la baja ({chg:.1f}%)"
            else: return 0,f"EPS forward estable ({chg:.1f}%)"
    return 0,"Sin historial de EPS para comparar"

def detect_market_regime(macro):
    vix_val=macro.get("vix",{}).get("value")
    vix_trend=macro.get("vix",{}).get("trend","neutral")
    iwda_ret6=macro.get("iwda",{}).get("ret_6m")
    dgs10=macro.get("interest_rates",{}).get("dgs10")
    dgs2=macro.get("interest_rates",{}).get("dgs2")
    ycs=None; yci=False
    if dgs10 and dgs2: ycs=round(dgs10-dgs2,2); yci=ycs<0
    if yci and vix_val and vix_val>20: regime="bear"; note="Curva invertida + VIX elevado"
    elif vix_val and vix_val>35 and vix_trend=="down": regime="opportunity"; note="VIX extremo bajando"
    elif vix_val and vix_val>25: regime="bear"; note="VIX elevado"
    elif yci: regime="neutral"; note="Curva invertida — señal anticipada"
    elif iwda_ret6 and iwda_ret6>10 and vix_val and vix_val<20: regime="bull"; note=f"IWDA +{iwda_ret6:.1f}% 6M, VIX bajo"
    else: regime="neutral"; note="Condiciones mixtas"
    if regime=="bull": wt={"rel_strength":0.30,"ema200":0.25,"mom6m":0.25,"entry":0.10,"consistency":0.10}
    elif regime=="bear": wt={"rel_strength":0.20,"ema200":0.20,"mom6m":0.15,"entry":0.35,"consistency":0.10}
    elif regime=="opportunity": wt={"rel_strength":0.15,"ema200":0.15,"mom6m":0.10,"entry":0.50,"consistency":0.10}
    else: wt=W_TECH_BASE.copy()
    if regime=="bull": sp={"defensive_demographics":0.90,"defensive_government":0.95,"rates_debt_sensitive":0.90,"water_scarcity":0.92}
    elif regime=="bear": sp={"growth_rates_sensitive":0.85,"crypto_halving":0.80,"copper_transition":0.88,"clean_energy":0.85}
    else: sp={}
    desc={"bull":"Mercado alcista fuerte — priorizando momentum y liderazgo",
          "bear":"Mercado bajista — priorizando punto de entrada sobre momentum",
          "opportunity":"Pánico extremo — máxima prioridad a precio de entrada",
          "neutral":"Mercado neutral — pesos estándar"}
    return {"regime":regime,"w_tech":wt,"sector_penalties":sp,"description":desc[regime],
            "regime_note":note,"vix":vix_val,"iwda_6m":iwda_ret6,
            "yield_curve_spread":ycs,"yield_curve_inverted":yci}

def compute_breadth_from_pair(prices_ew,prices_cw):
    if not prices_ew or not prices_cw: return 0,"Sin datos de breadth"
    re=ret_n(prices_ew,min(63,len(prices_ew)-1)); rc=ret_n(prices_cw,min(63,len(prices_cw)-1))
    if re is None or rc is None: return 0,"Sin datos de breadth"
    d=re-rc
    if d>5: return 8,f"Breadth positivo — pequeñas lideran (+{d:.1f}%)"
    elif d>2: return 4,f"Breadth moderadamente positivo (+{d:.1f}%)"
    elif d>-2: return 0,f"Breadth neutro ({d:.1f}%)"
    elif d>-5: return -4,f"Breadth negativo — solo grandes suben ({d:.1f}%)"
    else: return -8,f"Breadth muy negativo — concentrado ({d:.1f}%)"

def compute_breadth_from_holdings(etf_id):
    holdings=ETF_HOLDINGS.get(etf_id,[])
    if not holdings: return 0,"Sin datos de holdings",None
    above=0; total=0
    for ticker in holdings:
        try:
            prices=fetch_close_price(ticker)
            if not prices or len(prices)<55: continue
            e50=ema_n(prices,50)
            if e50 and prices[-1]>e50: above+=1
            total+=1; time.sleep(0.1)
        except: continue
    if total<5: return 0,"Datos insuficientes",None
    pct=round(above/total*100,0)
    if pct>=75: return 8,f"Breadth excelente — {pct:.0f}% sobre EMA50",pct
    elif pct>=60: return 4,f"Breadth positivo — {pct:.0f}% sobre EMA50",pct
    elif pct>=40: return 0,f"Breadth neutro — {pct:.0f}% sobre EMA50",pct
    elif pct>=25: return -4,f"Breadth negativo — {pct:.0f}% sobre EMA50",pct
    else: return -8,f"Breadth muy negativo — {pct:.0f}% sobre EMA50",pct

def detect_failure_patterns(prices,macro_profile,regime):
    patterns=[]; penalty=1.0; mwa=0.0
    d5y=drawdown_alltime(prices); m6=ret_n(prices,min(126,len(prices)-1)); m3=ret_n(prices,min(63,len(prices)-1))
    if macro_profile in {"defensive_demographics","defensive_government","rates_debt_sensitive","water_scarcity"} and regime=="bull":
        penalty*=0.88; patterns.append("Patrón A: sector defensivo en mercado alcista — históricamente queda rezagado")
    if d5y is not None and d5y<-30 and m6 is not None and m6>25:
        mwa=-0.08; patterns.append(f"Patrón B: recuperación desde mínimos extremos ({d5y:.0f}%) — posible rebote")
    if m3 is not None and m3>50:
        penalty*=0.90; patterns.append(f"Momentum 3M extremo (+{m3:.1f}%) — posible euforia")
    return penalty,patterns,mwa

def compute_overvaluation(prices,fund):
    signals=[]; sc=0; bonus=False
    pe=fund.get("pe"); ge=fund.get("growth_est"); per_exp=None
    if pe and len(prices)>=252:
        p12=prices[-253] if len(prices)>252 else prices[0]
        if p12>0 and prices[-1]>0:
            pr=prices[-1]/p12; per_exp=pe/(pe/pr)
            if per_exp>1.5: signals.append(f"PER expandido x{per_exp:.1f}"); sc+=1
            elif per_exp>1.3: signals.append(f"Expansión moderada (x{per_exp:.1f})"); sc+=0.5
            elif per_exp<0.8: bonus=True
    peg=None
    if pe and ge and ge>0:
        peg=round(pe/ge,2)
        if peg>3: signals.append(f"PEG muy alto ({peg:.1f})"); sc+=1
        elif peg>2: signals.append(f"PEG elevado ({peg:.1f})"); sc+=0.5
        elif peg<1: bonus=True
    dat=drawdown_alltime(prices)
    if dat is not None:
        if dat>-2: signals.append(f"En maximos historicos ({dat:.1f}%)"); sc+=1
        elif dat>-5: signals.append(f"Cerca de maximos ({dat:.1f}%)"); sc+=0.5
    m3=ret_n(prices,63); m3h=[]; n=len(prices)
    for i in range(1,min(504,n-63)):
        r=ret_n(prices[:n-i],63)
        if r is not None: m3h.append(r)
    if m3 is not None and m3h:
        avg=sum(m3h)/len(m3h)
        if avg>0 and m3>avg*3: signals.append(f"Mom3M {m3:.1f}%={m3/avg:.1f}x media"); sc+=1
        elif avg>0 and m3>avg*2: signals.append("Mom3M acelerado"); sc+=0.5
    if sc>=2.5: pen=0.5; lvl="🔴 Burbuja probable"
    elif sc>=1.5: pen=0.7; lvl="🟠 Sobrevaloración significativa"
    elif sc>=0.5: pen=0.85; lvl="🟡 Ligera sobrevaloración"
    elif bonus: pen=1.10; lvl="🟢 Precio justificado"
    else: pen=1.0; lvl="⚪ Valoración neutral"
    return {"overval_score":round(min(100,sc/3*100),0),"signals":signals,"penalty":pen,"level":lvl,
            "per_expansion":round(per_exp,2) if per_exp else None,"peg":peg,"dist_alltime":dat,"bonus":bonus}

def compute_technical_score(prices,iwda_prices,w_tech,mwa=0.0):
    if not prices or len(prices)<60: return None,{}
    n=len(prices); vol=vol_std(prices,min(252,n-1)); det={}
    w=dict(w_tech)
    if mwa!=0.0:
        w["mom6m"]=max(0.05,w["mom6m"]+mwa); w["entry"]=min(0.50,w["entry"]-mwa)
    total=sum(w.values()); w={k:v/total for k,v in w.items()}
    rs=None; rsh=[]
    if iwda_prices and len(iwda_prices)>=126:
        re=ret_n(prices,min(126,n-1)); ri=ret_n(iwda_prices,min(126,len(iwda_prices)-1))
        if re is not None and ri is not None: rs=(re-ri)/(vol/20.0)
        for i in range(126,min(n,756)):
            pe=prices[:n-i+126] if n-i+126>126 else prices[:126]
            pi=iwda_prices[:len(iwda_prices)-i+126] if len(iwda_prices)-i+126>126 else iwda_prices[:126]
            ree=ret_n(pe,126); rii=ret_n(pi,126)
            if ree is not None and rii is not None:
                rsh.append((ree-rii)/(vol_std(pe,min(252,len(pe)-1))/20.0))
    pct_rs=percentile_in_own_history(rs,rsh)
    det["rel_strength"]={"value":round(rs,2) if rs else None,"percentile":pct_rs,
        "interpretation":("Lidera al mercado" if rs and rs>1 else "Va por detrás" if rs and rs<-1 else "En línea")}
    e200=ema_n(prices,min(200,n)); de200=((prices[-1]/e200-1)*100) if e200 else None
    en=(de200/(vol/20.0)) if de200 else None; eh=[]
    for i in range(1,min(504,n-200)):
        pc=prices[:n-i]; e=ema_n(pc,min(200,len(pc)))
        if e: eh.append(((pc[-1]/e-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pct_e=percentile_in_own_history(en,eh)
    det["ema200"]={"value":round(de200,2) if de200 else None,"ema200_abs":round(e200,4) if e200 else None,
        "percentile":pct_e,"above":de200>0 if de200 is not None else None,
        "interpretation":(f"Muy por encima EMA200 (+{de200:.1f}%)" if de200 and de200>15
            else f"Por encima EMA200 (+{de200:.1f}%)" if de200 and de200>0
            else f"Por debajo EMA200 ({de200:.1f}%)" if de200 else "Sin datos EMA200")}
    m6=ret_n(prices,min(126,n-1)); m6n=(m6/(vol/20.0)) if m6 is not None else None; m6h=[]
    for i in range(1,min(756,n-126)):
        pc=prices[:n-i]; r=ret_n(pc,min(126,len(pc)-1))
        if r is not None: m6h.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pct_m6=percentile_in_own_history(m6n,m6h)
    det["mom6m"]={"value":round(m6,2) if m6 else None,"percentile":pct_m6,
        "interpretation":(f"Momentum 6M excepcional (+{m6:.1f}%)" if m6 and m6>30
            else f"Momentum 6M fuerte (+{m6:.1f}%)" if m6 and m6>10
            else f"Momentum 6M positivo (+{m6:.1f}%)" if m6 and m6>0
            else f"Momentum 6M negativo ({m6:.1f}%)" if m6 else "Sin datos")}
    d52=drawdown_from_max(prices,252); d5y=drawdown_alltime(prices)
    ec=d52*0.60+d5y*0.40 if d52 is not None and d5y is not None else d52
    dh=[]
    for i in range(1,min(756,n-252)):
        pc=prices[:n-i]; d=drawdown_from_max(pc,min(252,len(pc)))
        if d is not None: dh.append(-d)
    pct_en=percentile_in_own_history(-ec if ec is not None else None,dh)
    det["entry"]={"dist_from_max_52w":d52,"dist_from_max_5y":d5y,"percentile":pct_en,
        "interpretation":(f"Excelente entrada: {d5y:.0f}% bajo máximos" if d5y and d5y<-25
            else f"Buena entrada: {d52:.0f}% bajo máximos 52s" if d52 and d52<-10
            else "En máximos — entrada exigente" if d5y and d5y>-3
            else f"Cerca de máximos ({d52:.0f}%)" if d52 else "Sin datos")}
    co=consistency_6m(prices); coh=[]
    for i in range(1,min(756,n-130)):
        pc=prices[:n-i]; c=consistency_6m(pc)
        if c is not None: coh.append(c)
    pct_co=percentile_in_own_history(co,coh)
    det["consistency"]={"value":co,"percentile":pct_co,
        "interpretation":(f"Muy consistente ({co:.0f}%)" if co and co>=80
            else f"Consistente ({co:.0f}%)" if co and co>=60
            else f"Inconsistente ({co:.0f}%)" if co else "Sin datos")}
    score=(w["rel_strength"]*pct_rs+w["ema200"]*pct_e+w["mom6m"]*pct_m6+
           w["entry"]*pct_en+w["consistency"]*pct_co)
    m3=ret_n(prices,min(63,n-1)); pen=1.0
    if m3 is not None and m3<-10:
        pen=0.6; det["penalty"]={"applied":True,"reason":f"Caída 3M ({m3:.1f}%) — ×0.6","mom3m":round(m3,2)}
    else: det["penalty"]={"applied":False,"mom3m":round(m3,2) if m3 else None}
    det["extra"]={"r1m":round(ret_n(prices,21),2) if ret_n(prices,21) else None,
        "r3m":round(m3,2) if m3 else None,"r6m":round(m6,2) if m6 else None,
        "r12m":round(ret_n(prices,252),2) if ret_n(prices,252) else None,
        "vol":round(vol_annual(prices),1) if vol_annual(prices) else None,
        "drawdown":d52,"ann_ret":ann_ret(prices),"dist_max_5y":d5y}
    det["w_used"]=w
    return round(score*pen,1),det

def compute_macro_score(macro_profile,macro):
    if not macro: return 50,{}
    rates=macro.get("interest_rates",{}); dxy=macro.get("dxy",{})
    inr=macro.get("inr",{}); ux=macro.get("uranium_spot",{}); halving=macro.get("bitcoin_halving",{})
    rs=rates.get("score",50); di=dxy.get("score_inverse",50)
    us=ux.get("score",50); hs=halving.get("halving_score",50); det={}
    if macro_profile=="growth_rates_sensitive":
        s=rs; det={"tipos":{"weight":"100%","score":rs,"desc":rates.get("interpretation","")}}
    elif macro_profile=="defensive_government":
        s=65; det={"base":{"weight":"100%","score":65,"desc":"Gasto gubernamental estructural"}}
    elif macro_profile=="em_dollar_sensitive":
        s=di*0.60+rs*0.40
        if inr.get("trend")=="down": s*=0.85; det["rupia"]={"desc":"Rupia depreciándose"}
        det.update({"dolar":{"weight":"60%","score":di,"desc":dxy.get("interpretation","")},
                    "tipos":{"weight":"40%","score":rs,"desc":rates.get("interpretation","")}})
    elif macro_profile=="defensive_growth":
        s=rs*0.40+70*0.60
        det={"tipos":{"weight":"40%","score":rs,"desc":rates.get("interpretation","")},
             "base":{"weight":"60%","score":70,"desc":"Demanda estructural no cíclica"}}
    elif macro_profile=="rates_debt_sensitive":
        s=rs; det={"tipos":{"weight":"100%","score":rs,"desc":rates.get("interpretation","")}}
    elif macro_profile=="defensive_demographics":
        s=65; det={"base":{"weight":"100%","score":65,"desc":"Envejecimiento inevitable"}}
    elif macro_profile=="crypto_halving":
        s=rs*0.30+di*0.30+hs*0.40
        det={"tipos":{"weight":"30%","score":rs},"dolar":{"weight":"30%","score":di},
             "halving":{"weight":"40%","score":hs,"desc":halving.get("description","")}}
    elif macro_profile=="uranium_spot":
        s=us*0.70+rs*0.30
        det={"uranio_spot":{"weight":"70%","score":us,"desc":ux.get("interpretation","")},
             "tipos":{"weight":"30%","score":rs}}
    elif macro_profile=="water_scarcity":
        s=65*0.70+di*0.30
        det={"base":{"weight":"70%","score":65,"desc":"Escasez estructural — demanda inelástica"},
             "dolar":{"weight":"30%","score":di,"desc":dxy.get("interpretation","")}}
    elif macro_profile=="clean_energy":
        s=rs*0.50+di*0.30+60*0.20
        det={"tipos":{"weight":"50%","score":rs,"desc":rates.get("interpretation","")},
             "dolar":{"weight":"30%","score":di,"desc":dxy.get("interpretation","")},
             "politica":{"weight":"20%","score":60,"desc":"Transición energética estructural"}}
    elif macro_profile=="copper_transition":
        s=di*0.40+rs*0.30+65*0.30
        det={"dolar":{"weight":"40%","score":di,"desc":"Dólar débil favorece commodities"},
             "tipos":{"weight":"30%","score":rs,"desc":rates.get("interpretation","")},
             "demanda":{"weight":"30%","score":65,"desc":"Electrificación global — demanda estructural"}}
    else: s=50
    return round(min(100,max(0,s)),1),det

def compute_final_score(st,sm,op,fp,srp,bs,er_adj=0):
    base=st*W_FINAL["tech"]+sm*W_FINAL["macro"]
    adjusted=base*op*fp*srp
    return round(max(0,min(100,adjusted+bs*0.6+er_adj*0.5)),1)

def ema200_signal_daily(prices):
    if len(prices)<200: return "neutral"
    e200=ema_n(prices,200)
    if e200 is None: return "neutral"
    dd=drawdown_from_max(prices); mb=0
    for i in range(6):
        idx=-(21*(i+1))
        if abs(idx)>len(prices): break
        wp=prices[:len(prices)+idx+21]
        if len(wp)<200: break
        e=ema_n(wp,200)
        if e and wp[-1]<e: mb+=1
        else: break
    if prices[-1]>e200: return "green"
    elif mb>=3 and dd is not None and dd<-15: return "red"
    else: return "yellow"

def ema200_signal_weekly(pw):
    n=len(pw); ep=min(200,n-1) if n>50 else None
    if ep is None: return "neutral"
    e200=ema_n(pw,ep)
    if e200 is None: return "neutral"
    dd=drawdown_from_max(pw); wb=0
    for i in range(13):
        if i+1>len(pw): break
        wp=pw[:len(pw)-(i+1)]
        if len(wp)<ep: break
        e=ema_n(wp,ep)
        if e and wp[-1]<e: wb+=1
        else: break
    if pw[-1]>e200: return "green"
    elif wb>=13 and dd is not None and dd<-15: return "red"
    else: return "yellow"

def build_portfolio_signals(cartera):
    signals=[]
    for asset in cartera:
        ic=asset["sector"]=="Bitcoin y Cripto"
        if ic:
            pw,dw=fetch_history_weekly(asset["symbol"],"5y"); pd,dd=fetch_history(asset["symbol"],"5y")
            if not pw or len(pw)<50:
                signals.append({**asset,"signal":"neutral","signal_text":"Sin datos","dist_ema200":None,"r3m":None,"r12m":None,"drawdown":None,"sparkline":[],"spark_dates":[]})
                continue
            sig=ema200_signal_weekly(pw); e200=ema_n(pw,min(200,len(pw)-1))
            de=round((pw[-1]/e200-1)*100,1) if e200 else None; pm=pd or pw; ds=dd or dw
        else:
            pd,dd=fetch_history(asset["symbol"],"5y")
            if not pd or len(pd)<60:
                signals.append({**asset,"signal":"neutral","signal_text":"Sin datos","dist_ema200":None,"r3m":None,"r12m":None,"drawdown":None,"sparkline":[],"spark_dates":[]})
                continue
            sig=ema200_signal_daily(pd); e200=ema_n(pd,200)
            de=round((pd[-1]/e200-1)*100,1) if e200 else None; pm=pd; ds=dd
        r3m=ret_n(pm,63); r12m=ret_n(pm,252); drw=drawdown_from_max(pm)
        txt=("Tesis intacta — EMA200 alcista. Sigue aportando." if sig=="green"
             else f"Atención — EMA200 {'semanal' if ic else 'diaria'} bajo. Vigilar." if sig=="yellow"
             else f"Señal de salida — EMA200 {'semanal' if ic else 'diaria'} rota. Considera rotar.")
        signals.append({**asset,"signal":sig,"signal_text":txt,"dist_ema200":de,
            "ema_type":"weekly" if ic else "daily",
            "r3m":round(r3m,2) if r3m else None,"r12m":round(r12m,2) if r12m else None,"drawdown":drw,
            "sparkline":[round(p,4) for p in pm[-60:]],"spark_dates":ds[-60:] if ds else []})
    return signals

def load_history():
    if os.path.exists(HISTORY):
        with open(HISTORY,encoding="utf-8") as f: return json.load(f)
    return {"signals":[]}

def save_to_history(recommendation,sector_ranking,regime_info,portfolio_signals):
    history=load_history(); today=datetime.date.today().isoformat(); mk=today[:7]
    if any(s.get("month")==mk for s in history["signals"]):
        print(f"  Señal de {mk} ya registrada."); return
    entry={"month":mk,"date":today,"regime":regime_info.get("regime"),
        "score_top1":recommendation.get("score_top1"),"calidad":recommendation.get("calidad"),
        "top1":{"symbol":recommendation["distribucion"][0]["symbol"] if recommendation.get("distribucion") else None,
                "sector":recommendation["distribucion"][0]["sector"] if recommendation.get("distribucion") else None,
                "score":recommendation["distribucion"][0]["score"] if recommendation.get("distribucion") else None,
                "euros":recommendation["distribucion"][0]["euros"] if recommendation.get("distribucion") else None},
        "top2":{"symbol":recommendation["distribucion"][1]["symbol"] if len(recommendation.get("distribucion",[]))>1 else None,
                "sector":recommendation["distribucion"][1]["sector"] if len(recommendation.get("distribucion",[]))>1 else None,
                "score":recommendation["distribucion"][1]["score"] if len(recommendation.get("distribucion",[]))>1 else None,
                "euros":recommendation["distribucion"][1]["euros"] if len(recommendation.get("distribucion",[]))>1 else None},
        "portfolio_signals":{s["symbol"]:s["signal"] for s in portfolio_signals},
        "eps_forward_snapshot":{r["symbol"]:r.get("eps_forward") for r in sector_ranking if r.get("eps_forward") is not None},
        "entry_prices":{r["symbol"]:r.get("last") for r in sector_ranking if r.get("last") is not None},
        "ret_top1_3m":None,"ret_top2_3m":None,"ret_iwda_3m":None,"alpha_3m":None,"validated":False}
    history["signals"].append(entry)
    os.makedirs(os.path.dirname(HISTORY),exist_ok=True)
    with open(HISTORY,"w",encoding="utf-8") as f: json.dump(history,f,ensure_ascii=False,indent=2)
    print(f"  ✓ Señal {mk} guardada ({len(history['signals'])} señales totales)")

def get_prev_eps_snapshot(symbol):
    history=load_history(); signals=history.get("signals",[])
    for entry in reversed(signals[:-1] if signals else []):
        eps=entry.get("eps_forward_snapshot",{})
        if symbol in eps: return {"eps_forward":eps[symbol]}
    return None

def build_reasons(etf_data,macro_det,overval,fpatterns,breadth_desc,regime,er_adj,er_desc):
    ups,dns=[],[]
    td=etf_data.get("tech_details",{})
    for key in ["rel_strength","mom6m"]:
        f=td.get(key,{})
        if f.get("value") is not None:
            pct=f.get("percentile",50)
            if pct>70: ups.append(f"{f.get('interpretation',key)} — pct {pct:.0f}")
            elif pct<30: dns.append(f"{f.get('interpretation',key)} — pct {pct:.0f}")
    em=td.get("ema200",{})
    if em.get("value") is not None:
        pct=em.get("percentile",50); val=em["value"]
        if pct>70 and val>0: ups.append(f"{em['interpretation']} — pct {pct:.0f}")
        elif val>0: ups.append(f"{em['interpretation']}")
        elif pct<30: dns.append(f"{em['interpretation']} — pct {pct:.0f}")
    en=td.get("entry",{})
    if en.get("dist_from_max_5y") is not None:
        pct=en.get("percentile",50)
        if pct>65: ups.append(f"{en['interpretation']}")
        elif pct<35: dns.append(f"{en['interpretation']}")
    if td.get("penalty",{}).get("applied"): dns.append(td["penalty"].get("reason",""))
    if overval:
        for sig in overval.get("signals",[])[:2]: dns.append(f"Valoración: {sig}")
        if overval.get("bonus"): ups.append(f"Valoración: {overval.get('level','')} — justificado")
        elif overval.get("penalty",1)<1: dns.append(f"Valoración: {overval.get('level','')}")
    for p in fpatterns[:2]: dns.append(f"⚠️ {p}")
    if "negativo" in breadth_desc.lower(): dns.append(f"Breadth: {breadth_desc}")
    elif any(x in breadth_desc.lower() for x in ["positivo","excelente"]): ups.append(f"Breadth: {breadth_desc}")
    if er_adj>0: ups.append(f"Earnings: {er_desc}")
    elif er_adj<0: dns.append(f"Earnings: {er_desc}")
    if regime=="opportunity": ups.append("Régimen: pánico — oportunidad histórica")
    for md in macro_det.values():
        if isinstance(md,dict) and md.get("desc"):
            if md.get("score",50)>70: ups.append(f"Macro: {md['desc']}")
            elif md.get("score",50)<30: dns.append(f"Macro: {md['desc']}")
    return ups[:4],dns[:4]

def best_etf_per_sector(records):
    sectors={}
    for r in records:
        s=r["sector"]
        if s not in sectors or r["score_final"]>sectors[s]["score_final"]: sectors[s]=r
    return list(sectors.values())

def build_recommendation(sector_ranking,month_str,portfolio_signals,regime_info,correlations):
    if not sector_ranking: return {"mes":month_str,"accion_principal":"Sin datos","distribucion":[],"nota":""}
    top1=dict(sector_ranking[0]); score1=top1["score_final"]
    if score1<SCORE_FALLBACK:
        return {"mes":month_str,"calidad":"🔴 Sin oportunidades claras","score_top1":score1,
            "accion_principal":"Mercado sobrevalorado — aporta €500 a IWDA este mes",
            "distribucion":[{"rank":1,"name":"MSCI World IWDA","symbol":"IWDA.AS","sector":"Global",
                             "score":score1,"euros":500,"pct":100,"overval_level":"⚪"}],
            "fallback":True,"por_que":[f"Ningún sector > {SCORE_FALLBACK}. Máximo: {score1:.0f}"],
            "nota":"Cuando nada destaca, IWDA es la opción más eficiente.",
            "regimen":regime_info.get("regime"),"regimen_desc":regime_info.get("description","")}
    top2=None
    for candidate in sector_ranking[1:]:
        corr=get_correlation(correlations,top1["sector"],candidate["sector"])
        if abs(corr)<=MAX_CORRELATION: top2=candidate; break
    if top2 is None and len(sector_ranking)>1:
        top2=sector_ranking[1]; WARN.append(f"Top2 sin filtro correlacion")
    ya_tiene=any(s["symbol"]==top1["symbol"] for s in portfolio_signals)
    accion=(f"Añade más: {top1['name']} ({top1['symbol']}) — sigue siendo el #1"
            if ya_tiene else f"Aporta este mes en: {top1['name']} ({top1['symbol']})")
    if score1>=70: d1,d2,cal=350,150,"🟢 Señal fuerte"
    elif score1>=SCORE_WEAK: d1,d2,cal=300,200,"🟡 Señal moderada"
    else: d1,d2,cal=250,250,"🟠 Señal débil — diversifica más"
    t2s=top2["score_final"] if top2 else 0
    ct2=get_correlation(correlations,top1["sector"],top2["sector"]) if top2 else 0
    dist=[{"rank":1,"name":top1["name"],"symbol":top1["symbol"],"sector":top1["sector"],
           "score":score1,"euros":d1,"pct":round(d1/500*100),"overval_level":top1.get("overval_level","⚪")}]
    if top2:
        dist.append({"rank":2,"name":top2["name"],"symbol":top2["symbol"],"sector":top2["sector"],
                     "score":t2s,"euros":d2,"pct":round(d2/500*100),
                     "overval_level":top2.get("overval_level","⚪"),"correlacion_con_top1":ct2})
    return {"mes":month_str,"calidad":cal,"score_top1":score1,"accion_principal":accion,
            "distribucion":dist,"por_que":top1.get("reasons_up",[])[:2],"fallback":False,
            "regimen":regime_info.get("regime"),"regimen_desc":regime_info.get("description",""),
            "yield_curve":regime_info.get("yield_curve_spread"),
            "nota":f"Régimen: {regime_info.get('description','')}. Top2 correlación {ct2:.2f} vs Top1."}

def main():
    with open(UNI,encoding="utf-8") as f: uni_data=json.load(f)
    universe_all=uni_data["etfs"]
    up=[e for e in universe_all if e.get("universe","primary")=="primary"]
    us=[e for e in universe_all if e.get("universe","primary")=="secondary"]
    print(f"Universo principal: {len(up)} ETFs | Secundario: {len(us)} ETFs")
    macro={}
    if os.path.exists(MACRO):
        with open(MACRO,encoding="utf-8") as f: macro=json.load(f)
    ri=detect_market_regime(macro)
    print(f"\nRégimen: {ri['regime'].upper()} — {ri['description']}")
    print(f"  VIX: {ri['vix']} | IWDA 6M: {ri['iwda_6m']}%")
    if ri["yield_curve_spread"] is not None:
        print(f"  Curva tipos (10Y-2Y): {ri['yield_curve_spread']:+.2f}% {'⚠️ INVERTIDA' if ri['yield_curve_inverted'] else 'normal'}")
    wtr=ri["w_tech"]
    print("Descargando IWDA (5 anos)..."); iwda_prices,_=fetch_history("IWDA.AS","5y")
    print(f"\nAnalizando universo principal (v11)...")
    records=[]; etf_cache={}; spm={}
    for etf in up:
        p,d=fetch_history(etf["symbol"],"5y"); etf_cache[etf["id"]]=(p,d)
        if p: spm[etf["sector"]]=p
    print("Calculando correlaciones..."); correlations=compute_correlation_matrix(spm)
    print(f"  {len(correlations)//2} pares evaluados")
    for etf in up:
        sym=etf["symbol"]; aum=etf.get("aum_bn",1.0); mp=etf.get("macro_profile","")
        print(f"  {sym}...",end=" ",flush=True)
        prices,dates=etf_cache.get(etf["id"],(None,None))
        if not prices or len(prices)<60: print("sin datos"); continue
        if len(prices)<MIN_HISTORY_DAYS: print(f"insuficiente ({len(prices)}d)"); continue
        fp,fpatterns,mwa=detect_failure_patterns(prices,mp,ri["regime"])
        srp=ri["sector_penalties"].get(mp,1.0)
        st,tdet=compute_technical_score(prices,iwda_prices,wtr,mwa)
        if st is None: print("insuficiente"); continue
        sm,mdet=compute_macro_score(mp,macro)
        fund=fetch_fundamentals(sym); ov=compute_overvaluation(prices,fund)
        prev_eps=get_prev_eps_snapshot(sym); er_adj,er_desc=compute_earnings_revision(fund,prev_eps)
        bs=0; bd="Sin datos de breadth"; bp=None
        se=[(e["id"],e.get("aum_bn",1.0),etf_cache.get(e["id"],(None,None))[0])
            for e in up if e["sector"]==etf["sector"]]
        se=[(eid,a,p) for eid,a,p in se if p]
        if len(se)>=2:
            se.sort(key=lambda x:x[1],reverse=True); bs,bd=compute_breadth_from_pair(se[1][2],se[0][2])
        elif etf["id"] in ETF_HOLDINGS:
            print("(holdings)...",end=" ",flush=True); bs,bd,bp=compute_breadth_from_holdings(etf["id"])
        aum_p=1.0
        if aum<MIN_AUM_BN: aum_p=0.95; WARN.append(f"{sym}: AUM bajo")
        sf=round(compute_final_score(st,sm,ov["penalty"],fp,srp,bs,er_adj)*aum_p,1)
        extra=tdet.get("extra",{})
        rec={"id":etf["id"],"name":etf["name"],"symbol":sym,"sector":etf["sector"],
            "conviction":etf.get("conviction",4),"macro_profile":mp,"aum_bn":aum,"universe":"primary",
            "last":round(prices[-1],4),"score_tech":st,"score_macro":sm,"score_final":sf,
            "pct_rel_strength":tdet.get("rel_strength",{}).get("percentile"),
            "pct_ema200":tdet.get("ema200",{}).get("percentile"),
            "pct_mom6m":tdet.get("mom6m",{}).get("percentile"),
            "pct_entry":tdet.get("entry",{}).get("percentile"),
            "pct_consistency":tdet.get("consistency",{}).get("percentile"),
            "rel_strength":tdet.get("rel_strength",{}).get("value"),
            "dist_ema200":tdet.get("ema200",{}).get("value"),
            "ema200_abs":tdet.get("ema200",{}).get("ema200_abs"),
            "dist_from_max":tdet.get("entry",{}).get("dist_from_max_52w"),
            "dist_from_max_5y":tdet.get("entry",{}).get("dist_from_max_5y"),
            "consistency_pct":tdet.get("consistency",{}).get("value"),
            "mom_penalty":not tdet.get("penalty",{}).get("applied",False),
            "r1m":extra.get("r1m"),"r3m":extra.get("r3m"),"r6m":extra.get("r6m"),"r12m":extra.get("r12m"),
            "vol":extra.get("vol"),"drawdown":extra.get("drawdown"),"ann_ret":extra.get("ann_ret"),
            "pe":fund.get("pe"),"pe_forward":fund.get("pe_forward"),"beta":fund.get("beta"),
            "dy":fund.get("dy"),"growth_est":fund.get("growth_est"),
            "eps_forward":fund.get("eps_forward"),"eps_trailing":fund.get("eps_trailing"),
            "overval_score":ov["overval_score"],"overval_level":ov["level"],
            "overval_penalty":ov["penalty"],"overval_signals":ov["signals"],
            "per_expansion":ov.get("per_expansion"),"peg":ov.get("peg"),
            "dist_from_max_5y_overval":ov.get("dist_alltime"),
            "breadth_score":bs,"breadth_desc":bd,"breadth_pct":bp,
            "failure_patterns":fpatterns,"failure_penalty":fp,"regime_penalty":srp,"mom_weight_adj":mwa,
            "earnings_revision_adj":er_adj,"earnings_revision_desc":er_desc,
            "sparkline":[round(p,4) for p in prices[-60:]],"spark_dates":dates[-60:] if dates else [],
            "tech_details":tdet,"macro_details":mdet}
        ups,dns=build_reasons(rec,mdet,ov,fpatterns,bd,ri["regime"],er_adj,er_desc)
        rec["reasons_up"]=ups; rec["reasons_down"]=dns
        del rec["tech_details"]; del rec["macro_details"]
        records.append(rec)
        flags=[]
        if ov["penalty"]!=1.0: flags.append(ov["level"])
        if fpatterns: flags.append(f"⚠️{len(fpatterns)}p")
        if bs!=0: flags.append(f"b{bs:+d}")
        if srp!=1.0: flags.append(f"r×{srp}")
        if er_adj!=0: flags.append(f"er{er_adj:+d}")
        print(f"tech={st:.0f} macro={sm:.0f} final={sf:.0f} {' '.join(flags)}")
    if not records: print("ERROR: sin datos"); return
    records.sort(key=lambda x:x["score_final"],reverse=True)
    sr=best_etf_per_sector(records); sr.sort(key=lambda x:x["score_final"],reverse=True)
    print("\nAnalizando cartera actual...")
    ps=build_portfolio_signals(CARTERA)
    for s in ps:
        icon="✅" if s["signal"]=="green" else ("⚠️" if s["signal"]=="yellow" else "🔴")
        print(f"  {icon} {s['symbol']} ({'semanal' if s.get('ema_type')=='weekly' else 'diaria'}): {s['signal_text']}")
    ms=datetime.date.today().strftime("%B %Y")
    rec=build_recommendation(sr,ms,ps,ri,correlations)
    print("\nActualizando diario..."); save_to_history(rec,sr,ri,ps)
    mc={"tipos":macro.get("interest_rates",{}).get("interpretation","Sin datos"),
        "vix":macro.get("vix",{}).get("interpretation","Sin datos"),
        "dolar":macro.get("dxy",{}).get("interpretation","Sin datos"),
        "halving":macro.get("bitcoin_halving",{}).get("description","Sin datos"),
        "fred":macro.get("fred_available",False),"updated":macro.get("updated",""),"regime":ri}
    out={"updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z",
        "total_analyzed":len(records),"model_version":"11.0",
        "factor_weights":{"tech":W_FINAL["tech"],"macro":W_FINAL["macro"],
                          "tech_factors_base":W_TECH_BASE,"tech_factors_regime":wtr},
        "market_regime":ri,"recommendation":rec,"portfolio_signals":ps,
        "sector_ranking":sr,"all":records,"macro_context":mc,"warnings":WARN}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as fh: json.dump(out,fh,ensure_ascii=False,indent=2)
    print(f"\n{'='*65}")
    print(f"RÉGIMEN: {ri['regime'].upper()} — {ri['description']}")
    if ri.get("yield_curve_spread") is not None:
        print(f"  Curva tipos: {ri['yield_curve_spread']:+.2f}% {'⚠️ INVERTIDA' if ri['yield_curve_inverted'] else ''}")
    print(f"RECOMENDACIÓN {ms} — {rec.get('calidad','')}")
    print(f"  {rec['accion_principal']}")
    if rec.get("fallback"): print(f"  ⚠️ FALLBACK A IWDA")
    for d in rec.get("distribucion",[]):
        cs=f" corr={d.get('correlacion_con_top1',0):.2f}" if d.get("rank")==2 else ""
        print(f"  #{d['rank']} {d['symbol']:10s} score={d['score']:5.1f} → €{d['euros']} ({d['pct']}%) {d.get('overval_level','')}{cs}")
    print(f"\nRANKING SECTORES (v11 — 13 sectores):")
    for i,r in enumerate(sr[:6]):
        fp=f" ⚠️{len(r.get('failure_patterns',[]))}p" if r.get("failure_patterns") else ""
        br=f" b{r.get('breadth_score',0):+d}" if r.get("breadth_score",0)!=0 else ""
        er=f" er{r.get('earnings_revision_adj',0):+d}" if r.get("earnings_revision_adj",0)!=0 else ""
        print(f"  #{i+1} {r['sector']:22s} {r['symbol']:10s} score={r['score_final']:5.1f} {r.get('overval_level','')}{fp}{br}{er}")
    print(f"{'='*65}")
    print(f"v11: 13 sectores | correlacion | earnings | curva tipos | diario. Avisos: {len(WARN)}")

if __name__ == "__main__":
    main()
