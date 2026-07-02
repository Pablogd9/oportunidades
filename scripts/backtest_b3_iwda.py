#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_b3_iwda.py — Dos analisis en uno:
1. B3: Factor5 exacto + entrada 70/30 (verificacion limpia)
2. PATRON IWDA: cuando conviene IWDA en vez del Top1
"""

import json, math, os, datetime
from collections import defaultdict, Counter

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest_b3_iwda.json")
TODAY       = datetime.date.today()
WINDOW_YEARS= 5
NW_LAGS     = 2
SPLIT_DATE  = datetime.date(2022, 1, 1)

BACKTEST_UNIVERSE = [
    ("SMH","Semiconductores"),("IBB","Biotecnologia"),("ITA","Defensa"),
    ("IGV","Software"),("VHT","Salud"),("PHO","Agua"),
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
    if n<10: return None,None
    mean=sum(alphas)/n
    var=sum((a-mean)**2 for a in alphas)/n
    for lag in range(1,lags+1):
        cov=sum((alphas[i]-mean)*(alphas[i-lag]-mean) for i in range(lag,n))/n
        var+=2*(1.0-lag/(lags+1))*cov
    se=math.sqrt(max(var,0)/n) if var>0 else 0.0001
    tstat=mean/se
    def ncdf(x):
        t_=1.0/(1.0+0.2316419*abs(x))
        poly=(0.31938153*t_-0.356563782*t_**2+1.781477937*t_**3
              -1.821255978*t_**4+1.330274429*t_**5)
        return 1.0-(1.0/math.sqrt(2*math.pi))*math.exp(-x**2/2)*poly if x>=0 else ncdf(-x)
    pv=round(min(1.0,2*(1.0-ncdf(abs(tstat)))),4)
    return pv,round(tstat,3)

def momentum_score(prices):
    """IDENTICO al Factor5."""
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
            if r is not None:
                hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return pct_hist(mn,hist)

def entrada_score(prices):
    if not prices or len(prices)<252: return None
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    if n<252: return None
    max_52w=max(pw[-252:])
    if max_52w<=0: return None
    dd=(pw[-1]/max_52w-1)*100; dd_n=dd/(vol/20.0)
    hist=[]
    for i in range(252,min(n,756)):
        pc=pw[:n-i]
        if len(pc)>=252:
            mx=max(pc[-252:])
            if mx>0:
                hist.append(((pc[-1]/mx-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return round(100-pct_hist(dd_n,hist),1)

def sig(pv):
    if pv is None: return "Sin datos"
    if pv<0.05: return "SIGNIFICATIVO p<0.05"
    if pv<0.10: return "Marginal p<0.10"
    if pv<0.20: return "Debil p<0.20"
    return "No significativo"

def main():
    print("="*70)
    print("BACKTEST B3 + ANALISIS PATRON IWDA")
    print(f"Fecha: {TODAY}")
    print("="*70)

    print("\nCargando datos...")
    etf_data={}
    for sym,sec in BACKTEST_UNIVERSE:
        p,d=load_from_cache(sym)
        if not p or len(p)<273:
            print(f"  {sym:8s} insuficiente"); continue
        etf_data[sym]={"sector":sec,"prices":p,"dates":d}
        print(f"  {sym:8s} {len(p):5d}d")
    iwda_p,iwda_d=load_from_cache(BENCHMARK)
    if not iwda_p: print("ERROR sin IWDA"); return

    starts=sorted([datetime.date.fromisoformat(d["dates"][0]) for d in etf_data.values()])
    idx=min(int(len(starts)*0.75),len(starts)-1)
    bt_start=datetime.date(starts[idx].year+WINDOW_YEARS,starts[idx].month,1)

    months=[]; dt=bt_start
    while dt<=TODAY.replace(day=1):
        months.append((dt.year,dt.month))
        dt=datetime.date(dt.year+1,1,1) if dt.month==12 else datetime.date(dt.year,dt.month+1,1)
    months=[m for m in months
            if datetime.date(m[0],m[1],1)<=TODAY.replace(day=1)-datetime.timedelta(days=90)]
    print(f"\nDesde {bt_start} | {len(months)} señales | horizonte 3M")

    snaps_b1=[]; snaps_b3=[]
    snaps_m1_b1=[]; snaps_m2_b1=[]
    snaps_m1_b3=[]; snaps_m2_b3=[]
    iwda_analisis=[]

    for y,m in months:
        ed=datetime.date(y,m,1)
        ri=period_return(iwda_p,iwda_d,y,m,3)
        if ri is None: continue

        it=prices_up_to(iwda_p,iwda_d,ed)
        iwda_mom=momentum_score(it) if len(it)>=273 else None

        scores_b1=[]; scores_b3=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            if len(pt)<273: continue
            ms=momentum_score(pt)
            if ms is None: continue
            r=period_return(data["prices"],data["dates"],y,m,3)
            if r is None: continue
            scores_b1.append({"sym":sym,"score":ms,"ret":r,"alpha":round(r-ri,2)})
            es=entrada_score(pt)
            if es is None: es=50.0
            scores_b3.append({"sym":sym,"score":ms*0.70+es*0.30,"ms":ms,"es":es,
                              "ret":r,"alpha":round(r-ri,2)})

        if not scores_b1: continue
        scores_b1.sort(key=lambda x:-x["score"])
        scores_b3.sort(key=lambda x:-x["score"])
        t1=scores_b1[0]; t3=scores_b3[0]

        snap1={"date":ed.isoformat(),"year":y,"sym":t1["sym"],
               "score":t1["score"],"ret":t1["ret"],"ri":ri,
               "alpha":round(t1["ret"]-ri,2)}
        snap3={"date":ed.isoformat(),"year":y,"sym":t3["sym"],
               "score":t3["score"],"ret":t3["ret"],"ri":ri,
               "alpha":round(t3["ret"]-ri,2),
               "cambio":t3["sym"]!=t1["sym"]}

        snaps_b1.append(snap1)
        snaps_b3.append(snap3)
        if ed<SPLIT_DATE:
            snaps_m1_b1.append(snap1); snaps_m1_b3.append(snap3)
        else:
            snaps_m2_b1.append(snap1); snaps_m2_b3.append(snap3)

        iwda_analisis.append({
            "date":ed.isoformat(),"year":y,
            "top1_sym":t1["sym"],"top1_score":t1["score"],
            "top1_ret":t1["ret"],"iwda_ret":ri,
            "alpha":round(t1["ret"]-ri,2),
            "iwda_mejor":ri>t1["ret"],
            "iwda_mom":iwda_mom,
        })

    def mostrar(nombre, snaps, sm1, sm2):
        als=[s["alpha"] for s in snaps]
        am=round(sum(als)/len(als),3)
        bate=round(sum(1 for a in als if a>0)/len(als)*100,1)
        pv,_=newey_west_pvalue(als,NW_LAGS)
        am1=round(sum(s["alpha"] for s in sm1)/len(sm1),3) if sm1 else None
        am2=round(sum(s["alpha"] for s in sm2)/len(sm2),3) if sm2 else None
        pv1,_=newey_west_pvalue([s["alpha"] for s in sm1],NW_LAGS) if sm1 else (None,None)
        pv2,_=newey_west_pvalue([s["alpha"] for s in sm2],NW_LAGS) if sm2 else (None,None)
        diff=round(abs((am1 or 0)-(am2 or 0)),3)
        print(f"\n  {nombre}:")
        print(f"    n={len(snaps)} | Alpha={am:+.3f}% | Bate={bate}% | p_NW={pv} → {sig(pv)}")
        print(f"    M1={am1:+.3f}% p={pv1} | M2={am2:+.3f}% p={pv2} | Diff={diff}%")
        return am,pv,am1,pv1,am2,pv2

    print(f"\n{'='*70}")
    print("PARTE 1 — B1 vs B3")
    print(f"{'='*70}")
    r1=mostrar("B1 (momentum puro skip-1)",snaps_b1,snaps_m1_b1,snaps_m2_b1)
    r3=mostrar("B3 (momentum 70% + entrada 30%)",snaps_b3,snaps_m1_b3,snaps_m2_b3)

    print(f"\n  VERIFICACION:")
    print(f"    Factor5 B1: alpha=+2.983% p=0.0483")
    print(f"    Este B1:    alpha={r1[0]:+.3f}% p={r1[1]}")
    if r1[1] and abs(r1[0]-2.983)<0.1:
        print(f"    → COINCIDE ✓ — codigo correcto, B3 tambien fiable")
    else:
        print(f"    → NO coincide — hay diferencia en implementacion")

    cambios=[s for s in snaps_b3 if s.get("cambio")]
    sc=[s for s in snaps_b3 if not s.get("cambio")]
    if cambios and sc:
        ac=round(sum(s["alpha"] for s in cambios)/len(cambios),2)
        as_=round(sum(s["alpha"] for s in sc)/len(sc),2)
        print(f"\n  Entrada cambia decision: {len(cambios)}/{len(snaps_b3)} meses")
        print(f"    CON cambio: alpha={ac:+.2f}% | SIN cambio: alpha={as_:+.2f}%")
        print(f"    → {'Entrada MEJORA' if ac>as_ else 'Entrada NO mejora'} cuando actua")

    print(f"\n{'='*70}")
    print("PARTE 2 — PATRON IWDA")
    print(f"{'='*70}")

    n_t=len(iwda_analisis)
    n_iw=sum(1 for x in iwda_analisis if x["iwda_mejor"])
    print(f"\n  IWDA mejor que Top1: {n_iw}/{n_t} meses ({round(n_iw/n_t*100,1)}%)")

    print(f"\n  Alpha por año:")
    print(f"  {'Año':6s} {'N':>4} {'Alpha':>8} {'Bate%':>7} {'IWDA>Top1':>10}")
    by_year=defaultdict(list)
    for x in iwda_analisis: by_year[x["year"]].append(x)
    for yr in sorted(by_year.keys()):
        xs=by_year[yr]
        als=[x["alpha"] for x in xs]
        am=round(sum(als)/len(als),2)
        bate=round(sum(1 for a in als if a>0)/len(als)*100,0)
        niw=sum(1 for x in xs if x["iwda_mejor"])
        nota=" ← MAL AÑO" if am<-3 else " ← MUY BUEN AÑO" if am>8 else ""
        print(f"  {yr:6d} {len(xs):>4} {am:>+7.2f}% {bate:>6.0f}% {niw:>4d}/{len(xs)}{nota}")

    print(f"\n  PATRON DE SCORE — score bajo implica IWDA mejor?")
    for umbral in [50, 60, 70]:
        bajo=[x for x in iwda_analisis if x["top1_score"]<umbral]
        alto=[x for x in iwda_analisis if x["top1_score"]>=umbral]
        if not bajo: continue
        am_b=round(sum(x["alpha"] for x in bajo)/len(bajo),2)
        niw_b=sum(1 for x in bajo if x["iwda_mejor"])
        am_a=round(sum(x["alpha"] for x in alto)/len(alto),2) if alto else None
        niw_a=sum(1 for x in alto if x["iwda_mejor"]) if alto else 0
        print(f"    Score < {umbral}: n={len(bajo):3d} alpha={am_b:+.2f}% IWDA>{niw_b}/{len(bajo)} ({round(niw_b/len(bajo)*100,0):.0f}%)")
        if alto:
            print(f"    Score >= {umbral}: n={len(alto):3d} alpha={am_a:+.2f}% IWDA>{niw_a}/{len(alto)} ({round(niw_a/len(alto)*100,0):.0f}%)")

    print(f"\n  MOMENTUM RELATIVO — cuando IWDA tiene mas momentum que Top1:")
    con_iwda=[x for x in iwda_analisis if x["iwda_mom"] is not None]
    if con_iwda:
        iwda_gana_mom=[x for x in con_iwda if x["iwda_mom"]>x["top1_score"]]
        iwda_pierde_mom=[x for x in con_iwda if x["iwda_mom"]<=x["top1_score"]]
        if iwda_gana_mom:
            am_ig=round(sum(x["alpha"] for x in iwda_gana_mom)/len(iwda_gana_mom),2)
            am_ip=round(sum(x["alpha"] for x in iwda_pierde_mom)/len(iwda_pierde_mom),2) if iwda_pierde_mom else None
            print(f"    IWDA mom > Top1: n={len(iwda_gana_mom):3d} alpha sistema={am_ig:+.2f}%")
            print(f"    IWDA mom < Top1: n={len(iwda_pierde_mom):3d} alpha sistema={am_ip:+.2f}%")
            if am_ig<0:
                print(f"    → Cuando IWDA tiene mas momentum, el sistema PIERDE alpha")
                print(f"    → Podria tener sentido ir a IWDA en esos meses")

    print(f"\n  SECTORES donde IWDA mas frecuentemente gana:")
    syms_iw=[x["top1_sym"] for x in iwda_analisis if x["iwda_mejor"]]
    tops=Counter(syms_iw)
    for sym,cnt in tops.most_common(5):
        tot=sum(1 for x in iwda_analisis if x["top1_sym"]==sym)
        am_s=round(sum(x["alpha"] for x in iwda_analisis if x["top1_sym"]==sym)/tot,2)
        print(f"    {sym:8s}: IWDA ganó {cnt}/{tot} ({round(cnt/tot*100,0):.0f}%) alpha medio={am_s:+.2f}%")

    out={"fecha":TODAY.isoformat(),
         "b1":{"alpha":r1[0],"pvalue":r1[1],"m1":r1[2],"m2":r1[4]},
         "b3":{"alpha":r3[0],"pvalue":r3[1],"m1":r3[2],"m2":r3[4]},
         "iwda":{"n_total":n_t,"n_iwda_mejor":n_iw,"pct":round(n_iw/n_t*100,1)}}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*70}")
    print(f"  B1: alpha={r1[0]:+.3f}% p={r1[1]}")
    print(f"  B3: alpha={r3[0]:+.3f}% p={r3[1]}")
    print(f"  IWDA mejor: {round(n_iw/n_t*100,1)}% de los meses")
    print(f"{'='*70}")

if __name__=="__main__":
    main()
