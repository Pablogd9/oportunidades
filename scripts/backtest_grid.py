#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_grid.py v2 — Grid optimizado: 128 combinaciones en ~15 minutos.

PARAMETROS FIJOS (ya validados):
  Horizonte: 3 meses
  Skip: 1 mes

PARAMETROS A EXPLORAR:
  Lookback: [6,9,12,18] | Peso entrada: [0,0.15,0.30,0.45]
  F1 Sharpe: [on,off] | F2 LP inverso: [on,off] | F3 Cross: [on,off]
  Total: 4x4x2x2x2 = 128 combinaciones

CRITERIOS DE ROBUSTEZ:
  1. p_NW global < 0.05
  2. Alpha M1 > 0% | Alpha M2 > 0%
  3. Diferencia entre mitades < 2%
  4. p_NW de al menos una mitad < 0.20
"""

import json, math, os, datetime, itertools
from collections import Counter

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest_grid.json")
TODAY       = datetime.date.today()
WINDOW_YEARS= 5
NW_LAGS     = 2

BACKTEST_UNIVERSE = [
    "SMH","IBB","ITA","IGV","VHT","PHO",
    "IHI","ICLN","GRID","COPX","LIT","INDA",
    "ROBO","CIBR","PAVE",
]
BENCHMARK  = "IWDA.AS"
SPLIT_DATE = datetime.date(2022, 1, 1)
HORIZONTE  = 3
SKIP       = 1
LOOKBACKS  = [6, 9, 12, 18]
PESOS_ENT  = [0.0, 0.15, 0.30, 0.45]
F1_OPTIONS = [False, True]
F2_OPTIONS = [False, True]
F3_OPTIONS = [False, True]
CRITERIO_P_NW     = 0.05
CRITERIO_ALPHA_M1 = 0.0
CRITERIO_ALPHA_M2 = 0.0
CRITERIO_DIFF     = 2.0
CRITERIO_P_MITAD  = 0.20

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

def calc_momentum(prices,lb,sk=1):
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    lb_d=int(lb*21); sk_d=int(sk*21)
    min_n=lb_d+sk_d+1
    if n<min_n: return None
    s=-(lb_d+sk_d); e=-sk_d if sk_d>0 else -1
    m=ret_range(pw,s,e)
    if m is None: return None
    mn=m/(vol/20.0)
    hist=[]
    for i in range(min_n,min(n,min_n+400)):
        pc=pw[:n-i]
        if len(pc)>=min_n:
            r=ret_range(pc,s,e)
            if r is not None:
                hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return pct_hist(mn,hist)

def calc_entrada(prices):
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw)
    if n<252: return 50.0
    vol=vol_std(pw,min(252,n-1))
    mx=max(pw[-252:])
    if mx<=0: return 50.0
    dd=(pw[-1]/mx-1)*100; dd_n=dd/(vol/20.0)
    hist=[]
    for i in range(252,min(n,600)):
        pc=pw[:n-i]
        if len(pc)>=252:
            m=max(pc[-252:])
            if m>0: hist.append(((pc[-1]/m-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return round(100-pct_hist(dd_n,hist),1)

def calc_sharpe(prices,lb,sk=1):
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw)
    lb_d=int(lb*21); sk_d=int(sk*21)
    min_n=lb_d+sk_d+1
    if n<min_n: return 50.0
    s=-(lb_d+sk_d); e=-sk_d if sk_d>0 else -1
    ret=ret_range(pw,s,e)
    if ret is None: return 50.0
    periodo=pw[n+s:n+e+1] if e<-1 else pw[n+s:]
    if len(periodo)<5: return 50.0
    vp=vol_std(periodo,len(periodo)-1)
    if vp<=0: return 50.0
    sharpe=ret/vp*100
    hist=[]
    for i in range(min_n,min(n,min_n+400)):
        pc=pw[:n-i]
        if len(pc)>=min_n:
            r=ret_range(pc,s,e)
            if r is None: continue
            pp=pc[len(pc)+s:len(pc)+e+1] if e<-1 else pc[len(pc)+s:]
            if len(pp)<5: continue
            vpp=vol_std(pp,len(pp)-1)
            if vpp>0: hist.append(r/vpp*100)
    return pct_hist(sharpe,hist)

def calc_lp_inverso(prices):
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); lb=int(3*252)
    if n<lb+1: return 50.0
    r3=ret_range(pw,-lb,-1)
    if r3 is None: return 50.0
    vol=vol_std(pw,min(252,n-1))
    r3n=r3/(vol/20.0)
    hist=[]
    for i in range(lb,min(n,lb+400)):
        pc=pw[:n-i]
        if len(pc)>=lb:
            r=ret_range(pc,-lb,-1)
            if r is not None:
                hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return round(100-pct_hist(r3n,hist),1)

def calc_cross(prices,all_prices,lb,sk=1):
    lb_d=int(lb*21); sk_d=int(sk*21)
    min_n=lb_d+sk_d+1
    if len(prices)<min_n: return 50.0
    s=-(lb_d+sk_d); e=-sk_d if sk_d>0 else -1
    vol=vol_std(prices,min(252,len(prices)-1))
    r=ret_range(prices,s,e)
    if r is None: return 50.0
    rn=r/(vol/20.0)
    others=[]
    for op in all_prices:
        if len(op)<min_n: continue
        v=vol_std(op,min(252,len(op)-1))
        ro=ret_range(op,s,e)
        if ro is not None and v>0: others.append(ro/(v/20.0))
    return pct_hist(rn,others) if others else 50.0

def score_final(mom,entrada,sharpe,lp_inv,cs,pe,f1,f2,f3):
    if mom is None: return None
    extras=[]; pe_total=0
    if pe>0: extras.append((entrada,pe)); pe_total+=pe
    if f1: extras.append((sharpe,0.15)); pe_total+=0.15
    if f2: extras.append((lp_inv,0.15)); pe_total+=0.15
    if f3: extras.append((cs,0.15)); pe_total+=0.15
    w_mom=max(0.40,1.0-pe_total)
    sc=mom*w_mom
    for val,w in extras: sc+=val*w
    return round(sc,1)

def stats(snaps):
    if not snaps: return None,None
    als=[s["alpha"] for s in snaps]
    am=round(sum(als)/len(als),3)
    pv,_=newey_west_pvalue(als,NW_LAGS)
    return am,pv

def main():
    print("="*70)
    print("BACKTEST GRID v2 — 128 combinaciones optimizadas")
    print(f"Fecha: {TODAY} | Horizonte: {HORIZONTE}M fijo | Skip: {SKIP}M fijo")
    print(f"Criterios: p_NW<{CRITERIO_P_NW} | ambas mitades>0 | diff<{CRITERIO_DIFF}%")
    print("="*70)

    print("\nCargando datos...")
    etf_data={}
    for sym in BACKTEST_UNIVERSE:
        p,d=load_from_cache(sym)
        if not p or len(p)<500:
            print(f"  {sym:8s} insuficiente"); continue
        etf_data[sym]={"prices":p,"dates":d}
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
            if datetime.date(m[0],m[1],1)<=TODAY.replace(day=1)-datetime.timedelta(days=HORIZONTE*32)]
    print(f"\nDesde {bt_start} | {len(months)} señales validas")

    print("\nPre-calculando factores fijos por mes...")
    month_data={}
    for y,m in months:
        ed=datetime.date(y,m,1)
        etfs={}; all_prices=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            if len(pt)<300: continue
            all_prices.append(pt)
            r=period_return(data["prices"],data["dates"],y,m,HORIZONTE)
            ri=period_return(iwda_p,iwda_d,y,m,HORIZONTE)
            if r is None or ri is None: continue
            etfs[sym]={"pt":pt,"r":r,"alpha":round(r-ri,2),
                      "entrada":calc_entrada(pt),
                      "lp_inv":calc_lp_inverso(pt)}
        if etfs:
            month_data[(y,m)]={"ed":ed,"etfs":etfs,"all_prices":all_prices,
                               "ri":period_return(iwda_p,iwda_d,y,m,HORIZONTE)}
    print(f"Pre-calculo listo: {len(month_data)} meses")

    combos=list(itertools.product(LOOKBACKS,PESOS_ENT,F1_OPTIONS,F2_OPTIONS,F3_OPTIONS))
    print(f"\nEvaluando {len(combos)} combinaciones...")

    resultados=[]; n_ev=0; n_rob=0

    for lb,pe,f1,f2,f3 in combos:
        n_ev+=1
        if n_ev%20==0:
            print(f"  {n_ev}/{len(combos)} | Robustas: {n_rob}")

        snaps=[]; snaps_m1=[]; snaps_m2=[]
        lb_d=int(lb*21); sk_d=int(SKIP*21)
        min_n=lb_d+sk_d+2

        for y,m in months:
            if (y,m) not in month_data: continue
            md=month_data[(y,m)]
            ed=md["ed"]; etfs=md["etfs"]; all_prices=md["all_prices"]
            ri=md["ri"]
            if ri is None: continue

            scores=[]
            for sym,d in etfs.items():
                pt=d["pt"]
                if len(pt)<min_n: continue
                mom=calc_momentum(pt,lb,SKIP)
                if mom is None: continue
                sharpe=calc_sharpe(pt,lb,SKIP) if f1 else 50.0
                lp_inv=d["lp_inv"] if f2 else 50.0
                cs=calc_cross(pt,all_prices,lb,SKIP) if f3 else 50.0
                entrada=d["entrada"] if pe>0 else 50.0
                sc=score_final(mom,entrada,sharpe,lp_inv,cs,pe,f1,f2,f3)
                if sc is None: continue
                scores.append({"sym":sym,"score":sc,"alpha":d["alpha"]})

            if not scores: continue
            scores.sort(key=lambda x:-x["score"])
            t1=scores[0]
            snap={"date":ed.isoformat(),"year":y,"sym":t1["sym"],"alpha":t1["alpha"]}
            snaps.append(snap)
            if ed<SPLIT_DATE: snaps_m1.append(snap)
            else: snaps_m2.append(snap)

        if len(snaps)<20: continue

        am_g,pv_g=stats(snaps)
        am_m1,pv_m1=stats(snaps_m1)
        am_m2,pv_m2=stats(snaps_m2)
        if am_g is None or pv_g is None: continue

        am_m1=am_m1 or 0; am_m2=am_m2 or 0
        pv_m1=pv_m1 or 1.0; pv_m2=pv_m2 or 1.0

        pasa=(pv_g<CRITERIO_P_NW and
              am_m1>CRITERIO_ALPHA_M1 and
              am_m2>CRITERIO_ALPHA_M2 and
              abs(am_m1-am_m2)<CRITERIO_DIFF and
              min(pv_m1,pv_m2)<CRITERIO_P_MITAD)

        if pasa:
            n_rob+=1
            resultados.append({
                "lookback":lb,"skip":SKIP,"peso_entrada":pe,
                "horizonte":HORIZONTE,
                "f1_sharpe":f1,"f2_lp_inv":f2,"f3_cross":f3,
                "n":len(snaps),"alpha":am_g,"pvalue_nw":pv_g,
                "alpha_m1":am_m1,"pvalue_m1":pv_m1,
                "alpha_m2":am_m2,"pvalue_m2":pv_m2,
                "consistencia":round(abs(am_m1-am_m2),3),
            })

    resultados.sort(key=lambda x:x["pvalue_nw"])

    print(f"\n{'='*70}")
    print(f"RESULTADOS — {n_rob} modelos robustos de {n_ev} evaluados")
    print(f"{'='*70}")

    if not resultados:
        print("\nNINGUN modelo pasa todos los criterios.")
        print("B3 (LB=12 SK=1 PE=0.30 HZ=3M, p_NW=0.0447) sigue siendo el mejor.")
    else:
        print(f"\n{'Rk':3} {'LB':3} {'PE':5} {'F1':3} {'F2':3} {'F3':3} "
              f"{'Alpha':>8} {'p_NW':>7} {'M1':>7} {'M2':>7} {'Diff':>6}")
        print("-"*65)
        for i,r in enumerate(resultados[:25],1):
            f1s="✓" if r["f1_sharpe"] else "✗"
            f2s="✓" if r["f2_lp_inv"] else "✗"
            f3s="✓" if r["f3_cross"]  else "✗"
            mejor=" ←" if r["pvalue_nw"]<0.0447 else ""
            print(f"#{i:2d} {r['lookback']:3d} {r['peso_entrada']:5.2f} "
                  f"{f1s:3s} {f2s:3s} {f3s:3s} "
                  f"{r['alpha']:>+7.3f}% {r['pvalue_nw']:>7.4f} "
                  f"{r['alpha_m1']:>+6.3f}% {r['alpha_m2']:>+6.3f}% "
                  f"{r['consistencia']:>5.3f}%{mejor}")

        best=resultados[0]
        print(f"\nMEJOR MODELO:")
        print(f"  LB={best['lookback']}M SK={best['skip']}M "
              f"PE={best['peso_entrada']} HZ={best['horizonte']}M")
        print(f"  F1={best['f1_sharpe']} F2={best['f2_lp_inv']} F3={best['f3_cross']}")
        print(f"  Alpha={best['alpha']:+.3f}% p_NW={best['pvalue_nw']}")
        print(f"  M1={best['alpha_m1']:+.3f}% M2={best['alpha_m2']:+.3f}% "
              f"Diff={best['consistencia']:.3f}%")

        print(f"\nCOMPARACION CON B3: alpha=+3.44% p_NW=0.0447 M1=+3.43% M2=+3.46%")
        if best["pvalue_nw"]<0.0447:
            print(f"  -> MEJORA A B3")
        else:
            print(f"  -> B3 sigue siendo el mejor modelo robusto")

        n_top=min(25,len(resultados)); top=resultados[:n_top]
        lbs=Counter(r["lookback"] for r in top)
        pes=Counter(r["peso_entrada"] for r in top)
        print(f"\nANALISIS DE AGRUPACION (top {n_top} robustos):")
        print(f"  Lookbacks:     {dict(sorted(lbs.items()))}")
        print(f"  Pesos entrada: {dict(sorted(pes.items()))}")
        print(f"  F1 Sharpe:     {sum(1 for r in top if r['f1_sharpe'])}/{n_top} activo")
        print(f"  F2 LP inverso: {sum(1 for r in top if r['f2_lp_inv'])}/{n_top} activo")
        print(f"  F3 Cross-sec:  {sum(1 for r in top if r['f3_cross'])}/{n_top} activo")

        alphas_top=[r["alpha"] for r in top]
        am_min=min(alphas_top); am_max=max(alphas_top)
        print(f"\n  Rango alpha: {am_min:+.2f}% a {am_max:+.2f}%")
        if am_max-am_min<1.0:
            print(f"  -> Rango estrecho: alpha ESTABLE — buena señal sin overfitting")
        elif am_max-am_min<2.0:
            print(f"  -> Rango moderado: cierta variabilidad pero aceptable")
        else:
            print(f"  -> Rango amplio: posible overfitting en algunos modelos")

    out={"fecha":TODAY.isoformat(),"total_evaluadas":n_ev,"total_robustas":n_rob,
         "parametros_fijos":{"horizonte":HORIZONTE,"skip":SKIP},
         "criterios":{"p_nw":CRITERIO_P_NW,"alpha_m1":CRITERIO_ALPHA_M1,
                      "alpha_m2":CRITERIO_ALPHA_M2,"diff":CRITERIO_DIFF,
                      "p_mitad":CRITERIO_P_MITAD},
         "modelos_robustos":resultados[:50]}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\nTotal: {n_ev} evaluadas | {n_rob} robustas")
    print(f"{'='*70}")

if __name__=="__main__":
    main()
