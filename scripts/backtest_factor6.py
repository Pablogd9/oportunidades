#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_factor6.py — Momentum 12M skip-1 (70%) + Punto de entrada (30%).

Score = momentum_score x 0.70 + entrada_score x 0.30

Punto de entrada: distancia al maximo de 52 semanas, vol-normalizada,
percentil propio 5A — invertido (alto = lejos de maximos = mejor entrada).
"""

import json, math, os, random, datetime
from collections import Counter

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest_factor6.json")
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
BENCHMARK  = "IWDA.AS"
SPLIT_DATE = datetime.date(2022, 1, 1)
W_MOMENTUM = 0.70
W_ENTRADA  = 0.30

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

def momentum_score(prices):
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

def entrada_score(prices):
    if not prices or len(prices)<252: return None
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    if n<252: return None
    max_52w=max(pw[-252:])
    if max_52w<=0: return None
    dd=(pw[-1]/max_52w-1)*100
    dd_norm=dd/(vol/20.0)
    hist=[]
    for i in range(252,min(n,756)):
        pc=pw[:n-i]
        if len(pc)>=252:
            mx=max(pc[-252:])
            if mx>0:
                d_hist=((pc[-1]/mx-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0)
                hist.append(d_hist)
    pct=pct_hist(dd_norm,hist)
    return round(100-pct,1)

def score_combinado(prices):
    ms=momentum_score(prices)
    es=entrada_score(prices)
    if ms is None: return None
    if es is None: return ms
    return round(ms*W_MOMENTUM + es*W_ENTRADA, 1)

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
    if not snaps_periodo: return None
    alphas=[s["alpha"] for s in snaps_periodo]
    am=round(sum(alphas)/len(alphas),3)
    bate=round(sum(1 for a in alphas if a>0)/len(alphas)*100,1)
    pv_nw,tstat,_,_=newey_west_pvalue(alphas,NW_LAGS)
    pv_boot,_,_=bootstrap_pvalue_single(am,ids,etf_data,iwda_p,iwda_d,months_periodo,n_sim=500)
    print(f"\n  {nombre}")
    print(f"  {'─'*60}")
    print(f"    n={len(snaps_periodo)} | Alpha: {am:+.3f}% | Bate: {bate}%")
    print(f"    Newey-West: p={pv_nw} t={tstat} -> {sig(pv_nw)}")
    print(f"    Bootstrap:  p={pv_boot} -> {sig(pv_boot)}")
    return {"n":len(snaps_periodo),"alpha_medio":am,"bate_pct":bate,
            "pvalue_nw":pv_nw,"pvalue_bootstrap":pv_boot}

def main():
    print("="*70)
    print(f"BACKTEST FACTOR 6 — Momentum {int(W_MOMENTUM*100)}% + Entrada {int(W_ENTRADA*100)}%")
    print(f"Fecha: {TODAY} | ETFs: {len(BACKTEST_UNIVERSE)} (sin XBI)")
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
    print(f"\nDesde {bt_start} | {len(months)} señales | horizonte 3M")
    print(f"Score = momentum x{W_MOMENTUM} + entrada x{W_ENTRADA}")

    snaps=[]; cambios_vs_f5=0

    for y,m in months:
        ed=datetime.date(y,m,1)
        scores_f6=[]; scores_f5=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            if len(pt)<273: continue
            ms=momentum_score(pt)
            if ms is None: continue
            sc=score_combinado(pt)
            if sc is None: continue
            r=period_return(data["prices"],data["dates"],y,m,3)
            ri=period_return(iwda_p,iwda_d,y,m,3)
            if r is None or ri is None: continue
            scores_f6.append({"sym":sym,"score":sc,"ms":ms,"ret":r})
            scores_f5.append({"sym":sym,"score":ms,"ret":r})

        if not scores_f6: continue
        scores_f6.sort(key=lambda x:-x["score"])
        scores_f5.sort(key=lambda x:-x["score"])
        t1_f6=scores_f6[0]; t1_f5=scores_f5[0]
        if t1_f6["sym"]!=t1_f5["sym"]: cambios_vs_f5+=1

        ri=period_return(iwda_p,iwda_d,y,m,3)
        if ri is None: continue

        snaps.append({"date":ed.isoformat(),"year":y,
            "top1_sym":t1_f6["sym"],"top1_score":t1_f6["score"],"top1_ms":t1_f6["ms"],
            "top1_ret":t1_f6["ret"],"ri":ri,"alpha":round(t1_f6["ret"]-ri,2),
            "top1_f5":t1_f5["sym"],"cambio_vs_f5":t1_f6["sym"]!=t1_f5["sym"]})

    if not snaps: print("ERROR sin señales"); return

    print(f"\n  Factor entrada cambio el Top1 en {cambios_vs_f5}/{len(snaps)} meses ({round(cambios_vs_f5/len(snaps)*100,1)}%)")

    print("\n"+"─"*70)
    print("MODELO COMPLETO — periodo entero 2017-2026")
    print("─"*70)
    alphas=[s["alpha"] for s in snaps]
    am=round(sum(alphas)/len(alphas),3)
    bate=round(sum(1 for a in alphas if a>0)/len(alphas)*100,1)
    pv_nw,tstat,_,_=newey_west_pvalue(alphas,NW_LAGS)
    ids=list(etf_data.keys())
    pv_boot,_,mr=bootstrap_pvalue_single(am,ids,etf_data,iwda_p,iwda_d,months)
    print(f"\n  n={len(snaps)} | Alpha medio: {am:+.3f}% | Bate IWDA: {bate}%")
    print(f"  Newey-West: p={pv_nw} t={tstat} -> {sig(pv_nw)}")
    print(f"  Bootstrap:  p={pv_boot} -> {sig(pv_boot)}")

    tops=Counter(s["top1_sym"] for s in snaps)
    print(f"\n  Sectores mas elegidos:")
    for sym,n in tops.most_common(6):
        ss=[s for s in snaps if s["top1_sym"]==sym]
        sam=round(sum(s["alpha"] for s in ss)/len(ss),2)
        print(f"    {sym:8s} {n:3d}x alpha={sam:+.2f}%")

    cambios=[s for s in snaps if s.get("cambio_vs_f5")]
    sin_cambio=[s for s in snaps if not s.get("cambio_vs_f5")]
    if cambios:
        am_c=round(sum(s["alpha"] for s in cambios)/len(cambios),2)
        am_s=round(sum(s["alpha"] for s in sin_cambio)/len(sin_cambio),2) if sin_cambio else None
        print(f"\n  Impacto del factor entrada:")
        print(f"    Meses CON cambio de Top1:  n={len(cambios):3d} | alpha={am_c:+.2f}%")
        print(f"    Meses SIN cambio de Top1:  n={len(sin_cambio):3d} | alpha={am_s:+.2f}%")
        if am_c is not None and am_s is not None:
            if am_c > am_s:
                print(f"    -> El factor entrada MEJORA los meses donde actua")
            else:
                print(f"    -> El factor entrada NO mejora los meses donde actua")

    print("\n"+"─"*70)
    print("VALIDACION POR MITADES")
    print("─"*70)
    mitad1=[s for s in snaps if datetime.date.fromisoformat(s["date"])<SPLIT_DATE]
    mitad2=[s for s in snaps if datetime.date.fromisoformat(s["date"])>=SPLIT_DATE]
    m1months=[m for m in months if datetime.date(m[0],m[1],1)<SPLIT_DATE]
    m2months=[m for m in months if datetime.date(m[0],m[1],1)>=SPLIT_DATE]
    r1=analizar_periodo("MITAD 1: 2017-2021",mitad1,ids,etf_data,iwda_p,iwda_d,m1months)
    r2=analizar_periodo("MITAD 2: 2022-2026",mitad2,ids,etf_data,iwda_p,iwda_d,m2months)

    out={"n_senales":len(snaps),"alpha_medio":am,"pvalue_nw":pv_nw,"pvalue_bootstrap":pv_boot,
         "bate_pct":bate,"pesos":{"momentum":W_MOMENTUM,"entrada":W_ENTRADA},
         "cambios_vs_f5":cambios_vs_f5,"mitad1":r1,"mitad2":r2,"snapshots":snaps}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*70}")
    print("RESUMEN FINAL — COMPARACION CON FACTOR5 (solo momentum)")
    print(f"{'='*70}")
    print(f"  FACTOR 5 (momentum puro):          alpha=+3.02% p_NW=0.0483 p_boot=0.003")
    print(f"  FACTOR 6 (mom 70% + entrada 30%):  alpha={am:+.2f}% p_NW={pv_nw} p_boot={pv_boot}")
    if pv_nw is not None and pv_nw < 0.0483:
        print(f"  -> MEJORA: el factor entrada mejora la significancia")
    elif pv_nw is not None and pv_nw < 0.10:
        print(f"  -> NEUTRAL: no mejora ni empeora significativamente")
    else:
        print(f"  -> NO MEJORA: el factor entrada empeora el modelo")
    print(f"{'='*70}")

if __name__=="__main__":
    main()
