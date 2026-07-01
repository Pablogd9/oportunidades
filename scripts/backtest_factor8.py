#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_factor8.py — Fuerza relativa 1M + Concentracion temporal del momentum.

Prueba dos factores por separado y combinados vs Factor5 base:

  M0: Factor5 base (referencia)
  M1: Factor5 + filtro fuerza relativa 1M vs IWDA
  M2: Factor5 + filtro concentracion temporal del momentum
  M3: Factor5 + ambos filtros combinados

Hipotesis A: si el Top1 pierde fuerza vs IWDA el ultimo mes,
el momentum puede estar rompiendose. Pasar al siguiente sector.

Hipotesis B: momentum gradual (12 meses distribuidos) es mas
sostenible que momentum concentrado en los ultimos 2 meses.
"""

import json, math, os, random, datetime
from collections import Counter, defaultdict

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest_factor8.json")
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
CONCENTRACION_UMBRAL = 0.60

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

def fuerza_relativa_1m(prices, iwda_prices):
    """True si el sector supera a IWDA el ultimo mes (momentum intacto)."""
    if not prices or len(prices)<22: return True
    if not iwda_prices or len(iwda_prices)<22: return True
    ret_sector=ret_range(prices,-22,-1)
    ret_iwda=ret_range(iwda_prices,-22,-1)
    if ret_sector is None or ret_iwda is None: return True
    return ret_sector >= ret_iwda

def concentracion_momentum(prices):
    """
    True si el momentum es gradual (bueno).
    False si mas del 60% del momentum vino en los ultimos 2 meses (sospechoso).
    """
    if not prices or len(prices)<273: return True
    mom_total=ret_range(prices,-273,-21)
    mom_reciente=ret_range(prices,-63,-21)
    if mom_total is None or mom_reciente is None: return True
    if abs(mom_total)<0.5: return True
    concentracion=mom_reciente/mom_total
    return concentracion<=CONCENTRACION_UMBRAL

def sig(pv):
    if pv is None: return "Sin datos"
    if pv<0.05: return "SIGNIFICATIVO p<0.05"
    if pv<0.10: return "Marginal p<0.10"
    if pv<0.20: return "Debil p<0.20"
    return "No significativo"

def calcular_stats(snaps):
    if not snaps: return None,None,None,None
    alphas=[s["alpha"] for s in snaps]
    am=round(sum(alphas)/len(alphas),3)
    bate=round(sum(1 for a in alphas if a>0)/len(alphas)*100,1)
    pv_nw,tstat,_,_=newey_west_pvalue(alphas,NW_LAGS)
    return am,bate,pv_nw,tstat

def main():
    print("="*70)
    print("BACKTEST FACTOR 8 — Fuerza relativa 1M + Concentracion temporal")
    print(f"Fecha: {TODAY} | ETFs: {len(BACKTEST_UNIVERSE)} (sin XBI)")
    print(f"Umbral concentracion: {int(CONCENTRACION_UMBRAL*100)}%")
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

    snaps_m0=[]; snaps_m1=[]; snaps_m2=[]; snaps_m3=[]
    filtro1_meses=0; filtro2_meses=0; filtro_ambos=0

    for y,m in months:
        ed=datetime.date(y,m,1); scores=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            if len(pt)<273: continue
            it=prices_up_to(iwda_p,iwda_d,ed)
            sc=momentum_score(pt)
            if sc is None: continue
            r=period_return(data["prices"],data["dates"],y,m,3)
            ri=period_return(iwda_p,iwda_d,y,m,3)
            if r is None or ri is None: continue
            fr1m_ok=fuerza_relativa_1m(pt,it)
            conc_ok=concentracion_momentum(pt)
            scores.append({"sym":sym,"score":sc,"ret":r,
                          "fr1m_ok":fr1m_ok,"conc_ok":conc_ok,
                          "alpha":round(r-ri,2)})

        if not scores: continue
        scores.sort(key=lambda x:-x["score"])
        ri=period_return(iwda_p,iwda_d,y,m,3)
        if ri is None: continue
        t1=scores[0]

        snaps_m0.append({"date":ed.isoformat(),"year":y,"sym":t1["sym"],
                        "score":t1["score"],"ret":t1["ret"],"ri":ri,
                        "alpha":round(t1["ret"]-ri,2)})

        # M1: filtro fuerza relativa 1M
        scores_fr=[s for s in scores if s["fr1m_ok"]] or scores
        t1_m1=scores_fr[0]; cambio=(t1_m1["sym"]!=t1["sym"])
        if cambio: filtro1_meses+=1
        snaps_m1.append({"date":ed.isoformat(),"year":y,"sym":t1_m1["sym"],
                        "ret":t1_m1["ret"],"ri":ri,
                        "alpha":round(t1_m1["ret"]-ri,2),"filtro":cambio})

        # M2: filtro concentracion
        scores_conc=[s for s in scores if s["conc_ok"]] or scores
        t1_m2=scores_conc[0]; cambio2=(t1_m2["sym"]!=t1["sym"])
        if cambio2: filtro2_meses+=1
        snaps_m2.append({"date":ed.isoformat(),"year":y,"sym":t1_m2["sym"],
                        "ret":t1_m2["ret"],"ri":ri,
                        "alpha":round(t1_m2["ret"]-ri,2),"filtro":cambio2})

        # M3: ambos
        scores_ambos=([s for s in scores if s["fr1m_ok"] and s["conc_ok"]] or
                      [s for s in scores if s["fr1m_ok"]] or
                      [s for s in scores if s["conc_ok"]] or scores)
        t1_m3=scores_ambos[0]; cambio3=(t1_m3["sym"]!=t1["sym"])
        if cambio3: filtro_ambos+=1
        snaps_m3.append({"date":ed.isoformat(),"year":y,"sym":t1_m3["sym"],
                        "ret":t1_m3["ret"],"ri":ri,
                        "alpha":round(t1_m3["ret"]-ri,2),"filtro":cambio3})

    if not snaps_m0: print("ERROR sin señales"); return

    n=len(snaps_m0)
    print(f"\n  Filtro A (fuerza relativa 1M): {filtro1_meses}/{n} meses ({round(filtro1_meses/n*100,1)}%)")
    print(f"  Filtro B (concentracion):      {filtro2_meses}/{n} meses ({round(filtro2_meses/n*100,1)}%)")
    print(f"  Ambos filtros:                 {filtro_ambos}/{n} meses ({round(filtro_ambos/n*100,1)}%)")

    modelos=[
        ("M0 Factor5 base",           snaps_m0),
        ("M1 Fuerza relativa 1M",     snaps_m1),
        ("M2 Concentracion temporal", snaps_m2),
        ("M3 Ambos filtros",          snaps_m3),
    ]

    print(f"\n{'='*70}")
    print("COMPARACION DE MODELOS")
    print(f"{'='*70}")
    print(f"\n  {'Modelo':30s} {'Alpha':>8} {'Bate%':>6} {'p_NW':>8}  Significancia")
    print(f"  {'-'*68}")

    resultados={}
    for nombre,snaps in modelos:
        am,bate,pv_nw,tstat=calcular_stats(snaps)
        if am is None: continue
        print(f"  {nombre:30s} {am:>+7.3f}% {bate:>5.1f}% {str(pv_nw):>8s}  {sig(pv_nw)}")
        resultados[nombre]={"alpha":am,"bate":bate,"pvalue_nw":pv_nw}

    print(f"\n{'='*70}")
    print("IMPACTO DE CADA FILTRO CUANDO ACTUA")
    print(f"{'='*70}")
    for nombre,snaps,fn in [
        ("M1 Fuerza relativa 1M", snaps_m1, filtro1_meses),
        ("M2 Concentracion",      snaps_m2, filtro2_meses),
        ("M3 Ambos",              snaps_m3, filtro_ambos),
    ]:
        con=[s for s in snaps if s.get("filtro")]
        sin=[s for s in snaps if not s.get("filtro")]
        if con and sin:
            am_con=round(sum(s["alpha"] for s in con)/len(con),2)
            am_sin=round(sum(s["alpha"] for s in sin)/len(sin),2)
            print(f"\n  {nombre}:")
            print(f"    Con filtro activo:  n={len(con):3d} | alpha={am_con:+.2f}%")
            print(f"    Sin cambio:         n={len(sin):3d} | alpha={am_sin:+.2f}%")
            print(f"    -> {'MEJORA' if am_con>am_sin else 'NO mejora'} cuando actua")
            tops=Counter(s["sym"] for s in con)
            print(f"    Sectores elegidos cuando filtro actua:")
            for sym,cnt in tops.most_common(3):
                ss=[s for s in con if s["sym"]==sym]
                sam=round(sum(s["alpha"] for s in ss)/len(ss),2)
                print(f"      {sym:8s} {cnt:3d}x alpha={sam:+.2f}%")

    print(f"\n{'='*70}")
    print("VALIDACION POR MITADES")
    print(f"{'='*70}")
    for nombre,snaps in modelos:
        m1s=[s for s in snaps if datetime.date.fromisoformat(s["date"])<SPLIT_DATE]
        m2s=[s for s in snaps if datetime.date.fromisoformat(s["date"])>=SPLIT_DATE]
        am1,_,pv1,_=calcular_stats(m1s)
        am2,_,pv2,_=calcular_stats(m2s)
        if am1 is None or am2 is None: continue
        print(f"\n  {nombre}:")
        print(f"    Mitad 1 (2017-21): alpha={am1:+.2f}% p_NW={pv1}")
        print(f"    Mitad 2 (2022-26): alpha={am2:+.2f}% p_NW={pv2}")

    out={"fecha":TODAY.isoformat(),"n_senales":len(snaps_m0),
         "filtro1_meses":filtro1_meses,"filtro2_meses":filtro2_meses,
         "concentracion_umbral":CONCENTRACION_UMBRAL,"resultados":resultados}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*70}")
    print("REFERENCIA Factor5: alpha=+3.02% p_NW=0.0483 p_boot=0.003")
    print(f"{'='*70}")
    mejoras=[n for n,r in resultados.items() if r["pvalue_nw"] and r["pvalue_nw"]<0.0483]
    if mejoras:
        print(f"  MEJORAN vs Factor5: {', '.join(mejoras)}")
    else:
        print(f"  Ningun modelo mejora al Factor5")
    print(f"{'='*70}")

if __name__=="__main__":
    main()
