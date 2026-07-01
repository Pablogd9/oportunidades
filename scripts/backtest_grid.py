#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_grid.py v4 — Grid completo + analisis exhaustivo.

PARAMETROS A EXPLORAR (256 combinaciones):
  Lookback: [6,9,12,18] | Skip: [0,1] | Peso entrada: [0,0.15,0.30,0.45]
  F1 Sharpe: [on,off] | F2 LP inverso: [on,off] | F3 Cross: [on,off]

CRITERIOS DE ROBUSTEZ:
  1. p_NW global < 0.05
  2. Alpha M1 > 0% Y Alpha M2 > 0%
  3. Diferencia entre mitades < 2%
  4. p_NW de al menos una mitad < 0.20

ANALISIS ADICIONAL del mejor modelo:
  A. Alpha por año — en que periodos falla
  B. Estabilidad del ranking — consistencia del score entre meses
  C. Score vs rentabilidad — quintiles + Spearman
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
HORIZONTE  = 3
LOOKBACKS  = [6, 9, 12, 18]
SKIPS      = [0, 1]
PESOS_ENT  = [0.0, 0.15, 0.30, 0.45]
F1_OPTIONS = [False, True]
F2_OPTIONS = [False, True]
F3_OPTIONS = [False, True]
CRITERIO_P_NW    = 0.05
CRITERIO_ALPHA   = 0.0
CRITERIO_DIFF    = 2.0
CRITERIO_P_MITAD = 0.20

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

def spearman(xs,ys):
    n=len(xs)
    if n<5: return None
    xr={v:i for i,v in enumerate(sorted(xs))}
    yr={v:i for i,v in enumerate(sorted(ys))}
    sr=[xr[x] for x in xs]; tr=[yr[y] for y in ys]
    mx=sum(sr)/n; my=sum(tr)/n
    cov=sum((sr[i]-mx)*(tr[i]-my) for i in range(n))/n
    sx=math.sqrt(sum((x-mx)**2 for x in sr)/n)
    sy=math.sqrt(sum((y-my)**2 for y in tr)/n)
    return round(cov/(sx*sy),3) if sx>0 and sy>0 else 0

def calc_mom(pw,lb,sk):
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    lb_d=int(lb*21); sk_d=int(sk*21)
    min_n=lb_d+sk_d+1
    if n<min_n: return None
    s=-(lb_d+sk_d); e=-sk_d if sk_d>0 else -1
    m=ret_range(pw,s,e)
    if m is None: return None
    mn=m/(vol/20.0)
    hist=[]
    for i in range(min_n,min(n,min_n+350)):
        pc=pw[:n-i]
        if len(pc)>=min_n:
            r=ret_range(pc,s,e)
            if r is not None:
                hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return pct_hist(mn,hist)

