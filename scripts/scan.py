#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor del escaner de oportunidades - version 10.

Mejoras vs v9:
  MEJORA 1 - Breadth interno del ETF
  MEJORA 2 - Deteccion de patrones de fallo
  MEJORA 3 - Regimen de mercado con pesos dinamicos
"""

import json, math, os, urllib.request, datetime, time

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI   = os.path.join(ROOT, "universe.json")
MACRO = os.path.join(ROOT, "data", "macro.json")
OUT   = os.path.join(ROOT, "data", "output.json")
UA    = {"User-Agent": "Mozilla/5.0 (compatible; QuantScanner/10.0)"}
WARN  = []

CARTERA = [
    {"id":"SEMI","symbol":"SEMI.AS","name":"iShares MSCI Global Semiconductors","sector":"Semiconductores"},
    {"id":"BTC", "symbol":"BTC-EUR", "name":"Bitcoin",                           "sector":"Bitcoin y Cripto"},
]

W_TECH_BASE = {
    "rel_strength": 0.25,
    "ema200":       0.25,
    "mom6m":        0.20,
    "entry":        0.20,
    "consistency":  0.10,
}

W_FINAL = {"tech": 0.85, "macro": 0.15}
MIN_HISTORY_DAYS = 756
MIN_AUM_BN       = 0.5

ETF_HOLDINGS = {
    "WTAI":  ["NVDA","MSFT","GOOGL","META","AMZN","TSM","AVGO","ORCL","PLTR","CRM",
               "SNOW","AMAT","KLAC","ASML","AMD","INTC","QCOM","TXN","NOW","ADSK"],
    "ROBO":  ["ISRG","ABB","FANUC","KEYB","IRBT","BRKS","MKSI","NOVT","NDSN","TRMB",
               "ROP","AZTA","ONTO","LRCX","GTLS","ITRI","XYL","FLOW","REXR","BRKR"],
    "ITA":   ["RTX","LMT","NOC","GD","BA","L3H","HII","TDG","HEI","TXT",
               "LDOS","SAIC","CACI","BAH","DRS","MOOG","AXON","KTOS","AVAV","SPR"],
    "INDA":  ["INFY","WIPRO","HDB","IBN","WIT","AXBK","HDFCB","RELIANCE","BHARTIARTL","TCS",
               "HINDUNILVR","ICICIBC","SBIN","LT","KOTAKBANK","BAJFINANCE","ASIANPAINT","ULTRACEMCO","TITAN","NESTLEIND"],
    "FLIN":  ["INFY","HDB","IBN","RELIANCE","HDFCB","WIT","TCS","BHARTIARTL","ICICIBC","SBIN",
               "KOTAKBANK","BAJFINANCE","LT","ASIANPAINT","ULTRACEMCO","TITAN","NESTLEIND","POWERGRID","NTPC","COALINDIA"],
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
        pe_trailing=(sd.get("trailingPE") or {}).get("raw")
        pe_forward=(sd.get("forwardPE") or {}).get("raw") or (ks.get("forwardPE") or {}).get("raw")
        beta=(ks.get("beta") or {}).get("raw") or (sd.get("beta") or {}).get("raw")
        dy=(sd.get("dividendYield") or {}).get("raw")
        growth_est=(fd.get("earningsGrowth") or {}).get("raw") or (fd.get("revenueGrowth") or {}).get("raw")
        return {"pe":round(pe_trailing,1) if pe_trailing else None,
                "pe_forward":round(pe_forward,1) if pe_forward else None,
                "beta":round(beta,2) if beta else None,
                "dy":round(dy*100,2) if dy else None,
                "growth_est":round(growth_est*100,1) if growth_est else None}
    except: return {"pe":None,"pe_forward":None,"beta":None,"dy":None,"growth_est":None}

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

def drawdown_from_alltime_max(prices):
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

# ── MEJORA 3: REGIMEN DE MERCADO ──────────────────────────────────────

def detect_market_regime(macro):
    vix_val=macro.get("vix",{}).get("value")
    vix_trend=macro.get("vix",{}).get("trend","neutral")
    iwda_ret6=macro.get("iwda",{}).get("ret_6m")

    if vix_val and vix_val>35 and vix_trend=="down":
        regime="opportunity"
    elif vix_val and vix_val>25:
        regime="bear"
    elif iwda_ret6 and iwda_ret6>10 and vix_val and vix_val<20:
        regime="bull"
    else:
        regime="neutral"

    if regime=="bull":
        w_tech={"rel_strength":0.30,"ema200":0.25,"mom6m":0.25,"entry":0.10,"consistency":0.10}
    elif regime=="bear":
        w_tech={"rel_strength":0.20,"ema200":0.20,"mom6m":0.15,"entry":0.35,"consistency":0.10}
    elif regime=="opportunity":
        w_tech={"rel_strength":0.15,"ema200":0.15,"mom6m":0.10,"entry":0.50,"consistency":0.10}
    else:
        w_tech=W_TECH_BASE.copy()

    if regime=="bull":
        sector_penalties={"defensive_demographics":0.90,"defensive_government":0.95,"rates_debt_sensitive":0.90}
    elif regime=="bear":
        sector_penalties={"growth_rates_sensitive":0.85,"crypto_halving":0.80}
    else:
        sector_penalties={}

    descriptions={"bull":"Mercado alcista fuerte — priorizando momentum y liderazgo",
                  "bear":"Mercado bajista — priorizando punto de entrada sobre momentum",
                  "opportunity":"Pánico extremo (VIX>35 bajando) — máxima prioridad a precio de entrada",
                  "neutral":"Mercado neutral — pesos estándar del modelo"}
    return {"regime":regime,"w_tech":w_tech,"sector_penalties":sector_penalties,
            "description":descriptions[regime],"vix":vix_val,"iwda_6m":iwda_ret6}

# ── MEJORA 1: BREADTH INTERNO ─────────────────────────────────────────

def compute_breadth_from_pair(prices_ew, prices_cw):
    if not prices_ew or not prices_cw: return 0,"Sin datos de breadth"
    ret_ew=ret_n(prices_ew,min(63,len(prices_ew)-1))
    ret_cw=ret_n(prices_cw,min(63,len(prices_cw)-1))
    if ret_ew is None or ret_cw is None: return 0,"Sin datos de breadth"
    diff=ret_ew-ret_cw
    if diff>5:   return  8,f"Breadth positivo — empresas pequeñas lideran (+{diff:.1f}% ew vs cw)"
    elif diff>2: return  4,f"Breadth moderadamente positivo (+{diff:.1f}% ew vs cw)"
    elif diff>-2:return  0,f"Breadth neutro ({diff:.1f}% ew vs cw)"
    elif diff>-5:return -4,f"Breadth negativo — solo grandes suben ({diff:.1f}% ew vs cw)"
    else:        return -8,f"Breadth muy negativo — tendencia concentrada ({diff:.1f}% ew vs cw)"

def compute_breadth_from_holdings(etf_id):
    holdings=ETF_HOLDINGS.get(etf_id,[])
    if not holdings: return 0,"Sin datos de holdings",None
    above_ema50=0; total_checked=0
    for ticker in holdings:
        try:
            prices=fetch_close_price(ticker)
            if not prices or len(prices)<55: continue
            e50=ema_n(prices,50)
            if e50 and prices[-1]>e50: above_ema50+=1
            total_checked+=1
            time.sleep(0.1)
        except: continue
    if total_checked<5: return 0,"Datos insuficientes de holdings",None
    pct=round(above_ema50/total_checked*100,0)
    if pct>=75:   return  8,f"Breadth excelente — {pct:.0f}% de holdings sobre EMA50",pct
    elif pct>=60: return  4,f"Breadth positivo — {pct:.0f}% de holdings sobre EMA50",pct
    elif pct>=40: return  0,f"Breadth neutro — {pct:.0f}% de holdings sobre EMA50",pct
    elif pct>=25: return -4,f"Breadth negativo — solo {pct:.0f}% de holdings sobre EMA50",pct
    else:         return -8,f"Breadth muy negativo — solo {pct:.0f}% de holdings sobre EMA50",pct

# ── MEJORA 2: PATRONES DE FALLO ───────────────────────────────────────

def detect_failure_patterns(prices, macro_profile, regime):
    patterns=[]; penalty=1.0; mom_weight_adj=0.0
    dist_5y=drawdown_from_alltime_max(prices)
    mom6m=ret_n(prices,min(126,len(prices)-1))
    mom3m=ret_n(prices,min(63,len(prices)-1))

    # Patron A: defensivo en bull
    if macro_profile in {"defensive_demographics","defensive_government","rates_debt_sensitive"} and regime=="bull":
        penalty*=0.88
        patterns.append("Patrón A: sector defensivo en mercado alcista — históricamente queda rezagado")

    # Patron B: falsa recuperacion desde minimos extremos
    if dist_5y is not None and dist_5y<-30 and mom6m is not None and mom6m>25:
        mom_weight_adj=-0.08
        patterns.append(f"Patrón B: recuperación desde mínimos extremos ({dist_5y:.0f}% bajo máx 5A) con momentum alto (+{mom6m:.1f}%) — posible rebote")

    # Patron C: euforia de corto plazo
    if mom3m is not None and mom3m>50:
        penalty*=0.90
        patterns.append(f"Momentum 3M extremo (+{mom3m:.1f}%) — posible euforia de corto plazo")

    return penalty, patterns, mom_weight_adj

# ── SOBREVALORACIÓN ───────────────────────────────────────────────────

def compute_overvaluation(prices, fund):
    signals=[]; signal_count=0; bonus=False
    pe_now=fund.get("pe"); growth_est=fund.get("growth_est")
    per_expansion=None
    if pe_now and len(prices)>=252:
        p12=prices[-253] if len(prices)>252 else prices[0]
        if p12>0 and prices[-1]>0:
            pr=prices[-1]/p12; per_expansion=pe_now/(pe_now/pr)
            if per_expansion>1.5:
                signals.append(f"PER se expandió x{per_expansion:.1f} — beneficios no acompañan"); signal_count+=1
            elif per_expansion>1.3:
                signals.append(f"Expansión de múltiplos moderada (x{per_expansion:.1f})"); signal_count+=0.5
            elif per_expansion<0.8: bonus=True
    peg=None
    if pe_now and growth_est and growth_est>0:
        peg=round(pe_now/growth_est,2)
        if peg>3: signals.append(f"PEG muy alto ({peg:.1f}) — precio caro vs crecimiento"); signal_count+=1
        elif peg>2: signals.append(f"PEG elevado ({peg:.1f}) — cautela"); signal_count+=0.5
        elif peg<1: bonus=True
    dist_at=drawdown_from_alltime_max(prices)
    if dist_at is not None:
        if dist_at>-2: signals.append(f"En maximos historicos absolutos ({dist_at:.1f}%)"); signal_count+=1
        elif dist_at>-5: signals.append(f"Muy cerca de maximos historicos ({dist_at:.1f}%)"); signal_count+=0.5
    mom3m=ret_n(prices,63); mom3m_hist=[]
    n=len(prices)
    for i in range(1,min(504,n-63)):
        r=ret_n(prices[:n-i],63)
        if r is not None: mom3m_hist.append(r)
    if mom3m is not None and mom3m_hist:
        avg=sum(mom3m_hist)/len(mom3m_hist)
        if avg>0 and mom3m>avg*3: signals.append(f"Momentum 3M ({mom3m:.1f}%) es {mom3m/avg:.1f}x la media"); signal_count+=1
        elif avg>0 and mom3m>avg*2: signals.append(f"Momentum 3M acelerado ({mom3m:.1f}% vs media {avg:.1f}%)"); signal_count+=0.5
    if signal_count>=2.5: penalty=0.5; level="🔴 Burbuja probable"
    elif signal_count>=1.5: penalty=0.7; level="🟠 Sobrevaloración significativa"
    elif signal_count>=0.5: penalty=0.85; level="🟡 Ligera sobrevaloración"
    elif bonus: penalty=1.10; level="🟢 Precio justificado — beneficios acompañan"
    else: penalty=1.0; level="⚪ Valoración neutral"
    return {"overval_score":round(min(100,signal_count/3*100),0),"signals":signals,
            "penalty":penalty,"level":level,"per_expansion":round(per_expansion,2) if per_expansion else None,
            "peg":peg,"dist_alltime":dist_at,"bonus":bonus}

# ── SCORE TECNICO v10 ─────────────────────────────────────────────────

def compute_technical_score(prices, iwda_prices, w_tech, mom_weight_adj=0.0):
    if not prices or len(prices)<60: return None,{}
    n=len(prices); vol=vol_std(prices,min(252,n-1)); details={}
    w=dict(w_tech)
    if mom_weight_adj!=0.0:
        w["mom6m"]=max(0.05,w["mom6m"]+mom_weight_adj)
        w["entry"]=min(0.50,w["entry"]-mom_weight_adj)
    total=sum(w.values()); w={k:v/total for k,v in w.items()}

    rs_now=None; rs_hist=[]
    if iwda_prices and len(iwda_prices)>=126:
        r_e=ret_n(prices,min(126,n-1)); r_i=ret_n(iwda_prices,min(126,len(iwda_prices)-1))
        if r_e is not None and r_i is not None: rs_now=(r_e-r_i)/(vol/20.0)
        for i in range(126,min(n,756)):
            p_e=prices[:n-i+126] if n-i+126>126 else prices[:126]
            p_i=iwda_prices[:len(iwda_prices)-i+126] if len(iwda_prices)-i+126>126 else iwda_prices[:126]
            re=ret_n(p_e,126); ri=ret_n(p_i,126)
            if re is not None and ri is not None:
                rs_hist.append((re-ri)/(vol_std(p_e,min(252,len(p_e)-1))/20.0))
    pct_rel=percentile_in_own_history(rs_now,rs_hist)
    details["rel_strength"]={"value":round(rs_now,2) if rs_now else None,"percentile":pct_rel,
        "interpretation":("Lidera al mercado global" if rs_now and rs_now>1
            else "Va por detrás del mercado" if rs_now and rs_now<-1 else "En línea con el mercado")}

    e200=ema_n(prices,min(200,n)); dist_ema=((prices[-1]/e200-1)*100) if e200 else None
    ema_norm=(dist_ema/(vol/20.0)) if dist_ema else None
    ema_hist=[]
    for i in range(1,min(504,n-200)):
        pc=prices[:n-i]; e=ema_n(pc,min(200,len(pc)))
        if e: ema_hist.append(((pc[-1]/e-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pct_ema=percentile_in_own_history(ema_norm,ema_hist)
    details["ema200"]={"value":round(dist_ema,2) if dist_ema else None,"ema200_abs":round(e200,4) if e200 else None,
        "percentile":pct_ema,"above":dist_ema>0 if dist_ema is not None else None,
        "interpretation":(f"Muy por encima de EMA200 (+{dist_ema:.1f}%)" if dist_ema and dist_ema>15
            else f"Por encima de EMA200 (+{dist_ema:.1f}%)" if dist_ema and dist_ema>0
            else f"Por debajo de EMA200 ({dist_ema:.1f}%)" if dist_ema else "Sin datos EMA200")}

    mom6m=ret_n(prices,min(126,n-1)); mom6m_norm=(mom6m/(vol/20.0)) if mom6m is not None else None
    mom6m_hist=[]
    for i in range(1,min(756,n-126)):
        pc=prices[:n-i]; r=ret_n(pc,min(126,len(pc)-1))
        if r is not None: mom6m_hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pct_mom6=percentile_in_own_history(mom6m_norm,mom6m_hist)
    details["mom6m"]={"value":round(mom6m,2) if mom6m else None,"percentile":pct_mom6,
        "interpretation":(f"Momentum 6M excepcional (+{mom6m:.1f}%)" if mom6m and mom6m>30
            else f"Momentum 6M fuerte (+{mom6m:.1f}%)" if mom6m and mom6m>10
            else f"Momentum 6M positivo (+{mom6m:.1f}%)" if mom6m and mom6m>0
            else f"Momentum 6M negativo ({mom6m:.1f}%)" if mom6m else "Sin datos")}

    d52=drawdown_from_max(prices,252); d5y=drawdown_from_alltime_max(prices)
    entry_c=d52*0.60+d5y*0.40 if d52 is not None and d5y is not None else d52
    dd_hist=[]
    for i in range(1,min(756,n-252)):
        pc=prices[:n-i]; d=drawdown_from_max(pc,min(252,len(pc)))
        if d is not None: dd_hist.append(-d)
    pct_entry=percentile_in_own_history(-entry_c if entry_c is not None else None,dd_hist)
    details["entry"]={"dist_from_max_52w":d52,"dist_from_max_5y":d5y,"percentile":pct_entry,
        "interpretation":(f"Excelente entrada: {d5y:.0f}% bajo maximos historicos" if d5y and d5y<-25
            else f"Buena entrada: {d52:.0f}% bajo maximos 52s" if d52 and d52<-10
            else f"En maximos historicos — entrada muy exigente" if d5y and d5y>-3
            else f"Cerca de maximos ({d52:.0f}%)" if d52 else "Sin datos")}

    co=consistency_6m(prices); co_hist=[]
    for i in range(1,min(756,n-130)):
        pc=prices[:n-i]; c=consistency_6m(pc)
        if c is not None: co_hist.append(c)
    pct_co=percentile_in_own_history(co,co_hist)
    details["consistency"]={"value":co,"percentile":pct_co,
        "interpretation":(f"Muy consistente ({co:.0f}% meses positivos)" if co and co>=80
            else f"Consistente ({co:.0f}% meses positivos)" if co and co>=60
            else f"Inconsistente ({co:.0f}% meses positivos)" if co else "Sin datos")}

    score=(w["rel_strength"]*pct_rel+w["ema200"]*pct_ema+w["mom6m"]*pct_mom6+
           w["entry"]*pct_entry+w["consistency"]*pct_co)
    mom3m=ret_n(prices,min(63,n-1)); pen=1.0
    if mom3m is not None and mom3m<-10:
        pen=0.6; details["penalty"]={"applied":True,"reason":f"Caída fuerte 3M ({mom3m:.1f}%) — score ×0.6","mom3m":round(mom3m,2)}
    else: details["penalty"]={"applied":False,"mom3m":round(mom3m,2) if mom3m else None}
    details["extra"]={"r1m":round(ret_n(prices,21),2) if ret_n(prices,21) else None,
        "r3m":round(mom3m,2) if mom3m else None,"r6m":round(mom6m,2) if mom6m else None,
        "r12m":round(ret_n(prices,252),2) if ret_n(prices,252) else None,
        "vol":round(vol_annual(prices),1) if vol_annual(prices) else None,
        "drawdown":d52,"ann_ret":ann_ret(prices),"dist_max_5y":d5y}
    details["w_used"]=w
    return round(score*pen,1), details

def compute_macro_score(macro_profile, macro):
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
        s=65; det={"base":{"weight":"100%","score":65,"desc":"Envejecimiento poblacional inevitable"}}
    elif macro_profile=="crypto_halving":
        s=rs*0.30+di*0.30+hs*0.40
        det={"tipos":{"weight":"30%","score":rs,"desc":rates.get("interpretation","")},
             "dolar":{"weight":"30%","score":di,"desc":dxy.get("interpretation","")},
             "halving":{"weight":"40%","score":hs,"desc":halving.get("description","")}}
    elif macro_profile=="uranium_spot":
        s=us*0.70+rs*0.30
        det={"uranio_spot":{"weight":"70%","score":us,"desc":ux.get("interpretation","")},
             "tipos":{"weight":"30%","score":rs,"desc":rates.get("interpretation","")}}
    else: s=50
    return round(min(100,max(0,s)),1), det

def compute_final_score(score_tech,score_macro,overval_penalty,failure_penalty,sector_regime_penalty,breadth_score):
    base=score_tech*W_FINAL["tech"]+score_macro*W_FINAL["macro"]
    adjusted=base*overval_penalty*failure_penalty*sector_regime_penalty
    breadth_adj=breadth_score*0.6
    return round(max(0,min(100,adjusted+breadth_adj)),1)

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

def ema200_signal_weekly(prices_w):
    n=len(prices_w); ep=min(200,n-1) if n>50 else None
    if ep is None: return "neutral"
    e200=ema_n(prices_w,ep)
    if e200 is None: return "neutral"
    dd=drawdown_from_max(prices_w); wb=0
    for i in range(13):
        if i+1>len(prices_w): break
        wp=prices_w[:len(prices_w)-(i+1)]
        if len(wp)<ep: break
        e=ema_n(wp,ep)
        if e and wp[-1]<e: wb+=1
        else: break
    if prices_w[-1]>e200: return "green"
    elif wb>=13 and dd is not None and dd<-15: return "red"
    else: return "yellow"

def build_portfolio_signals(cartera):
    signals=[]
    for asset in cartera:
        ic=asset["sector"]=="Bitcoin y Cripto"
        if ic:
            pw,dw=fetch_history_weekly(asset["symbol"],"5y")
            pd,dd=fetch_history(asset["symbol"],"5y")
            if not pw or len(pw)<50:
                signals.append({**asset,"signal":"neutral","signal_text":"Sin datos","dist_ema200":None,"r3m":None,"r12m":None,"drawdown":None,"sparkline":[],"spark_dates":[]})
                continue
            sig=ema200_signal_weekly(pw); e200=ema_n(pw,min(200,len(pw)-1))
            de=round((pw[-1]/e200-1)*100,1) if e200 else None
            pm=pd or pw; ds=dd or dw
        else:
            pd,dd=fetch_history(asset["symbol"],"5y")
            if not pd or len(pd)<60:
                signals.append({**asset,"signal":"neutral","signal_text":"Sin datos","dist_ema200":None,"r3m":None,"r12m":None,"drawdown":None,"sparkline":[],"spark_dates":[]})
                continue
            sig=ema200_signal_daily(pd); e200=ema_n(pd,200)
            de=round((pd[-1]/e200-1)*100,1) if e200 else None
            pm=pd; ds=dd
        r3m=ret_n(pm,63); r12m=ret_n(pm,252); drw=drawdown_from_max(pm)
        txt=("Tesis intacta — EMA200 alcista. Sigue aportando." if sig=="green"
             else f"Atención — por debajo de EMA200 {'semanal' if ic else 'diaria'}. Vigilar." if sig=="yellow"
             else f"Señal de salida — EMA200 {'semanal' if ic else 'diaria'} rota. Considera rotar.")
        signals.append({**asset,"signal":sig,"signal_text":txt,"dist_ema200":de,
            "ema_type":"weekly" if ic else "daily",
            "r3m":round(r3m,2) if r3m else None,"r12m":round(r12m,2) if r12m else None,"drawdown":drw,
            "sparkline":[round(p,4) for p in pm[-60:]],"spark_dates":ds[-60:] if ds else []})
    return signals

def build_reasons(etf_data,macro_details,overval,failure_patterns,breadth_desc,regime):
    ups,dns=[],[]
    td=etf_data.get("tech_details",{})
    for key,label,lo,hi in [("rel_strength","interpretation",30,70),("mom6m","interpretation",25,75),("consistency","value",30,70)]:
        f=td.get(key,{})
        if f.get("value") is not None or f.get("percentile") is not None:
            pct=f.get("percentile",50)
            if pct>hi: ups.append(f"{f.get('interpretation',key)} — percentil {pct:.0f}")
            elif pct<lo: dns.append(f"{f.get('interpretation',key)} — percentil {pct:.0f}")
    em=td.get("ema200",{})
    if em.get("value") is not None:
        pct=em.get("percentile",50); val=em["value"]
        if pct>70 and val>0: ups.append(f"{em['interpretation']} — pct {pct:.0f}")
        elif val>0: ups.append(f"{em['interpretation']}")
        elif pct<30: dns.append(f"{em['interpretation']} — momento débil")
    en=td.get("entry",{})
    if en.get("dist_from_max_5y") is not None:
        pct=en.get("percentile",50)
        if pct>65: ups.append(f"{en['interpretation']}")
        elif pct<35: dns.append(f"{en['interpretation']}")
    if td.get("penalty",{}).get("applied"): dns.append(td["penalty"].get("reason",""))
    if overval:
        for sig in overval.get("signals",[])[:2]: dns.append(f"Valoración: {sig}")
        if overval.get("bonus"): ups.append(f"Valoración: {overval.get('level','')} — precio justificado")
        elif overval.get("penalty",1)<1: dns.append(f"Valoración: {overval.get('level','')}")
    for p in failure_patterns[:2]: dns.append(f"⚠️ {p}")
    if "negativo" in breadth_desc.lower(): dns.append(f"Breadth: {breadth_desc}")
    elif any(x in breadth_desc.lower() for x in ["positivo","excelente"]): ups.append(f"Breadth: {breadth_desc}")
    if regime=="opportunity": ups.append("Régimen: pánico extremo — oportunidad histórica de entrada")
    for md in macro_details.values():
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

def build_recommendation(sector_ranking,month_str,portfolio_signals,regime_info):
    if not sector_ranking: return {"mes":month_str,"accion_principal":"Sin datos","distribucion":[],"nota":""}
    top1=dict(sector_ranking[0]); top2=sector_ranking[1] if len(sector_ranking)>1 else None
    ya_tiene=any(s["symbol"]==top1["symbol"] for s in portfolio_signals)
    accion=(f"Añade más a lo que ya tienes: {top1['name']} ({top1['symbol']}) — sigue siendo el #1"
            if ya_tiene else f"Aporta este mes en: {top1['name']} ({top1['symbol']})")
    score1=top1["score_final"]
    if score1>=70: d1,d2,cal=350,150,"🟢 Señal fuerte"
    elif score1>=55: d1,d2,cal=300,200,"🟡 Señal moderada"
    else: d1,d2,cal=250,250,"🟠 Señal débil — diversifica más"
    t2s=top2["score_final"] if top2 else 0
    dist=[{"rank":1,"name":top1["name"],"symbol":top1["symbol"],"sector":top1["sector"],
           "score":score1,"euros":d1,"pct":round(d1/500*100),"overval_level":top1.get("overval_level","⚪")}]
    if top2:
        dist.append({"rank":2,"name":top2["name"],"symbol":top2["symbol"],"sector":top2["sector"],
                     "score":t2s,"euros":d2,"pct":round(d2/500*100),"overval_level":top2.get("overval_level","⚪")})
    return {"mes":month_str,"calidad":cal,"score_top1":score1,"accion_principal":accion,
            "distribucion":dist,"por_que":top1.get("reasons_up",[])[:2],
            "regimen":regime_info.get("regime","neutral"),"regimen_desc":regime_info.get("description",""),
            "nota":f"Régimen: {regime_info.get('description','')}. 🔴/🟠 = riesgo burbuja."}

def main():
    with open(UNI,encoding="utf-8") as f: uni_data=json.load(f)
    universe_all=uni_data["etfs"]
    universe_primary=[e for e in universe_all if e.get("universe","primary")=="primary"]
    universe_secondary=[e for e in universe_all if e.get("universe","primary")=="secondary"]
    print(f"Universo principal: {len(universe_primary)} ETFs | Secundario: {len(universe_secondary)} ETFs")

    macro={}
    if os.path.exists(MACRO):
        with open(MACRO,encoding="utf-8") as f: macro=json.load(f)

    regime_info=detect_market_regime(macro)
    print(f"\nRégimen: {regime_info['regime'].upper()} — {regime_info['description']}")
    print(f"  VIX: {regime_info['vix']} | IWDA 6M: {regime_info['iwda_6m']}%")
    w_tech_r=regime_info["w_tech"]

    print("Descargando IWDA (5 anos)...")
    iwda_prices,_=fetch_history("IWDA.AS","5y")

    print(f"\nAnalizando universo principal (v10)...")
    records=[]; etf_cache={}; sector_cache={}

    # Pasada 1: descargar precios
    for etf in universe_primary:
        p,d=fetch_history(etf["symbol"],"5y")
        etf_cache[etf["id"]]=(p,d)
        sec=etf["sector"]
        if sec not in sector_cache: sector_cache[sec]=[]
        if p: sector_cache[sec].append((etf["id"],p))

    # Pasada 2: calcular scores
    for etf in universe_primary:
        sym=etf["symbol"]; aum=etf.get("aum_bn",1.0); mp=etf.get("macro_profile","")
        print(f"  {sym}...",end=" ",flush=True)
        prices,dates=etf_cache.get(etf["id"],(None,None))
        if not prices or len(prices)<60: print("sin datos"); continue
        if len(prices)<MIN_HISTORY_DAYS: print(f"historico insuficiente ({len(prices)}d)"); continue

        fp,fpatterns,mwa=detect_failure_patterns(prices,mp,regime_info["regime"])
        srp=regime_info["sector_penalties"].get(mp,1.0)
        score_tech,tech_det=compute_technical_score(prices,iwda_prices,w_tech_r,mwa)
        if score_tech is None: print("insuficiente"); continue
        score_macro,macro_det=compute_macro_score(mp,macro)
        fund=fetch_fundamentals(sym); overval=compute_overvaluation(prices,fund)

        # Breadth
        bs=0; bd="Sin datos de breadth"; bp=None
        sec_etfs=[(e["id"],e.get("aum_bn",1.0),etf_cache.get(e["id"],(None,None))[0])
                  for e in universe_primary if e["sector"]==etf["sector"]]
        sec_etfs=[(eid,a,p) for eid,a,p in sec_etfs if p]
        if len(sec_etfs)>=2:
            sec_etfs.sort(key=lambda x:x[1],reverse=True)
            bs,bd=compute_breadth_from_pair(sec_etfs[1][2],sec_etfs[0][2])
        elif etf["id"] in ETF_HOLDINGS:
            print(f"(holdings)...",end=" ",flush=True)
            bs,bd,bp=compute_breadth_from_holdings(etf["id"])

        aum_p=1.0
        if aum<MIN_AUM_BN: aum_p=0.95; WARN.append(f"{sym}: AUM bajo ({aum}B)")

        sf=compute_final_score(score_tech,score_macro,overval["penalty"],fp,srp,bs)
        sf=round(sf*aum_p,1)

        extra=tech_det.get("extra",{})
        rec={"id":etf["id"],"name":etf["name"],"symbol":sym,"sector":etf["sector"],
            "conviction":etf.get("conviction",4),"macro_profile":mp,"aum_bn":aum,"universe":"primary",
            "last":round(prices[-1],4),"score_tech":score_tech,"score_macro":score_macro,"score_final":sf,
            "pct_rel_strength":tech_det.get("rel_strength",{}).get("percentile"),
            "pct_ema200":tech_det.get("ema200",{}).get("percentile"),
            "pct_mom6m":tech_det.get("mom6m",{}).get("percentile"),
            "pct_entry":tech_det.get("entry",{}).get("percentile"),
            "pct_consistency":tech_det.get("consistency",{}).get("percentile"),
            "rel_strength":tech_det.get("rel_strength",{}).get("value"),
            "dist_ema200":tech_det.get("ema200",{}).get("value"),
            "ema200_abs":tech_det.get("ema200",{}).get("ema200_abs"),
            "dist_from_max":tech_det.get("entry",{}).get("dist_from_max_52w"),
            "dist_from_max_5y":tech_det.get("entry",{}).get("dist_from_max_5y"),
            "consistency_pct":tech_det.get("consistency",{}).get("value"),
            "mom_penalty":not tech_det.get("penalty",{}).get("applied",False),
            "r1m":extra.get("r1m"),"r3m":extra.get("r3m"),"r6m":extra.get("r6m"),"r12m":extra.get("r12m"),
            "vol":extra.get("vol"),"drawdown":extra.get("drawdown"),"ann_ret":extra.get("ann_ret"),
            "pe":fund.get("pe"),"pe_forward":fund.get("pe_forward"),"beta":fund.get("beta"),
            "dy":fund.get("dy"),"growth_est":fund.get("growth_est"),
            "overval_score":overval["overval_score"],"overval_level":overval["level"],
            "overval_penalty":overval["penalty"],"overval_signals":overval["signals"],
            "per_expansion":overval.get("per_expansion"),"peg":overval.get("peg"),
            "dist_from_max_5y_overval":overval.get("dist_alltime"),
            "breadth_score":bs,"breadth_desc":bd,"breadth_pct":bp,
            "failure_patterns":fpatterns,"failure_penalty":fp,
            "regime_penalty":srp,"mom_weight_adj":mwa,
            "sparkline":[round(p,4) for p in prices[-60:]],"spark_dates":dates[-60:] if dates else [],
            "tech_details":tech_det,"macro_details":macro_det}
        ups,dns=build_reasons(rec,macro_det,overval,fpatterns,bd,regime_info["regime"])
        rec["reasons_up"]=ups; rec["reasons_down"]=dns
        del rec["tech_details"]; del rec["macro_details"]
        records.append(rec)

        flags=[]
        if overval["penalty"]!=1.0: flags.append(overval["level"])
        if fpatterns: flags.append(f"⚠️{len(fpatterns)}p")
        if bs!=0: flags.append(f"breadth{bs:+d}")
        if srp!=1.0: flags.append(f"reg×{srp}")
        print(f"tech={score_tech:.0f} macro={score_macro:.0f} final={sf:.0f} {' '.join(flags)}")

    if not records: print("ERROR: sin datos"); return
    records.sort(key=lambda x:x["score_final"],reverse=True)
    sector_ranking=best_etf_per_sector(records)
    sector_ranking.sort(key=lambda x:x["score_final"],reverse=True)

    print("\nAnalizando cartera actual...")
    portfolio_signals=build_portfolio_signals(CARTERA)
    for s in portfolio_signals:
        icon="✅" if s["signal"]=="green" else ("⚠️" if s["signal"]=="yellow" else "🔴")
        print(f"  {icon} {s['symbol']} ({'semanal' if s.get('ema_type')=='weekly' else 'diaria'}): {s['signal_text']}")

    month_str=datetime.date.today().strftime("%B %Y")
    recommendation=build_recommendation(sector_ranking,month_str,portfolio_signals,regime_info)
    macro_context={"tipos":macro.get("interest_rates",{}).get("interpretation","Sin datos"),
        "vix":macro.get("vix",{}).get("interpretation","Sin datos"),
        "dolar":macro.get("dxy",{}).get("interpretation","Sin datos"),
        "halving":macro.get("bitcoin_halving",{}).get("description","Sin datos"),
        "fred":macro.get("fred_available",False),"updated":macro.get("updated",""),"regime":regime_info}
    out={"updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z",
        "total_analyzed":len(records),"model_version":"10.0",
        "factor_weights":{"tech":W_FINAL["tech"],"macro":W_FINAL["macro"],
                          "tech_factors_base":W_TECH_BASE,"tech_factors_regime":w_tech_r},
        "market_regime":regime_info,"recommendation":recommendation,
        "portfolio_signals":portfolio_signals,"sector_ranking":sector_ranking,
        "all":records,"macro_context":macro_context,"warnings":WARN}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as fh: json.dump(out,fh,ensure_ascii=False,indent=2)

    print(f"\n{'='*65}")
    print(f"RÉGIMEN: {regime_info['regime'].upper()} — {regime_info['description']}")
    print(f"RECOMENDACIÓN {month_str} — {recommendation['calidad']}")
    print(f"  {recommendation['accion_principal']}")
    for d in recommendation.get("distribucion",[]):
        print(f"  #{d['rank']} {d['symbol']:10s} score={d['score']:5.1f} → €{d['euros']} ({d['pct']}%) {d.get('overval_level','')}")
    print(f"\nRANKING SECTORES (v10):")
    for i,r in enumerate(sector_ranking[:5]):
        fp=f" ⚠️{len(r.get('failure_patterns',[]))}p" if r.get("failure_patterns") else ""
        br=f" breadth{r.get('breadth_score',0):+d}" if r.get("breadth_score",0)!=0 else ""
        print(f"  #{i+1} {r['sector']:20s} {r['symbol']:10s} score={r['score_final']:5.1f} {r.get('overval_level','')}{fp}{br}")
    print(f"{'='*65}")
    print(f"v10: breadth+patrones+regimen. Avisos: {len(WARN)}")

if __name__ == "__main__":
    main()
