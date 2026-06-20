#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest walk-forward del modelo v6 (quant profesional).
Score en percentiles propios. Compara vs IWDA. Analiza predictividad del score.
"""

import json, math, os, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI  = os.path.join(ROOT, "universe.json")
OUT  = os.path.join(ROOT, "data", "backtest.json")
UA   = {"User-Agent": "Mozilla/5.0 (compatible; Backtest/4.0)"}
BITCOIN_HALVING_DATE = datetime.date(2024, 4, 19)
W_TECH = {"rel_strength":0.25,"ema200":0.25,"mom6m":0.20,"entry":0.20,"consistency":0.10}

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_history_2y(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2y&interval=1d"
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
    except: return None,None

def ema_n(prices,n):
    if len(prices)<n: return None
    k=2.0/(n+1); ema=sum(prices[:n])/n
    for p in prices[n:]: ema=p*k+ema*(1-k)
    return ema

def ret_n(prices,n):
    if len(prices)<n+1: return None
    p0,p1=prices[-(n+1)],prices[-1]
    return (p1/p0-1)*100 if p0>0 else None

def drawdown_from_max(prices,n=252):
    if len(prices)<2: return None
    window=prices[-min(n,len(prices)):]; peak=max(window)
    return round((prices[-1]/peak-1)*100,2) if peak>0 else None

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

def percentile_in_history(value,series):
    if value is None or not series: return 50.0
    return round(sum(1 for v in series if v<=value)/len(series)*100,1)

def prices_up_to(all_prices,all_dates,target_date):
    cutoff=target_date.isoformat()
    for i,d in enumerate(all_dates):
        if d>cutoff: return all_prices[:i]
    return all_prices[:]

def future_return_at(all_prices,all_dates,from_date,n_days):
    from_str=from_date.isoformat(); start_idx=None
    for i,d in enumerate(all_dates):
        if d>=from_str: start_idx=i; break
    if start_idx is None: return None
    end_idx=min(start_idx+n_days,len(all_prices)-1)
    if end_idx<=start_idx: return None
    p0=all_prices[start_idx]; p1=all_prices[end_idx]
    return round((p1/p0-1)*100,2) if p0>0 else None

def compute_score_at_date(prices,iwda_prices):
    if not prices or len(prices)<60: return None
    n=len(prices)
    rs_now=None; rs_hist=[]
    if iwda_prices and len(iwda_prices)>=126:
        r_e=ret_n(prices,min(126,n-1)); r_i=ret_n(iwda_prices,min(126,len(iwda_prices)-1))
        if r_e is not None and r_i is not None: rs_now=r_e-r_i
        for i in range(126,min(n,378)):
            p_e=prices[:n-i+126] if n-i+126>126 else prices[:126]
            p_i=iwda_prices[:len(iwda_prices)-i+126] if len(iwda_prices)-i+126>126 else iwda_prices[:126]
            re=ret_n(p_e,126); ri=ret_n(p_i,126)
            if re is not None and ri is not None: rs_hist.append(re-ri)
    pct_rs=percentile_in_history(rs_now,rs_hist)
    e200=ema_n(prices,min(200,n)); ema_now=((prices[-1]/e200-1)*100) if e200 else None
    ema_hist=[]
    for i in range(1,min(253,n-200)):
        pc=prices[:n-i]; e=ema_n(pc,min(200,len(pc)))
        if e: ema_hist.append((pc[-1]/e-1)*100)
    pct_ema=percentile_in_history(ema_now,ema_hist)
    m6_now=ret_n(prices,min(126,n-1)); m6_hist=[]
    for i in range(1,min(253,n-126)):
        pc=prices[:n-i]; r=ret_n(pc,min(126,len(pc)-1))
        if r is not None: m6_hist.append(r)
    pct_m6=percentile_in_history(m6_now,m6_hist)
    dd_now=drawdown_from_max(prices,252); dd_hist=[]
    for i in range(1,min(253,n-252)):
        pc=prices[:n-i]; d=drawdown_from_max(pc,min(252,len(pc)))
        if d is not None: dd_hist.append(-d)
    pct_entry=percentile_in_history(-dd_now if dd_now is not None else None,dd_hist)
    co_now=consistency_6m(prices); co_hist=[]
    for i in range(1,min(253,n-130)):
        pc=prices[:n-i]; c=consistency_6m(pc)
        if c is not None: co_hist.append(c)
    pct_co=percentile_in_history(co_now,co_hist)
    score=(W_TECH["rel_strength"]*pct_rs+W_TECH["ema200"]*pct_ema+
           W_TECH["mom6m"]*pct_m6+W_TECH["entry"]*pct_entry+W_TECH["consistency"]*pct_co)
    m3=ret_n(prices,min(63,n-1))
    if m3 is not None and m3<-10: score*=0.6
    return round(score,1)

def macro_score_simple(eval_date,macro_profile):
    if macro_profile=="crypto_halving":
        months=(eval_date-BITCOIN_HALVING_DATE).days/30.44
        if months<=18:   return min(100,100-months*2)*0.35+50*0.65
        elif months<=30: return 60
        else:            return 45
    return 50

def main():
    with open(UNI,encoding="utf-8") as f:
        universe=json.load(f)["etfs"]
    print(f"Descargando historico de {len(universe)} ETFs...")
    etf_data={}
    for etf in universe:
        sym=etf["symbol"]
        print(f"  {sym}...",end=" ",flush=True)
        prices,dates=fetch_history_2y(sym)
        if not prices or len(prices)<120: print("sin datos"); continue
        etf_data[etf["id"]]={**etf,"prices":prices,"dates":dates}
        print(f"{len(prices)} dias")
    print("  IWDA...",end=" ")
    iwda_p,iwda_d=fetch_history_2y("IWDA.AS")
    print(f"{len(iwda_p) if iwda_p else 0} dias")
    if not etf_data: print("ERROR: sin datos"); return
    today=datetime.date.today()
    eval_dates=[]
    d=today.replace(day=1)
    for _ in range(15):
        d=(d-datetime.timedelta(days=1)).replace(day=1)
        eval_dates.append(d)
    eval_dates=sorted(eval_dates)
    print(f"\nCalculando backtest para {len(eval_dates)} fechas...")
    snapshots=[]
    for eval_date in eval_dates:
        print(f"\n  === {eval_date} ===")
        etf_scores=[]
        for eid,edata in etf_data.items():
            p_cut=prices_up_to(edata["prices"],edata["dates"],eval_date)
            if len(p_cut)<60: continue
            iwda_cut=prices_up_to(iwda_p,iwda_d,eval_date) if iwda_p else None
            st=compute_score_at_date(p_cut,iwda_cut)
            if st is None: continue
            sm=macro_score_simple(eval_date,edata.get("macro_profile",""))
            sf=round(st*0.70+sm*0.30,1)
            etf_scores.append({"id":eid,"name":edata["name"],"symbol":edata["symbol"],
                "sector":edata["sector"],"score_final":sf,"score_tech":st,"score_macro":sm})
        if not etf_scores: continue
        sector_best={}
        for r in sorted(etf_scores,key=lambda x:x["score_final"],reverse=True):
            s=r["sector"]
            if s not in sector_best: sector_best[s]=r
        sector_ranking=sorted(sector_best.values(),key=lambda x:x["score_final"],reverse=True)
        top2=sector_ranking[:2]; top2_with_rets=[]
        for r in top2:
            edata=etf_data[r["id"]]
            ret_1m=future_return_at(edata["prices"],edata["dates"],eval_date,21)
            ret_3m=future_return_at(edata["prices"],edata["dates"],eval_date,63)
            ret_6m=future_return_at(edata["prices"],edata["dates"],eval_date,126)
            acerto_3m=None if ret_3m is None else ret_3m>0
            top2_with_rets.append({**r,"ret_1m":ret_1m,"ret_3m":ret_3m,"ret_6m":ret_6m,"acerto_3m":acerto_3m})
            status="✓" if acerto_3m else ("✗" if acerto_3m is False else "?")
            print(f"    #{sector_ranking.index(r)+1} {r['symbol']:10s} [{r['sector']:20s}] score={r['score_final']:5.1f} ret3M={str(ret_3m)+'%' if ret_3m else '?':8s} {status}")
        iwda_ret_3m=future_return_at(iwda_p,iwda_d,eval_date,63) if iwda_p else None
        iwda_ret_6m=future_return_at(iwda_p,iwda_d,eval_date,126) if iwda_p else None
        top2_rets_3m=[e["ret_3m"] for e in top2_with_rets if e["ret_3m"] is not None]
        avg_top2_3m=round(sum(top2_rets_3m)/len(top2_rets_3m),2) if
