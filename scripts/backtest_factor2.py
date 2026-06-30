#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_factor2.py — Factor unico (momentum 12M skip-1) con analisis separado.

Mejoras vs factor1:
  1. Separa completamente el rendimiento de Top1 vs Top2 (no solo combinado)
  2. Valida si el SCORE tiene sentido ordinal real:
     - Divide TODOS los ETFs evaluados cada mes en quintiles de score
     - Mide el alpha medio de cada quintil
     - Si el sistema funciona: quintil 5 (mejor score) > quintil 1 (peor score)
  3. Reporta correlacion rank entre score y retorno futuro (Spearman simplificado)
"""

import json, math, os, random, datetime

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest_factor2.json")
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

def spearman_simple(scores, rets):
    n=len(scores)
    if n<5: return None
    score_rank = {v:i for i,v in enumerate(sorted(scores))}
    ret_rank   = {v:i for i,v in enumerate(sorted(rets))}
    sr = [score_rank[s] for s in scores]
    rr = [ret_rank[r] for r in rets]
    mean_sr = sum(sr)/n; mean_rr = sum(rr)/n
    cov = sum((sr[i]-mean_sr)*(rr[i]-mean_rr) for i in range(n))/n
    sd_sr = math.sqrt(sum((x-mean_sr)**2 for x in sr)/n)
    sd_rr = math.sqrt(sum((x-mean_rr)**2 for x in rr)/n)
    if sd_sr==0 or sd_rr==0: return 0
    return round(cov/(sd_sr*sd_rr),3)

def main():
    print("="*70)
    print("BACKTEST FACTOR 2 — Momentum puro + analisis Top1/Top2 + quintiles")
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

    all_score_ret = []
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
            scores.append({"sym":sym,"score":sc,"ret":r,"alpha_indiv":round(r-ri,2)})
            all_score_ret.append((sc, round(r-ri,2)))

        if len(scores)<2: continue
        scores.sort(key=lambda x:-x["score"])
        t1,t2=scores[0],scores[1]
        ri=period_return(iwda_p,iwda_d,y,m,3)
        if ri is None: continue

        snaps.append({
            "date":ed.isoformat(),
            "top1_sym":t1["sym"],"top1_score":t1["score"],"top1_ret":t1["ret"],"top1_alpha":t1["alpha_indiv"],
            "top2_sym":t2["sym"],"top2_score":t2["score"],"top2_ret":t2["ret"],"top2_alpha":t2["alpha_indiv"],
            "ri":ri,
            "alpha_combinado":round((t1["ret"]*0.70+t2["ret"]*0.30)-ri,2)
        })

    if not snaps: print("ERROR sin señales"); return

    print("\n"+"─"*70)
    print("ANALISIS 1 — Top1 vs Top2 (rendimiento SEPARADO)")
    print("─"*70)

    alphas_top1 = [s["top1_alpha"] for s in snaps]
    alphas_top2 = [s["top2_alpha"] for s in snaps]
    alphas_comb = [s["alpha_combinado"] for s in snaps]

    am1 = round(sum(alphas_top1)/len(alphas_top1),3)
    am2 = round(sum(alphas_top2)/len(alphas_top2),3)
    amc = round(sum(alphas_comb)/len(alphas_comb),3)

    bate1 = round(sum(1 for a in alphas_top1 if a>0)/len(alphas_top1)*100,1)
    bate2 = round(sum(1 for a in alphas_top2 if a>0)/len(alphas_top2)*100,1)

    pv1,t1stat,_,_ = newey_west_pvalue(alphas_top1, NW_LAGS)
    pv2,t2stat,_,_ = newey_west_pvalue(alphas_top2, NW_LAGS)
    pvc,tcstat,_,_ = newey_west_pvalue(alphas_comb, NW_LAGS)

    def sig(pv):
        if pv is None: return "Sin datos"
        if pv<0.05: return "SIGNIFICATIVO p<0.05"
        if pv<0.10: return "Marginal p<0.10"
        if pv<0.20: return "Debil p<0.20"
        return "No significativo"

    print(f"\n  TOP1 SOLO (mejor score cada mes):")
    print(f"    n={len(alphas_top1)} | alpha medio={am1:+.3f}% | bate IWDA={bate1}%")
    print(f"    Newey-West: p={pv1} t={t1stat} -> {sig(pv1)}")

    print(f"\n  TOP2 SOLO (segundo mejor score cada mes):")
    print(f"    n={len(alphas_top2)} | alpha medio={am2:+.3f}% | bate IWDA={bate2}%")
    print(f"    Newey-West: p={pv2} t={t2stat} -> {sig(pv2)}")

    print(f"\n  COMBINADO (70% Top1 + 30% Top2):")
    print(f"    n={len(alphas_comb)} | alpha medio={amc:+.3f}%")
    print(f"    Newey-West: p={pvc} t={tcstat} -> {sig(pvc)}")

    diff_top1_top2 = round(am1 - am2, 3)
    print(f"\n  DIFERENCIA Top1 vs Top2: {diff_top1_top2:+.3f}%")
    if diff_top1_top2 > 0.3:
        print(f"  → Top1 es claramente mejor que Top2. El ranking SI distingue.")
    elif diff_top1_top2 > 0:
        print(f"  → Top1 ligeramente mejor que Top2. Distincion debil.")
    else:
        print(f"  → Top2 es igual o mejor que Top1. El ranking NO distingue bien.")

    print("\n"+"─"*70)
    print("ANALISIS 2 — Quintiles de score (TODOS los ETFs evaluados cada mes)")
    print("─"*70)
    print(f"\n  Total observaciones (ETF x mes): {len(all_score_ret)}")

    all_score_ret.sort(key=lambda x: x[0])
    n_total = len(all_score_ret)
    quintil_size = n_total // 5

    print(f"\n  {'Quintil':10s} {'Score range':18s} {'N':>5} {'Alpha medio':>12}")
    print(f"  {'-'*50}")

    quintiles_data = []
    for q in range(5):
        start_idx = q * quintil_size
        end_idx = (q+1)*quintil_size if q<4 else n_total
        chunk = all_score_ret[start_idx:end_idx]
        if not chunk: continue
        scores_q = [x[0] for x in chunk]
        alphas_q = [x[1] for x in chunk]
        am_q = round(sum(alphas_q)/len(alphas_q),3)
        quintiles_data.append({"q":q+1,"score_min":min(scores_q),"score_max":max(scores_q),
                               "n":len(chunk),"alpha_medio":am_q})
        label = "Q1 (peor)" if q==0 else "Q5 (mejor)" if q==4 else f"Q{q+1}"
        print(f"  {label:10s} {min(scores_q):5.0f}-{max(scores_q):5.0f}      {len(chunk):>5} {am_q:>+11.2f}%")

    all_scores_list = [x[0] for x in all_score_ret]
    all_alphas_list = [x[1] for x in all_score_ret]
    rank_corr = spearman_simple(all_scores_list, all_alphas_list)

    print(f"\n  Correlacion de rango (Spearman) score vs alpha futuro: {rank_corr}")
    if rank_corr is not None:
        if rank_corr > 0.15:
            print(f"  → El score SI predice ordinalmente el alpha futuro (correlacion positiva)")
        elif rank_corr > 0.05:
            print(f"  → El score predice debilmente — relacion positiva pero pequena")
        elif rank_corr > -0.05:
            print(f"  → El score NO tiene relacion clara con el alpha futuro")
        else:
            print(f"  → ALERTA: el score predice EN SENTIDO CONTRARIO (mas score = peor alpha)")

    alphas_por_quintil = [q["alpha_medio"] for q in quintiles_data]
    es_monotono = all(alphas_por_quintil[i] <= alphas_por_quintil[i+1] for i in range(len(alphas_por_quintil)-1))
    print(f"\n  ¿Los quintiles son monotonos crecientes (Q1<Q2<Q3<Q4<Q5)? {'SI' if es_monotono else 'NO'}")
    if not es_monotono:
        print(f"  → El score tiene relacion con el alpha pero NO es perfectamente ordinal")

    print("\n"+"─"*70)
    print("VALIDACION CRUZADA — Bootstrap del alpha combinado")
    print("─"*70)
    print(f"\n  Bootstrap 1000...", end=" ", flush=True)
    ids = list(etf_data.keys())
    ra = []
    for _ in range(N_BOOTSTRAP):
        rs=0.0; ris=0.0; nm=0
        for y,m in months:
            avail=[i for i in ids if etf_data[i]["prices"] and
                   len(prices_up_to(etf_data[i]["prices"],etf_data[i]["dates"],datetime.date(y,m,1)))>=273]
            if len(avail)<2: continue
            ch=random.sample(avail,2)
            r1b=period_return(etf_data[ch[0]]["prices"],etf_data[ch[0]]["dates"],y,m,3)
            r2b=period_return(etf_data[ch[1]]["prices"],etf_data[ch[1]]["dates"],y,m,3)
            rib=period_return(iwda_p,iwda_d,y,m,3)
            if r1b is not None and r2b is not None and rib is not None:
                rs+=r1b*0.70+r2b*0.30; ris+=rib; nm+=1
        if nm>0: ra.append((rs-ris)/nm)
    pct=sum(1 for a in ra if a<=amc)/len(ra)*100
    pv_boot=round(1-pct/100,4)
    mean_rand=round(sum(ra)/len(ra),3)
    print(f"alpha_rand={mean_rand}% real={amc}% pct={pct:.0f}% p={pv_boot}")

    out = {
        "n_senales": len(snaps),
        "top1": {"alpha_medio": am1, "bate_pct": bate1, "pvalue_nw": pv1},
        "top2": {"alpha_medio": am2, "bate_pct": bate2, "pvalue_nw": pv2},
        "combinado": {"alpha_medio": amc, "pvalue_nw": pvc, "pvalue_bootstrap": pv_boot},
        "diferencia_top1_top2": diff_top1_top2,
        "quintiles": quintiles_data,
        "rank_correlation": rank_corr,
        "es_monotono": es_monotono,
        "snapshots": snaps,
    }
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*70}")
    print("RESUMEN FINAL")
    print(f"{'='*70}")
    print(f"  Top1 solo:    alpha={am1:+.2f}% | p={pv1} | {sig(pv1)}")
    print(f"  Top2 solo:    alpha={am2:+.2f}% | p={pv2} | {sig(pv2)}")
    print(f"  Combinado:    alpha={amc:+.2f}% | p_NW={pvc} | p_boot={pv_boot}")
    print(f"  Rank corr:    {rank_corr} | Monotono: {'SI' if es_monotono else 'NO'}")
    print(f"{'='*70}")

if __name__=="__main__":
    main()
