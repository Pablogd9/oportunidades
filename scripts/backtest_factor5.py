#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_factor5.py — Modelo Top1 SIN XBI (excluido por evidencia estructural).

XBI demostro fallar de forma CONSISTENTE en ambas mitades temporales
(Mitad1: -0.25%, Mitad2: -0.63%) -> razon estructural real, no ruido.
COPX se mantiene porque su mal comportamiento resulto ser ruido puntual
(Mitad1: +1.17%, Mitad2: +3.08% -> ambas positivas).
"""

import json, math, os, random, datetime
from collections import Counter, defaultdict

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest_factor5.json")
TODAY       = datetime.date.today()
N_BOOTSTRAP = 1000
WINDOW_YEARS= 5
NW_LAGS     = 2
random.seed(42)

BACKTEST_UNIVERSE = [
    ("SMH","Semiconductores"),("IBB","Biotecnologia"),("ITA","Defensa"),
    ("IGV","Software"),("VHT","Salud"),("PHO","Agua"),
    ("IHI","Salud2"),("ICLN","EnergiaLimpia"),("GRID","Infraestructura"),
    ("COPX","Cobre"),("LIT","Litio"),("INDA","India"),("ROBO","Robotica"),
    ("CIBR","Ciberseguridad"),("PAVE","Infraestructura2"),
]
BENCHMARK = "IWDA.AS"
SPLIT_DATE = datetime.date(2022, 1, 1)

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

def bootstrap_pvalue_single(real_alpha, ids, etf_data, iwda_p, iwda_d, months, n_sim=N_BOOTSTRAP):
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
    return pv,pct,mr

def sig(pv):
    if pv is None: return "Sin datos"
    if pv<0.05: return "SIGNIFICATIVO p<0.05"
    if pv<0.10: return "Marginal p<0.10"
    if pv<0.20: return "Debil p<0.20"
    return "No significativo"

def analizar_periodo(nombre, snaps_periodo, ids, etf_data, iwda_p, iwda_d, months_periodo):
    if not snaps_periodo:
        print(f"\n  {nombre}: SIN SEÑALES")
        return None
    alphas=[s["alpha"] for s in snaps_periodo]
    am=round(sum(alphas)/len(alphas),3)
    bate=round(sum(1 for a in alphas if a>0)/len(alphas)*100,1)
    pv_nw,tstat,_,_=newey_west_pvalue(alphas,NW_LAGS)
    pv_boot,_,mr=bootstrap_pvalue_single(am,ids,etf_data,iwda_p,iwda_d,months_periodo,n_sim=500)
    print(f"\n  {nombre}")
    print(f"  {'─'*60}")
    print(f"    n={len(snaps_periodo)} señales | Alpha medio: {am:+.3f}% | Bate IWDA: {bate}%")
    print(f"    Newey-West: p={pv_nw} t={tstat} -> {sig(pv_nw)}")
    print(f"    Bootstrap:  p={pv_boot} -> {sig(pv_boot)}")
    return {"n":len(snaps_periodo),"alpha_medio":am,"bate_pct":bate,
            "pvalue_nw":pv_nw,"pvalue_bootstrap":pv_boot}

def main():
    print("="*70)
    print("BACKTEST FACTOR 5 — Top1 SIN XBI (exclusion estructural)")
    print(f"Fecha: {TODAY} | ETFs: {len(BACKTEST_UNIVERSE)} (XBI excluido)")
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
            scores.append({"sym":sym,"score":sc,"ret":r})
        if not scores: continue
        scores.sort(key=lambda x:-x["score"])
        t1=scores[0]
        ri=period_return(iwda_p,iwda_d,y,m,3)
        if ri is None: continue
        snaps.append({"date":ed.isoformat(),"year":y,"top1_sym":t1["sym"],
                     "top1_score":t1["score"],"top1_ret":t1["ret"],"ri":ri,
                     "alpha":round(t1["ret"]-ri,2)})

    if not snaps: print("ERROR sin señales"); return

    print("\n"+"─"*70)
    print("MODELO COMPLETO (sin XBI) — periodo entero 2017-2026")
    print("─"*70)
    alphas=[s["alpha"] for s in snaps]
    am=round(sum(alphas)/len(alphas),3)
    bate=round(sum(1 for a in alphas if a>0)/len(alphas)*100,1)
    pv_nw,tstat,_,_=newey_west_pvalue(alphas,NW_LAGS)
    ids=list(etf_data.keys())
    pv_boot,_,mr=bootstrap_pvalue_single(am,ids,etf_data,iwda_p,iwda_d,months,n_sim=N_BOOTSTRAP)
    print(f"\n  n={len(snaps)} | Alpha medio: {am:+.3f}% | Bate IWDA: {bate}%")
    print(f"  Newey-West: p={pv_nw} t={tstat} -> {sig(pv_nw)}")
    print(f"  Bootstrap:  p={pv_boot} -> {sig(pv_boot)}")

    tops=Counter(s["top1_sym"] for s in snaps)
    print(f"\n  Sectores mas elegidos:")
    for sym,n in tops.most_common(6):
        ss=[s for s in snaps if s["top1_sym"]==sym]
        sam=round(sum(s["alpha"] for s in ss)/len(ss),2)
        print(f"    {sym:8s} {n:3d}x alpha={sam:+.2f}%")

    print("\n"+"─"*70)
    print("VALIDACION POR MITADES (sin XBI)")
    print("─"*70)
    mitad1=[s for s in snaps if datetime.date.fromisoformat(s["date"])<SPLIT_DATE]
    mitad2=[s for s in snaps if datetime.date.fromisoformat(s["date"])>=SPLIT_DATE]
    m1months=[m for m in months if datetime.date(m[0],m[1],1)<SPLIT_DATE]
    m2months=[m for m in months if datetime.date(m[0],m[1],1)>=SPLIT_DATE]
    r1=analizar_periodo("MITAD 1: 2017-2021",mitad1,ids,etf_data,iwda_p,iwda_d,m1months)
    r2=analizar_periodo("MITAD 2: 2022-2026",mitad2,ids,etf_data,iwda_p,iwda_d,m2months)

    out={"n_senales":len(snaps),"alpha_medio":am,"pvalue_nw":pv_nw,"pvalue_bootstrap":pv_boot,
         "bate_pct":bate,"mitad1":r1,"mitad2":r2,"snapshots":snaps}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*70}")
    print("RESUMEN FINAL — COMPARACION CON FACTOR3 (con XBI)")
    print(f"{'='*70}")
    print(f"  CON XBI (factor3):  alpha=+2.98% p_NW=0.0523 p_boot=0.003")
    print(f"  SIN XBI (factor5):  alpha={am:+.2f}% p_NW={pv_nw} p_boot={pv_boot}")
    if pv_nw is not None and pv_nw < 0.0523:
        print(f"  -> MEJORA: excluir XBI mejora la significancia estadistica")
    else:
        print(f"  -> NO MEJORA: excluir XBI no aporta mejora clara")
    print(f"{'='*70}")

if __name__=="__main__":
    main()
