#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_factor3.py — Solo Top1 (sin Top2) + diagnostico del quintil Q4 anomalo.

Cambios vs factor2:
  1. Modelo principal: 100% capital en Top1 (Top2 demostrado que no aporta, p=0.70)
  2. Diagnostico profundo de Q4: que ETFs/fechas componen ese quintil anomalo
  3. Analisis temporal: el alpha de Top1 por año
"""

import json, math, os, random, datetime
from collections import Counter, defaultdict

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest_factor3.json")
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

def bootstrap_pvalue_single(real_alpha,ids,etf_data,iwda_p,iwda_d,months,n_sim=N_BOOTSTRAP):
    print(f"  Bootstrap {n_sim} (solo Top1)...",end=" ",flush=True)
    ra=[]
    for _ in range(n_sim):
        rs=0.0; ris=0.0; nm=0
        for y,m in months:
            avail=[i for i in ids if etf_data[i]["prices"] and
                   len(prices_up_to(etf_data[i]["prices"],etf_data[i]["dates"],datetime.date(y,m,1)))>=273]
            if not avail: continue
            ch=random.choice(avail)
            r1=period_return(etf_data[ch]["prices"],etf_data[ch]["dates"],y,m,3)
            ri=period_return(iwda_p,iwda_d,y,m,3)
            if r1 is not None and ri is not None:
                rs+=r1; ris+=ri; nm+=1
        if nm>0: ra.append((rs-ris)/nm)
    if not ra: return None,None,None
    pct=sum(1 for a in ra if a<=real_alpha)/len(ra)*100
    pv=round(1-pct/100,4); mr=round(sum(ra)/len(ra),3)
    print(f"alpha_rand={mr}% real={real_alpha}% pct={pct:.0f}% p={pv}")
    return pv,pct,mr

def main():
    print("="*70)
    print("BACKTEST FACTOR 3 — Solo Top1 (100% capital) + diagnostico Q4")
    print(f"Fecha: {TODAY} | ETFs: {len(BACKTEST_UNIVERSE)}")
    print("="*70)

    print("\nCargando...")
    etf_data={}
    for sym,sec in BACKTEST_UNIVERSE:
        p,d=load_from_cache(sym)
        if not p or len(p)<273:
            print(f"  {sym:8s} insuficiente"); continue
        etf_data[sym]={"sector":sec,"prices":p,"dates":d}
        print(f"  {sym:8s} {len(p):5d}d")
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
    all_obs=[]

    for y,m in months:
        ed=datetime.date(y,m,1); scores=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            it=prices_up_to(iwda_p,iwda_d,ed)
            sc=momentum_score(pt,it)
            if sc is None: continue
            r=period_return(data["prices"],data["dates"],y,m,3)
            ri=period_return(iwda_p,iwda_d,y,m,3)
            if r is None or ri is None: continue
            alpha_indiv=round(r-ri,2)
            scores.append({"sym":sym,"score":sc,"ret":r})
            all_obs.append({"score":sc,"alpha":alpha_indiv,"sym":sym,"date":ed.isoformat(),"sector":data["sector"]})

        if not scores: continue
        scores.sort(key=lambda x:-x["score"])
        t1=scores[0]
        ri=period_return(iwda_p,iwda_d,y,m,3)
        if ri is None: continue

        snaps.append({"date":ed.isoformat(),"year":y,"top1_sym":t1["sym"],"top1_score":t1["score"],
                     "top1_ret":t1["ret"],"ri":ri,"alpha":round(t1["ret"]-ri,2)})

    if not snaps: print("ERROR sin señales"); return

    print("\n"+"─"*70)
    print("MODELO: 100% CAPITAL EN TOP1 (sin Top2)")
    print("─"*70)

    alphas=[s["alpha"] for s in snaps]
    am=round(sum(alphas)/len(alphas),3)
    bate=round(sum(1 for a in alphas if a>0)/len(alphas)*100,1)
    pv_nw,tstat,_,_=newey_west_pvalue(alphas,NW_LAGS)
    ids=list(etf_data.keys())
    pv_boot,_,mr=bootstrap_pvalue_single(am,ids,etf_data,iwda_p,iwda_d,months)

    def sig(pv):
        if pv is None: return "Sin datos"
        if pv<0.05: return "SIGNIFICATIVO p<0.05"
        if pv<0.10: return "Marginal p<0.10"
        if pv<0.20: return "Debil p<0.20"
        return "No significativo"

    print(f"\n  n={len(snaps)} | Alpha medio: {am:+.3f}% | Bate IWDA: {bate}%")
    print(f"  Newey-West: p={pv_nw} t={tstat} -> {sig(pv_nw)}")
    print(f"  Bootstrap:  p={pv_boot} -> {sig(pv_boot)}")

    print("\n"+"─"*70)
    print("ANALISIS TEMPORAL — Alpha de Top1 por año")
    print("─"*70)
    by_year=defaultdict(list)
    for s in snaps: by_year[s["year"]].append(s["alpha"])
    print(f"\n  {'Año':6s} {'N':>4} {'Alpha medio':>12} {'Bate%':>7}")
    for year in sorted(by_year.keys()):
        als=by_year[year]
        am_y=round(sum(als)/len(als),2)
        bate_y=round(sum(1 for a in als if a>0)/len(als)*100,0)
        flag = " <-- EXTREMO" if abs(am_y)>5 else ""
        print(f"  {year:6d} {len(als):>4} {am_y:>+11.2f}% {bate_y:>6.0f}%{flag}")

    print("\n"+"─"*70)
    print("DIAGNOSTICO Q4 — Que compone el quintil anomalo")
    print("─"*70)

    all_obs.sort(key=lambda x: x["score"])
    n_total=len(all_obs)
    q_size=n_total//5
    q4_start=3*q_size; q4_end=4*q_size
    q4_obs=all_obs[q4_start:q4_end]

    print(f"\n  Q4 contiene {len(q4_obs)} observaciones")
    print(f"  Score range: {min(o['score'] for o in q4_obs):.0f} - {max(o['score'] for o in q4_obs):.0f}")

    q4_sectors=Counter(o["sector"] for o in q4_obs)
    print(f"\n  Sectores en Q4:")
    for sec,n in q4_sectors.most_common():
        secs=[o for o in q4_obs if o["sector"]==sec]
        am_sec=round(sum(o["alpha"] for o in secs)/len(secs),2)
        print(f"    {sec:20s} n={n:3d} alpha={am_sec:+.2f}%")

    q4_years=Counter(o["date"][:4] for o in q4_obs)
    print(f"\n  Años en Q4:")
    for yr,n in sorted(q4_years.items()):
        yrs_obs=[o for o in q4_obs if o["date"][:4]==yr]
        am_yr=round(sum(o["alpha"] for o in yrs_obs)/len(yrs_obs),2)
        flag = " <-- revisar" if am_yr < -3 else ""
        print(f"    {yr} n={n:3d} alpha={am_yr:+.2f}%{flag}")

    q4_sorted=sorted(q4_obs,key=lambda x:x["alpha"])
    print(f"\n  Las 10 peores observaciones de Q4:")
    for o in q4_sorted[:10]:
        print(f"    {o['date']} {o['sym']:8s} score={o['score']:5.1f} alpha={o['alpha']:+7.2f}%")

    out={"n_senales":len(snaps),"alpha_medio":am,"pvalue_nw":pv_nw,"pvalue_bootstrap":pv_boot,
         "bate_pct":bate,"por_año":{str(y):round(sum(a)/len(a),2) for y,a in by_year.items()},
         "q4_diagnostico":{"sectores":dict(q4_sectors),"años":dict(q4_years)},
         "snapshots":snaps}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*70}")
    print("RESUMEN FINAL")
    print(f"{'='*70}")
    print(f"  Solo Top1: alpha={am:+.2f}% | p_NW={pv_nw} | p_boot={pv_boot} | {sig(pv_nw)}")
    print(f"{'='*70}")

if __name__=="__main__":
    main()