def calc_entrada(pw):
    n=len(pw)
    if n<252: return 50.0
    vol=vol_std(pw,min(252,n-1))
    mx=max(pw[-252:])
    if mx<=0: return 50.0
    dd=(pw[-1]/mx-1)*100; dd_n=dd/(vol/20.0)
    hist=[]
    for i in range(252,min(n,550)):
        pc=pw[:n-i]
        if len(pc)>=252:
            m=max(pc[-252:])
            if m>0: hist.append(((pc[-1]/m-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return round(100-pct_hist(dd_n,hist),1)

def calc_sharpe(pw,lb,sk):
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
    for i in range(min_n,min(n,min_n+350)):
        pc=pw[:n-i]
        if len(pc)>=min_n:
            r=ret_range(pc,s,e)
            if r is None: continue
            pp=pc[len(pc)+s:len(pc)+e+1] if e<-1 else pc[len(pc)+s:]
            if len(pp)<5: continue
            vpp=vol_std(pp,len(pp)-1)
            if vpp>0: hist.append(r/vpp*100)
    return pct_hist(sharpe,hist)

def calc_lp_inv(pw):
    n=len(pw); lb=int(3*252)
    if n<lb+1: return 50.0
    r3=ret_range(pw,-lb,-1)
    if r3 is None: return 50.0
    vol=vol_std(pw,min(252,n-1))
    r3n=r3/(vol/20.0)
    hist=[]
    for i in range(lb,min(n,lb+350)):
        pc=pw[:n-i]
        if len(pc)>=lb:
            r=ret_range(pc,-lb,-1)
            if r is not None:
                hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return round(100-pct_hist(r3n,hist),1)

def calc_cross(pw,all_pw,lb,sk):
    lb_d=int(lb*21); sk_d=int(sk*21)
    min_n=lb_d+sk_d+1
    if len(pw)<min_n: return 50.0
    s=-(lb_d+sk_d); e=-sk_d if sk_d>0 else -1
    vol=vol_std(pw,min(252,len(pw)-1))
    r=ret_range(pw,s,e)
    if r is None: return 50.0
    rn=r/(vol/20.0)
    others=[]
    for op in all_pw:
        if len(op)<min_n: continue
        v=vol_std(op,min(252,len(op)-1))
        ro=ret_range(op,s,e)
        if ro is not None and v>0: others.append(ro/(v/20.0))
    return pct_hist(rn,others) if others else 50.0

def stats(snaps):
    if not snaps: return None,None
    als=[s["alpha"] for s in snaps]
    am=round(sum(als)/len(als),3)
    pv,_=newey_west_pvalue(als,NW_LAGS)
    return am,pv

def analisis_adicional(snaps_full, all_obs, label):
    print(f"\n{'='*70}")
    print(f"ANALISIS ADICIONAL — {label}")
    print(f"{'='*70}")

    # A. Alpha por año
    print(f"\nA. ALPHA POR AÑO")
    print(f"  {'Año':6s} {'N':>4} {'Alpha':>8} {'Bate%':>7} {'Nota'}")
    print(f"  {'-'*50}")
    by_year=defaultdict(list)
    for s in snaps_full: by_year[s["year"]].append(s)
    for yr in sorted(by_year.keys()):
        ss=by_year[yr]
        als=[s["alpha"] for s in ss]
        am=round(sum(als)/len(als),2)
        bate=round(sum(1 for a in als if a>0)/len(als)*100,0)
        nota=""
        if am<-3: nota=" ← MAL AÑO"
        elif am>8: nota=" ← MUY BUEN AÑO"
        elif am<0: nota=" ← negativo"
        print(f"  {yr:6d} {len(ss):>4} {am:>+7.2f}% {bate:>6.0f}%{nota}")

    # B. Estabilidad del ranking
    print(f"\nB. ESTABILIDAD DEL RANKING")
    top1_syms=[s["sym"] for s in snaps_full]
    scores_top=[s.get("top1_score",50) for s in snaps_full]

    if len(scores_top)>10:
        lag1=spearman(scores_top[:-1],scores_top[1:])
        print(f"  Autocorrelacion score Top1 (lag 1 mes): {lag1}")
        if lag1 and lag1>0.5: print(f"  → Score MUY ESTABLE mes a mes")
        elif lag1 and lag1>0.3: print(f"  → Score MODERADAMENTE ESTABLE")
        elif lag1 and lag1>0.1: print(f"  → Score POCO ESTABLE")
        else: print(f"  → Score INESTABLE — ranking cambia mucho")

    cambios=sum(1 for i in range(1,len(top1_syms)) if top1_syms[i]!=top1_syms[i-1])
    pct_c=round(cambios/len(top1_syms)*100,1)
    print(f"  Top1 cambia de sector: {cambios}/{len(top1_syms)} meses ({pct_c}%)")

    max_racha=1; racha=1
    for i in range(1,len(top1_syms)):
        if top1_syms[i]==top1_syms[i-1]: racha+=1; max_racha=max(max_racha,racha)
        else: racha=1
    print(f"  Racha maxima mismo sector: {max_racha} meses consecutivos")

    # Que sectores dominan el Top1
    tops=Counter(top1_syms)
    print(f"  Sectores mas elegidos como Top1:")
    for sym,cnt in tops.most_common(5):
        ss=[s for s in snaps_full if s["sym"]==sym]
        am=round(sum(s["alpha"] for s in ss)/len(ss),2)
        print(f"    {sym:8s} {cnt:3d}x alpha={am:+.2f}%")

    # C. Score vs rentabilidad
    print(f"\nC. SCORE VS RENTABILIDAD (todos los ETFs evaluados cada mes)")
    if len(all_obs)>50:
        all_obs_s=sorted(all_obs,key=lambda x:x["score"])
        n=len(all_obs_s); q=n//5
        print(f"  Total observaciones (ETF x mes): {n}")
        print(f"\n  {'Quintil':12s} {'Score':12s} {'N':>5} {'Alpha medio':>12}")
        print(f"  {'-'*46}")
        alphas_q=[]
        for qi in range(5):
            chunk=all_obs_s[qi*q:(qi+1)*q if qi<4 else n]
            scs=[x["score"] for x in chunk]
            als=[x["alpha"] for x in chunk]
            am=round(sum(als)/len(als),3)
            alphas_q.append(am)
            label2="Q1 (peor)" if qi==0 else "Q5 (mejor)" if qi==4 else f"Q{qi+1}"
            print(f"  {label2:12s} {min(scs):4.0f}-{max(scs):4.0f}       {len(chunk):>5} {am:>+11.2f}%")

        all_scs=[x["score"] for x in all_obs]
        all_als=[x["alpha"] for x in all_obs]
        sp=spearman(all_scs,all_als)
        print(f"\n  Correlacion Spearman score→alpha: {sp}")
        if sp and sp>0.15: print(f"  → Score SI predice ordinalmente")
        elif sp and sp>0.05: print(f"  → Prediccion debil pero positiva")
        elif sp and sp>-0.05: print(f"  → Score NO predice ordinalmente")
        else: print(f"  → ALERTA: score predice al reves")

        monotono=all(alphas_q[i]<=alphas_q[i+1] for i in range(4))
        print(f"  Quintiles monotonos (Q1<Q2<Q3<Q4<Q5): {'SI' if monotono else 'NO'}")
    else:
        print(f"  Sin suficientes observaciones")

def main():
    print("="*70)
    print("BACKTEST GRID v4 — Grid completo + analisis exhaustivo")
    print(f"Fecha: {TODAY} | Horizonte: {HORIZONTE}M | 256 combinaciones")
    print(f"Criterios: p_NW<{CRITERIO_P_NW} | ambas>0 | diff<{CRITERIO_DIFF}%")
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
    print(f"\nDesde {bt_start} | {len(months)} señales")

    print("\nPre-calculando scores...")
    pre={}; month_meta={}

    for mi,(y,m) in enumerate(months):
        ed=datetime.date(y,m,1)
        ri=period_return(iwda_p,iwda_d,y,m,HORIZONTE)
        etf_pts={}; all_pw=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            if len(pt)<300: continue
            etf_pts[sym]=pt; all_pw.append(pt)

        entrada_c={}; lp_inv_c={}
        for sym,pt in etf_pts.items():
            wd=WINDOW_YEARS*252
            pw=pt[-wd:] if len(pt)>wd else pt
            entrada_c[sym]=calc_entrada(pw)
            lp_inv_c[sym]=calc_lp_inv(pw)

        month_meta[mi]={"ed":ed,"ri":ri,"etf_pts":etf_pts,
                        "all_pw":all_pw,"entrada":entrada_c,"lp_inv":lp_inv_c}

        for sym,pt in etf_pts.items():
            wd=WINDOW_YEARS*252
            pw=pt[-wd:] if len(pt)>wd else pt
            r=period_return(etf_data[sym]["prices"],etf_data[sym]["dates"],y,m,HORIZONTE)
            if r is None or ri is None: continue
            alpha=round(r-ri,2)
            if sym not in pre: pre[sym]={}
            if mi not in pre[sym]: pre[sym][mi]={}
            for lb in LOOKBACKS:
                for sk in SKIPS:
                    key=(lb,sk)
                    pw2=pt[-(WINDOW_YEARS*252):] if len(pt)>WINDOW_YEARS*252 else pt
                    mom=calc_mom(pw2,lb,sk)
                    sharpe=calc_sharpe(pw2,lb,sk)
                    cross=calc_cross(pw2,all_pw,lb,sk)
                    pre[sym][mi][key]={
                        "mom":mom,"sharpe":sharpe,"cross":cross,
                        "entrada":entrada_c[sym],"lp_inv":lp_inv_c[sym],
                        "alpha":alpha,"ret":r}

        if mi%10==0: print(f"  Mes {mi+1}/{len(months)}...",flush=True)

    print("Pre-calculo listo")

    combos=list(itertools.product(LOOKBACKS,SKIPS,PESOS_ENT,F1_OPTIONS,F2_OPTIONS,F3_OPTIONS))
    print(f"\nEvaluando {len(combos)} combinaciones...")

    resultados=[]; n_ev=0; n_rob=0

    for lb,sk,pe,f1,f2,f3 in combos:
        n_ev+=1
        key=(lb,sk)
        if n_ev%50==0: print(f"  {n_ev}/{len(combos)} | Rob: {n_rob}",flush=True)

        snaps=[]; snaps_m1=[]; snaps_m2=[]

        for mi,(y,m) in enumerate(months):
            md=month_meta[mi]; ed=md["ed"]; ri=md["ri"]
            if ri is None: continue
            scores=[]
            for sym in etf_data:
                if sym not in pre or mi not in pre[sym]: continue
                if key not in pre[sym][mi]: continue
                d=pre[sym][mi][key]
                if d["mom"] is None: continue
                extras=[]; pe_t=0
                if pe>0: extras.append((d["entrada"],pe)); pe_t+=pe
                if f1: extras.append((d["sharpe"],0.15)); pe_t+=0.15
                if f2: extras.append((d["lp_inv"],0.15)); pe_t+=0.15
                if f3: extras.append((d["cross"],0.15)); pe_t+=0.15
                w_mom=max(0.40,1.0-pe_t)
                sc=d["mom"]*w_mom+sum(v*w for v,w in extras)
                scores.append({"sym":sym,"score":round(sc,1),"alpha":d["alpha"]})
            if not scores: continue
            scores.sort(key=lambda x:-x["score"])
            t1=scores[0]
            snap={"date":ed.isoformat(),"year":y,"sym":t1["sym"],
                  "alpha":t1["alpha"],"top1_score":t1["score"]}
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

        pasa=(pv_g<CRITERIO_P_NW and am_m1>CRITERIO_ALPHA and am_m2>CRITERIO_ALPHA and
              abs(am_m1-am_m2)<CRITERIO_DIFF and min(pv_m1,pv_m2)<CRITERIO_P_MITAD)

        if pasa:
            n_rob+=1
            resultados.append({
                "lookback":lb,"skip":sk,"peso_entrada":pe,
                "f1_sharpe":f1,"f2_lp_inv":f2,"f3_cross":f3,
                "n":len(snaps),"alpha":am_g,"pvalue_nw":pv_g,
                "alpha_m1":am_m1,"pvalue_m1":pv_m1,
                "alpha_m2":am_m2,"pvalue_m2":pv_m2,
                "consistencia":round(abs(am_m1-am_m2),3),
            })

    resultados.sort(key=lambda x:x["pvalue_nw"])

    print(f"\n{'='*70}")
    print(f"RESULTADOS GRID — {n_rob} robustos de {n_ev} evaluados")
    print(f"{'='*70}")

    esperados=round(n_ev*CRITERIO_P_NW,1)
    print(f"\n  Esperados por azar: ~{esperados} | Encontrados: {n_rob}")
    if n_rob>esperados*2: print(f"  → SEÑAL REAL — mas que por azar")
    elif n_rob>esperados: print(f"  → Señal debil")
    else: print(f"  → Similar al azar — posible ruido")

    if not resultados:
        print("\nNINGUN modelo pasa criterios.")
        print("B3 (p=0.0447) y A3 (p=0.0231) siguen siendo referencias.")
    else:
        print(f"\n{'Rk':3} {'LB':3} {'SK':2} {'PE':5} {'F1':3} {'F2':3} {'F3':3} "
              f"{'Alpha':>8} {'p_NW':>7} {'M1':>7} {'M2':>7} {'Diff':>6}")
        print("-"*68)
        for i,r in enumerate(resultados[:25],1):
            f1s="✓" if r["f1_sharpe"] else "✗"
            f2s="✓" if r["f2_lp_inv"] else "✗"
            f3s="✓" if r["f3_cross"]  else "✗"
            mejor=" ←" if r["pvalue_nw"]<0.0447 else ""
            print(f"#{i:2d} {r['lookback']:3d} {r['skip']:2d} {r['peso_entrada']:5.2f} "
                  f"{f1s:3s} {f2s:3s} {f3s:3s} "
                  f"{r['alpha']:>+7.3f}% {r['pvalue_nw']:>7.4f} "
                  f"{r['alpha_m1']:>+6.3f}% {r['alpha_m2']:>+6.3f}% "
                  f"{r['consistencia']:>5.3f}%{mejor}")

        print(f"\nRESPUESTAS CLAVE:")
        rob_sk0=[r for r in resultados if r["skip"]==0]
        rob_sk1=[r for r in resultados if r["skip"]==1]
        print(f"  Skip-0: {len(rob_sk0)} | Skip-1: {len(rob_sk1)}", end=" ")
        if len(rob_sk1)>len(rob_sk0): print(f"→ Skip-1 MAS ROBUSTO")
        elif len(rob_sk0)>len(rob_sk1): print(f"→ Skip-0 MAS ROBUSTO")
        else: print(f"→ Empate")

        rob_sin=[r for r in resultados if r["peso_entrada"]==0]
        rob_con=[r for r in resultados if r["peso_entrada"]>0]
        print(f"  Sin entrada: {len(rob_sin)} | Con entrada: {len(rob_con)}", end=" ")
        if len(rob_con)>len(rob_sin): print(f"→ Entrada MEJORA")
        elif len(rob_sin)>len(rob_con): print(f"→ Entrada NO mejora")
        else: print(f"→ Neutral")

        lbs=Counter(r["lookback"] for r in resultados)
        print(f"  Lookbacks: {dict(sorted(lbs.items()))} → optimo: {lbs.most_common(1)[0][0]}M")
        print(f"  F1 Sharpe: {sum(1 for r in resultados if r['f1_sharpe'])}/{len(resultados)}")
        print(f"  F2 LP inv: {sum(1 for r in resultados if r['f2_lp_inv'])}/{len(resultados)}")
        print(f"  F3 Cross:  {sum(1 for r in resultados if r['f3_cross'])}/{len(resultados)}")

        alphas=[r["alpha"] for r in resultados[:20]]
        rango=round(max(alphas)-min(alphas),2) if alphas else 0
        print(f"  Rango alpha top20: {rango}% →", end=" ")
        if rango<1.0: print("ESTRECHO sin overfitting")
        elif rango<2.0: print("MODERADO aceptable")
        else: print("AMPLIO posible overfitting")

        best=resultados[0]
        print(f"\nMEJOR MODELO: LB={best['lookback']}M SK={best['skip']} PE={best['peso_entrada']}")
        print(f"  F1={best['f1_sharpe']} F2={best['f2_lp_inv']} F3={best['f3_cross']}")
        print(f"  Alpha={best['alpha']:+.3f}% p_NW={best['pvalue_nw']}")
        print(f"  M1={best['alpha_m1']:+.3f}% M2={best['alpha_m2']:+.3f}% Diff={best['consistencia']:.3f}%")
        print(f"\nVS B1(+2.98% p=0.0487) B3(+3.44% p=0.0447) A3(+3.84% p=0.0231)")
        if best["pvalue_nw"]<0.0231: print(f"→ MEJORA A A3")
        elif best["pvalue_nw"]<0.0447: print(f"→ Mejora B3 no A3")
        else: print(f"→ No mejora referencias")

        # ANALISIS ADICIONAL del mejor modelo
        lb,sk,pe=best["lookback"],best["skip"],best["peso_entrada"]
        f1,f2,f3=best["f1_sharpe"],best["f2_lp_inv"],best["f3_cross"]
        key=(lb,sk)
        best_snaps=[]; best_all_obs=[]
        for mi,(y,m) in enumerate(months):
            md=month_meta[mi]; ed=md["ed"]; ri=md["ri"]
            if ri is None: continue
            scores=[]
            for sym in etf_data:
                if sym not in pre or mi not in pre[sym]: continue
                if key not in pre[sym][mi]: continue
                d=pre[sym][mi][key]
                if d["mom"] is None: continue
                extras=[]; pe_t=0
                if pe>0: extras.append((d["entrada"],pe)); pe_t+=pe
                if f1: extras.append((d["sharpe"],0.15)); pe_t+=0.15
                if f2: extras.append((d["lp_inv"],0.15)); pe_t+=0.15
                if f3: extras.append((d["cross"],0.15)); pe_t+=0.15
                w_mom=max(0.40,1.0-pe_t)
                sc=d["mom"]*w_mom+sum(v*w for v,w in extras)
                scores.append({"sym":sym,"score":round(sc,1),"alpha":d["alpha"]})
                best_all_obs.append({"score":round(sc,1),"alpha":d["alpha"]})
            if not scores: continue
            scores.sort(key=lambda x:-x["score"])
            t1=scores[0]
            best_snaps.append({"date":ed.isoformat(),"year":y,"sym":t1["sym"],
                              "alpha":t1["alpha"],"top1_score":t1["score"]})

        analisis_adicional(best_snaps, best_all_obs,
                          f"LB={lb}M SK={sk} PE={pe} F1={f1} F2={f2} F3={f3}")

    out={"fecha":TODAY.isoformat(),"total_evaluadas":n_ev,"total_robustas":n_rob,
         "esperados_azar":esperados,
         "criterios":{"p_nw":CRITERIO_P_NW,"alpha_min":CRITERIO_ALPHA,
                      "diff_max":CRITERIO_DIFF,"p_mitad":CRITERIO_P_MITAD},
         "modelos_robustos":resultados[:50]}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)
    print(f"\nTotal: {n_ev} | Robustas: {n_rob} | guardado")

if __name__=="__main__":
    main()
