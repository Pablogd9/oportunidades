#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_factor1.py — Modelo de UN SOLO FACTOR: momentum 12M skip-1.

Objetivo: probar si el factor mas basico y academicamente validado
tiene alpha real ANTES de anadir cualquier otra complejidad.
"""

import json, math, os, random, datetime

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest_factor1.json")
TODAY       = datetime.date.today()
N_BOOTSTRAP = 1000
WINDOW_YEARS= 5
NW_LAGS     = 2
random.seed(42)

BACKTEST_UNIVERSE = [
    ("SMH","Semiconductores"),("IBB","Biotecnologia"),("ITA","Defensa"),
    ("IGV","Software"),("VHT","Salud"),("PHO","Agua"),("XBI","Biotecnologia2"),
    ("IHI","Salud2"),("ICLN","EnergiaLimpia"),("GRID","Infraestructura"),
    ("COPX","Cobre"),("LIT","Litio"),("INDA","India"),("ROBO","Robotica"),
    ("CIBR","Ciberseguridad"),("PAVE","Infraestructura2"),
]
BENCHMARK = "IWDA.AS"

def load_from_cache(symbol):
    path=os.path.join(CACHE,f"{symbol.replace('.','-')}.json")
    if os.path.exists(path):
        with open(path,encoding="utf-8") as f: d=json.load(f)
        if d.get("dates") and d.get("prices"): return d["prices"],d["dates"]
    return None,None

def ret_range(prices,s,e):
    if abs(s)>=len(prices) or abs(e)>=len(prices): return None
    p0=prices[s]; p1=prices[e]
    return (p1/p0-1)*100 if p0>0 else None

def vol_std(prices,n=252):
    n=min(n,len(prices)-1)
    if n<5: return 20.0
    rets=[prices[i]/prices[i-1]-1 for i in range(len(prices)-n,len(prices))]
    mean=sum(rets)/len(rets)
    sd=math.sqrt(sum((r-mean)**2 for r in rets)/(len(rets)-1))
    return max(5.0,sd*math.sqrt(252)*100)

def pct_hist(value,series):
    if value is None or not series: return 50.0
    return round(sum(1 for v in series if v<=value)/len(series)*100,1)

def prices_up_to(p,d,target):
    cutoff=target.isoformat()
    for i,dt in enumerate(d):
        if dt>cutoff: return p[:i]
    return p[:]

def price_at_date(p,d,target):
    ts=target.isoformat(); bp=None; bd=float('inf')
    for i,dt in enumerate(d):
        diff=abs((datetime.date.fromisoformat(dt)-datetime.date.fromisoformat(ts)).days)
        if diff<bd: bd=diff; bp=p[i]
        if dt>ts and diff>5: break
    return bp

def period_return(p,d,year,month,n_months=3):
    first=datetime.date(year,month,1)
    em=month+n_months; ey=year
    while em>12: em-=12; ey+=1
    last=datetime.date(ey,em,1)-datetime.timedelta(days=1)
    p0=price_at_date(p,d,first); p1=price_at_date(p,d,last)
    return round((p1/p0-1)*100,2) if p0 and p1 and p0>0 else None

def newey_west_pvalue(alphas,lags=NW_LAGS):
    n=len(alphas)
    if n<10: return None,None,None,None
    mean=sum(alphas)/n
    var=sum((a-mean)**2 for a in alphas)/n
    for lag in range(1,lags+1):
        cov=sum((alphas[i]-mean)*(alphas[i-lag]-mean) for i in range(lag,n))/n
        var+=2*(1.0-lag/(lags+1))*cov
    se=math.sqrt(max(var,0)/n) if var>0 else 0.0001
    tstat=mean/se
    def ncdf(x):
        t_=1.0/(1.0+0.2316419*abs(x))
        poly=(0.31938153*t_-0.356563782*t_**2+1.781477937*t_**3-1.821255978*t_**4+1.330274429*t_**5)
        return 1.0-(1.0/math.sqrt(2*math.pi))*math.exp(-x**2/2)*poly if x>=0 else ncdf(-x)
    pv=round(min(1.0,2*(1.0-ncdf(abs(tstat)))),4)
    return pv,round(tstat,3),round(mean,4),round(se,4)

def momentum_score(prices,iwda_prices):
    if not prices or len(prices)<273: return None
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    if n<273: return None
    m=ret_range(pw,-273,-21)
    if m is None: return None
    mn=m/(vol/20.0)
    hist=[]
    for i in range(273,min(n,756)):
        pc=pw[:n-i]
        if len(pc)>=273:
            r=ret_range(pc,-273,-21)
            if r is not None: hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return pct_hist(mn,hist)

def bootstrap_pvalue(real_alpha,ids,etf_data,iwda_p,iwda_d,months,n_sim=N_BOOTSTRAP):
    print(f"\n  Bootstrap {n_sim}...",end=" ",flush=True)
    ra=[]
    for _ in range(n_sim):
        rs=0.0; ris=0.0; nm=0
        for y,m in months:
            avail=[i for i in ids if etf_data[i]["prices"] and
                   len(prices_up_to(etf_data[i]["prices"],etf_data[i]["dates"],datetime.date(y,m,1)))>=273]
            if len(avail)<2: continue
            ch=random.sample(avail,2)
            r1=period_return(etf_data[ch[0]]["prices"],etf_data[ch[0]]["dates"],y,m,3)
            r2=period_return(etf_data[ch[1]]["prices"],etf_data[ch[1]]["dates"],y,m,3)
            ri=period_return(iwda_p,iwda_d,y,m,3)
            if r1 is not None and r2 is not None and ri is not None:
                rs+=r1*0.70+r2*0.30; ris+=ri; nm+=1
        if nm>0: ra.append((rs-ris)/nm)
    if not ra: return None,None,None
    pct=sum(1 for a in ra if a<=real_alpha)/len(ra)*100
    pv=round(1-pct/100,4); mr=round(sum(ra)/len(ra),3)
    print(f"alpha_rand={mr}% real={real_alpha}% pct={pct:.0f}% p={pv}")
    return pv,pct,mr

def main():
    print("="*65)
    print("BACKTEST FACTOR UNICO — Momentum 12M skip-1")
    print(f"Fecha: {TODAY} | ETFs: {len(BACKTEST_UNIVERSE)}")
    print("="*65)
    print("\nCargando...")
    etf_data={}
    for sym,sec in BACKTEST_UNIVERSE:
        p,d=load_from_cache(sym)
        if not p or len(p)<273:
            print(f"  {sym:8s} insuficiente"); continue
        yrs=round((datetime.date.fromisoformat(d[-1])-datetime.date.fromisoformat(d[0])).days/365.25,1)
        print(f"  {sym:8s} {len(p):5d}d {yrs:.1f}A")
        etf_data[sym]={"sector":sec,"prices":p,"dates":d}
    iwda_p,iwda_d=load_from_cache(BENCHMARK)
    if not iwda_p: print("ERROR sin IWDA"); return
    if not etf_data: print("ERROR sin datos"); return

    starts=sorted([datetime.date.fromisoformat(d["dates"][0]) for d in etf_data.values()])
    idx=min(int(len(starts)*0.75),len(starts)-1)
    bt_start=datetime.date(starts[idx].year+WINDOW_YEARS,starts[idx].month,1)

    months=[]; dt=bt_start
    while dt<=TODAY.replace(day=1):
        months.append((dt.year,dt.month))
        dt=datetime.date(dt.year+1,1,1) if dt.month==12 else datetime.date(dt.year,dt.month+1,1)
    months=[m for m in months if datetime.date(m[0],m[1],1)<=TODAY.replace(day=1)-datetime.timedelta(days=90)]
    print(f"\nDesde {bt_start} | {len(months)} señales mensuales | horizonte 3M")

    snaps=[]
    for y,m in months:
        ed=datetime.date(y,m,1); scores=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            it=prices_up_to(iwda_p,iwda_d,ed)
            sc=momentum_score(pt,it)
            if sc is not None: scores.append({"sym":sym,"score":sc})
        if len(scores)<2: continue
        scores.sort(key=lambda x:-x["score"])
        t1,t2=scores[0],scores[1]
        r1=period_return(etf_data[t1["sym"]]["prices"],etf_data[t1["sym"]]["dates"],y,m,3)
        r2=period_return(etf_data[t2["sym"]]["prices"],etf_data[t2["sym"]]["dates"],y,m,3)
        ri=period_return(iwda_p,iwda_d,y,m,3)
        if r1 is None or ri is None: continue
        rp=r1*0.70+r2*0.30 if r2 is not None else r1
        snaps.append({"date":ed.isoformat(),"top1":t1["sym"],"score":t1["score"],
                     "r1":r1,"ri":ri,"alpha":round(rp-ri,2),"bate":r1>ri})

    if not snaps: print("ERROR sin señales"); return
    alphas=[s["alpha"] for s in snaps]
    am=round(sum(alphas)/len(alphas),3)
    pb=round(sum(1 for s in snaps if s["bate"])/len(snaps)*100,1)
    pv_nw,tstat,_,_=newey_west_pvalue(alphas,NW_LAGS)
    pv_boot,_,mr=bootstrap_pvalue(am,list(etf_data.keys()),etf_data,iwda_p,iwda_d,months)

    def sig(pv):
        if pv is None: return "Sin datos"
        if pv<0.05: return "SIGNIFICATIVO p<0.05"
        if pv<0.10: return "Marginal p<0.10"
        if pv<0.20: return "Debil p<0.20"
        return "No significativo"

    print(f"\n{'='*65}\nRESULTADO\n{'='*65}")
    print(f"Señales: {len(snaps)} | Alpha: {am:+.3f}%/señal | Bate: {pb}%")
    print(f"P-Newey-West: {pv_nw} t={tstat} -> {sig(pv_nw)}")
    print(f"P-Bootstrap: {pv_boot} -> {sig(pv_boot)}")

    from collections import Counter
    tops=Counter(s["top1"] for s in snaps)
    print("\nSectores mas elegidos:")
    for sym,n in tops.most_common(5):
        ss=[s for s in snaps if s["top1"]==sym]
        sam=round(sum(s["alpha"] for s in ss)/len(ss),2)
        print(f"  {sym:8s} {n:3d}x alpha={sam:+.2f}%")

    out={"n":len(snaps),"alpha":am,"pv_nw":pv_nw,"pv_boot":pv_boot,"pct_bate":pb,"snapshots":snaps}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*65}")
    if pv_nw is not None and pv_nw<0.20:
        print("CONCLUSION: momentum puro SI muestra señal. Construir encima.")
    else:
        print("CONCLUSION: ni momentum puro funciona. Revisar universo/periodo.")
    print("="*65)

if __name__=="__main__":
    main()
