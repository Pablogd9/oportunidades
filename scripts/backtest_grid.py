#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_grid.py — Backtest masivo con cuadricula de 864 combinaciones.

CRITERIOS DE ROBUSTEZ (definidos ANTES de ejecutar):
  Solo se reportan modelos que pasan TODOS simultaneamente:
  1. p_NW global < 0.05
  2. Alpha Mitad 1 > 0%
  3. Alpha Mitad 2 > 0%
  4. Diferencia entre mitades < 2%
  5. p_NW de al menos una mitad < 0.20

Combinaciones:
  Lookback: [6,9,12,18]M | Skip: [0,1,2]M | Peso entrada: [0,0.15,0.30]
  Horizonte: [1,2,3]M | F1 Sharpe: [on,off] | F2 LP inverso: [on,off]
  F3 Cross-sectional: [on,off]
  Total: 4x3x3x3x2x2x2 = 864 combinaciones
"""

import json, math, os, datetime, itertools
from collections import Counter, defaultdict

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

LOOKBACKS   = [6, 9, 12, 18]
SKIPS       = [0, 1, 2]
PESOS_ENT   = [0.0, 0.15, 0.30]
HORIZONTES  = [1, 2, 3]
F1_OPTIONS  = [False, True]
F2_OPTIONS  = [False, True]
F3_OPTIONS  = [False, True]

CRITERIO_P_NW_GLOBAL  = 0.05
CRITERIO_ALPHA_M1     = 0.0
CRITERIO_ALPHA_M2     = 0.0
CRITERIO_CONSISTENCIA = 2.0
CRITERIO_P_NW_MITAD   = 0.20

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

def period_return(p,d,year,month,n_months):
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

def calc_momentum_base(prices,lookback_m,skip_m):
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    lb_d=int(lookback_m*21); sk_d=int(skip_m*21)
    min_needed=lb_d+sk_d+1
    if n<min_needed: return None
    start_idx=-(lb_d+sk_d); end_idx=-(sk_d) if sk_d>0 else -1
    m=ret_range(pw,start_idx,end_idx)
    if m is None: return None
    mn=m/(vol/20.0)
    hist=[]
    for i in range(min_needed,min(n,min_needed+500)):
        pc=pw[:n-i]
        if len(pc)>=min_needed:
            r=ret_range(pc,start_idx,end_idx)
            if r is not None:
                hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return pct_hist(mn,hist)

def calc_entrada(prices):
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw)
    if n<252: return 50.0
    vol=vol_std(pw,min(252,n-1))
    max_52w=max(pw[-252:])
    if max_52w<=0: return 50.0
    dd=(pw[-1]/max_52w-1)*100; dd_norm=dd/(vol/20.0)
    hist=[]
    for i in range(252,min(n,756)):
        pc=pw[:n-i]
        if len(pc)>=252:
            mx=max(pc[-252:])
            if mx>0: hist.append(((pc[-1]/mx-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return round(100-pct_hist(dd_norm,hist),1)

def calc_sharpe_momentum(prices,lookback_m,skip_m):
    """F1: Sharpe del momentum — consistencia de la subida."""
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw)
    lb_d=int(lookback_m*21); sk_d=int(skip_m*21)
    min_needed=lb_d+sk_d+1
    if n<min_needed: return 50.0
    start_idx=-(lb_d+sk_d); end_idx=-(sk_d) if sk_d>0 else -1
    ret=ret_range(pw,start_idx,end_idx)
    if ret is None: return 50.0
    if end_idx==-1:
        periodo=pw[n+start_idx:]
    else:
        periodo=pw[n+start_idx:n+end_idx+1]
    if len(periodo)<5: return 50.0
    vol_p=vol_std(periodo,len(periodo)-1)
    if vol_p<=0: return 50.0
    sharpe=ret/vol_p*100
    hist=[]
    for i in range(min_needed,min(n,min_needed+500)):
        pc=pw[:n-i]
        if len(pc)>=min_needed:
            r=ret_range(pc,start_idx,end_idx)
            if r is None: continue
            if end_idx==-1: pp=pc[len(pc)+start_idx:]
            else: pp=pc[len(pc)+start_idx:len(pc)+end_idx+1]
            if len(pp)<5: continue
            vp=vol_std(pp,len(pp)-1)
            if vp>0: hist.append(r/vp*100)
    return pct_hist(sharpe,hist)

def calc_momentum_lp_inverso(prices):
    """F2: Penaliza sectores con retorno 3A muy alto (riesgo reversion secular)."""
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); lb_3y=int(3*252)
    if n<lb_3y+1: return 50.0
    ret_3y=ret_range(pw,-lb_3y,-1)
    if ret_3y is None: return 50.0
    vol=vol_std(pw,min(252,n-1))
    ret_3y_norm=ret_3y/(vol/20.0)
    hist=[]
    for i in range(lb_3y,min(n,lb_3y+500)):
        pc=pw[:n-i]
        if len(pc)>=lb_3y:
            r=ret_range(pc,-lb_3y,-1)
            if r is not None:
                hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pct=pct_hist(ret_3y_norm,hist)
    return round(100-pct,1)  # invertido

def calc_cross_sectional(prices,all_prices_universe,lookback_m,skip_m):
    """F3: Percentil del momentum de este ETF vs todos los demas en este momento."""
    lb_d=int(lookback_m*21); sk_d=int(skip_m*21)
    min_needed=lb_d+sk_d+1
    if len(prices)<min_needed: return 50.0
    start_idx=-(lb_d+sk_d); end_idx=-(sk_d) if sk_d>0 else -1
    vol=vol_std(prices,min(252,len(prices)-1))
    ret_self=ret_range(prices,start_idx,end_idx)
    if ret_self is None: return 50.0
    ret_self_norm=ret_self/(vol/20.0)
    all_rets=[]
    for op in all_prices_universe:
        if len(op)<min_needed: continue
        v=vol_std(op,min(252,len(op)-1))
        r=ret_range(op,start_idx,end_idx)
        if r is not None and v>0: all_rets.append(r/(v/20.0))
    if not all_rets: return 50.0
    return pct_hist(ret_self_norm,all_rets)

def calc_score_combinado(mom,entrada,sharpe,lp_inv,cs,pe,f1,f2,f3):
    if mom is None: return None
    extras=[]; peso_extra=0
    if pe>0: extras.append((entrada,pe)); peso_extra+=pe
    if f1: extras.append((sharpe,0.15)); peso_extra+=0.15
    if f2: extras.append((lp_inv,0.15)); peso_extra+=0.15
    if f3: extras.append((cs,0.15)); peso_extra+=0.15
    peso_mom=max(0.40,1.0-peso_extra)
    score=mom*peso_mom
    for val,peso in extras: score+=val*peso
    return round(score,1)

def main():
    print("="*75)
    print("BACKTEST GRID — 864 combinaciones con criterios de robustez")
    print(f"Fecha: {TODAY}")
    print(f"Criterios: p_NW<{CRITERIO_P_NW_GLOBAL} | ambas mitades>0 | diff<{CRITERIO_CONSISTENCIA}%")
    print("="*75)

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
    if not etf_data: print("ERROR sin datos"); return

    starts=sorted([datetime.date.fromisoformat(d["dates"][0]) for d in etf_data.values()])
    idx=min(int(len(starts)*0.75),len(starts)-1)
    bt_start=datetime.date(starts[idx].year+WINDOW_YEARS,starts[idx].month,1)

    months=[]; dt=bt_start
    while dt<=TODAY.replace(day=1):
        months.append((dt.year,dt.month))
        dt=datetime.date(dt.year+1,1,1) if dt.month==12 else datetime.date(dt.year,dt.month+1,1)

    print(f"\nDesde {bt_start} | {len(months)} meses")
    print("\nPre-calculando datos por mes...")

    month_data={}
    for y,m in months:
        ed=datetime.date(y,m,1)
        etfs_mes={}; all_prices=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            if len(pt)<200: continue
            it=prices_up_to(iwda_p,iwda_d,ed)
            all_prices.append(pt)
            etfs_mes[sym]={"pt":pt,"it":it,
                          "entrada":calc_entrada(pt),
                          "lp_inv":calc_momentum_lp_inverso(pt)}
        month_data[(y,m)]={"ed":ed,"etfs":etfs_mes,"all_prices":all_prices}

    print(f"Pre-calculo listo para {len(month_data)} meses")

    combos=list(itertools.product(LOOKBACKS,SKIPS,PESOS_ENT,HORIZONTES,
                                   F1_OPTIONS,F2_OPTIONS,F3_OPTIONS))
    print(f"\nEvaluando {len(combos)} combinaciones (20-30 min)...\n")

    resultados_robustos=[]; total_ev=0; total_rob=0

    for lb,sk,pe,hz,f1,f2,f3 in combos:
        total_ev+=1
        if total_ev%100==0:
            print(f"  {total_ev}/{len(combos)} evaluadas | {total_rob} robustas")

        months_v=[m for m in months
                  if datetime.date(m[0],m[1],1)<=TODAY.replace(day=1)-datetime.timedelta(days=hz*32)]
        if len(months_v)<30: continue

        snaps=[]; snaps_m1=[]; snaps_m2=[]

        for y,m in months_v:
            if (y,m) not in month_data: continue
            md=month_data[(y,m)]
            ed=md["ed"]; etfs=md["etfs"]; all_prices=md["all_prices"]
            ri=period_return(iwda_p,iwda_d,y,m,hz)
            if ri is None: continue

            scores=[]
            for sym,d in etfs.items():
                pt=d["pt"]
                lb_d=int(lb*21); sk_d=int(sk*21)
                if len(pt)<lb_d+sk_d+2: continue
                mom=calc_momentum_base(pt,lb,sk)
                if mom is None: continue
                sharpe=calc_sharpe_momentum(pt,lb,sk) if f1 else 50.0
                lp_inv=d["lp_inv"] if f2 else 50.0
                cs=calc_cross_sectional(pt,all_prices,lb,sk) if f3 else 50.0
                entrada=d["entrada"] if pe>0 else 50.0
                sc=calc_score_combinado(mom,entrada,sharpe,lp_inv,cs,pe,f1,f2,f3)
                if sc is None: continue
                r=period_return(etf_data[sym]["prices"],etf_data[sym]["dates"],y,m,hz)
                if r is None: continue
                scores.append({"sym":sym,"score":sc,"ret":r,"alpha":round(r-ri,2)})

            if not scores: continue
            scores.sort(key=lambda x:-x["score"])
            t1=scores[0]
            snap={"date":ed.isoformat(),"year":y,"sym":t1["sym"],"alpha":t1["alpha"]}
            snaps.append(snap)
            if ed<SPLIT_DATE: snaps_m1.append(snap)
            else: snaps_m2.append(snap)

        if len(snaps)<20: continue

        def stats(ss):
            if not ss: return None,None
            als=[s["alpha"] for s in ss]
            am=round(sum(als)/len(als),3)
            pv,_=newey_west_pvalue(als,NW_LAGS)
            return am,pv

        am_g,pv_g=stats(snaps)
        am_m1,pv_m1=stats(snaps_m1)
        am_m2,pv_m2=stats(snaps_m2)
        if am_g is None or pv_g is None: continue

        am_m1=am_m1 or 0; am_m2=am_m2 or 0
        pv_m1=pv_m1 or 1.0; pv_m2=pv_m2 or 1.0

        pasa=(pv_g<CRITERIO_P_NW_GLOBAL and
              am_m1>CRITERIO_ALPHA_M1 and
              am_m2>CRITERIO_ALPHA_M2 and
              abs(am_m1-am_m2)<CRITERIO_CONSISTENCIA and
              min(pv_m1,pv_m2)<CRITERIO_P_NW_MITAD)

        if pasa:
            total_rob+=1
            resultados_robustos.append({
                "lookback":lb,"skip":sk,"peso_entrada":pe,
                "horizonte":hz,"f1_sharpe":f1,"f2_lp_inv":f2,"f3_cross":f3,
                "n":len(snaps),"alpha_global":am_g,"pvalue_nw":pv_g,
                "alpha_m1":am_m1,"pvalue_m1":pv_m1,
                "alpha_m2":am_m2,"pvalue_m2":pv_m2,
                "consistencia":round(abs(am_m1-am_m2),3),
            })

    resultados_robustos.sort(key=lambda x:x["pvalue_nw"])

    print(f"\n{'='*75}")
    print(f"RESULTADOS — {total_rob} modelos robustos de {total_ev} evaluados")
    print(f"{'='*75}")

    if not resultados_robustos:
        print("\nNINGUN modelo pasa todos los criterios.")
        print("B3 (skip-1+entrada, p_NW=0.0447) sigue siendo el mejor.")
    else:
        print(f"\n{'Rank':4} {'LB':3} {'SK':3} {'PEnt':5} {'HZ':3} "
              f"{'F1':3} {'F2':3} {'F3':3} {'Alpha':>8} {'p_NW':>7} "
              f"{'M1':>7} {'M2':>7} {'Diff':>6} {'N':>4}")
        print("-"*80)
        for i,r in enumerate(resultados_robustos[:20],1):
            f1s="✓" if r["f1_sharpe"] else "✗"
            f2s="✓" if r["f2_lp_inv"] else "✗"
            f3s="✓" if r["f3_cross"]  else "✗"
            print(f"#{i:3d} {r['lookback']:3d} {r['skip']:3d} {r['peso_entrada']:5.2f} "
                  f"{r['horizonte']:3d} {f1s:3s} {f2s:3s} {f3s:3s} "
                  f"{r['alpha_global']:>+7.2f}% {r['pvalue_nw']:>7.4f} "
                  f"{r['alpha_m1']:>+6.2f}% {r['alpha_m2']:>+6.2f}% "
                  f"{r['consistencia']:>5.2f}% {r['n']:>4d}")

        best=resultados_robustos[0]
        print(f"\nMEJOR MODELO:")
        print(f"  Lookback:{best['lookback']}M Skip:{best['skip']}M "
              f"PesoEnt:{best['peso_entrada']} Horizonte:{best['horizonte']}M")
        print(f"  F1 Sharpe:{best['f1_sharpe']} F2 LP_inv:{best['f2_lp_inv']} "
              f"F3 Cross:{best['f3_cross']}")
        print(f"  Alpha:{best['alpha_global']:+.3f}% p_NW:{best['pvalue_nw']}")
        print(f"  M1:{best['alpha_m1']:+.3f}% M2:{best['alpha_m2']:+.3f}% "
              f"Diff:{best['consistencia']:.3f}%")

        print(f"\nCOMPARACION CON B3: alpha=+3.44% p_NW=0.0447 M1=+3.43% M2=+3.46%")
        if best["pvalue_nw"]<0.0447:
            print(f"  -> MEJORA A B3")
        else:
            print(f"  -> B3 sigue siendo el mejor modelo robusto")

        n_top=min(20,len(resultados_robustos)); top20=resultados_robustos[:n_top]
        print(f"\nFRECUENCIA EN TOP {n_top} ROBUSTOS:")
        print(f"  F1 Sharpe:    {sum(1 for r in top20 if r['f1_sharpe'])}/{n_top}")
        print(f"  F2 LP inverso:{sum(1 for r in top20 if r['f2_lp_inv'])}/{n_top}")
        print(f"  F3 Cross-sec: {sum(1 for r in top20 if r['f3_cross'])}/{n_top}")
        lbs=Counter(r["lookback"] for r in top20)
        sks=Counter(r["skip"] for r in top20)
        hzs=Counter(r["horizonte"] for r in top20)
        print(f"  Lookbacks:    {dict(lbs.most_common(3))}")
        print(f"  Skips:        {dict(sks.most_common(3))}")
        print(f"  Horizontes:   {dict(hzs.most_common(3))}")

    out={"fecha":TODAY.isoformat(),"total_evaluadas":total_ev,
         "total_robustas":total_rob,
         "criterios":{"p_nw_global":CRITERIO_P_NW_GLOBAL,
                      "alpha_m1_min":CRITERIO_ALPHA_M1,
                      "alpha_m2_min":CRITERIO_ALPHA_M2,
                      "consistencia_max":CRITERIO_CONSISTENCIA,
                      "p_nw_mitad_min":CRITERIO_P_NW_MITAD},
         "modelos_robustos":resultados_robustos[:50]}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\nTotal evaluadas:{total_ev} | Robustas:{total_rob}")
    print(f"{'='*75}")

if __name__=="__main__":
    main()
