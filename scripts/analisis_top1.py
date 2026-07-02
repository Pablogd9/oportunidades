#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analisis_top1.py — Consistencia real del Top1 mes a mes.

Preguntas que responde:
  1. El Top1 elegido cada mes, ¿renta más que el Top2, Top3... Top15?
  2. ¿Cuántas veces el Top1 es realmente el mejor sector real?
  3. ¿El ranking del sistema predice el ranking real? (Spearman)
  4. Distribución del alpha del Top1 mes a mes
  5. Señal actual — qué sector elegiría el sistema HOY
"""

import json, math, os, datetime
from collections import defaultdict, Counter

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "analisis_top1.json")
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

def spearman(xs,ys):
    n=len(xs)
    if n<5: return None
    xr={v:i for i,v in enumerate(sorted(set(xs)))}
    yr={v:i for i,v in enumerate(sorted(set(ys)))}
    sr=[xr[x] for x in xs]; tr=[yr[y] for y in ys]
    mx=sum(sr)/n; my=sum(tr)/n
    cov=sum((sr[i]-mx)*(tr[i]-my) for i in range(n))/n
    sx=math.sqrt(sum((x-mx)**2 for x in sr)/n)
    sy=math.sqrt(sum((y-my)**2 for y in tr)/n)
    return round(cov/(sx*sy),3) if sx>0 and sy>0 else 0

def momentum_score(prices):
    """Identico al Factor5."""
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

def main():
    print("="*70)
    print("ANALISIS DE CONSISTENCIA DEL TOP1")
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

    all_months=[]; spearman_por_mes=[]

    for y,m in months:
        ed=datetime.date(y,m,1)
        ri=period_return(iwda_p,iwda_d,y,m,3)
        if ri is None: continue

        etfs_mes=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            sc=momentum_score(pt)
            if sc is None: continue
            r=period_return(data["prices"],data["dates"],y,m,3)
            if r is None: continue
            etfs_mes.append({"sym":sym,"score":sc,"ret":r,"alpha":round(r-ri,2)})

        if len(etfs_mes)<5: continue

        etfs_mes.sort(key=lambda x:-x["score"])
        etfs_por_ret=sorted(etfs_mes,key=lambda x:-x["ret"])
        rank_real={e["sym"]:i+1 for i,e in enumerate(etfs_por_ret)}

        for i,e in enumerate(etfs_mes):
            e["rank_real"]=rank_real[e["sym"]]
            e["rank_score"]=i+1

        sp_mes=spearman([e["score"] for e in etfs_mes],[e["ret"] for e in etfs_mes])
        spearman_por_mes.append({"date":ed.isoformat(),"year":y,"spearman":sp_mes})

        all_months.append({
            "date":ed.isoformat(),"year":y,"ri":ri,
            "n_etfs":len(etfs_mes),"etfs":etfs_mes,
            "top1":etfs_mes[0],
            "top1_rank_real":etfs_mes[0]["rank_real"],
            "spearman":sp_mes
        })

    if not all_months: print("ERROR sin datos"); return
    n=len(all_months)

    # ── 1. Alpha por posicion ─────────────────────────────────────────
    print(f"\n{'='*70}")
    print("1. ALPHA MEDIO POR POSICION EN EL RANKING")
    print(f"{'='*70}")
    print(f"\n  {'Pos':5s} {'N':>5} {'Alpha medio':>12} {'Bate IWDA':>10}")
    print(f"  {'-'*35}")
    by_rank=defaultdict(list)
    for md in all_months:
        for e in md["etfs"]:
            by_rank[e["rank_score"]].append(e["alpha"])
    alphas_rank=[]
    for rank in sorted(by_rank.keys()):
        als=by_rank[rank]
        am=round(sum(als)/len(als),2)
        bate=round(sum(1 for a in als if a>0)/len(als)*100,1)
        alphas_rank.append(am)
        print(f"  Top{rank:<3d} {len(als):>5} {am:>+11.2f}% {bate:>9.1f}%")

    monotono=all(alphas_rank[i]>=alphas_rank[i+1] for i in range(min(4,len(alphas_rank)-1)))
    print(f"\n  Top1>Top2>Top3>Top4>Top5 monotono: {'SI' if monotono else 'NO'}")

    # ── 2. ¿El Top1 es el mejor real? ────────────────────────────────
    print(f"\n{'='*70}")
    print("2. ¿CUANTAS VECES EL TOP1 FUE EL MEJOR SECTOR REAL?")
    print(f"{'='*70}")

    rank_reales=[md["top1_rank_real"] for md in all_months]
    n_etfs_medio=round(sum(md["n_etfs"] for md in all_months)/n,1)

    es_1=sum(1 for r in rank_reales if r==1)
    es_top3=sum(1 for r in rank_reales if r<=3)
    es_top5=sum(1 for r in rank_reales if r<=5)
    es_peor=sum(1 for r in rank_reales if r>n_etfs_medio-3)
    rank_medio=round(sum(rank_reales)/n,1)

    print(f"\n  Total señales: {n} | ETFs por mes: ~{n_etfs_medio}")
    print(f"  Top1 fue el MEJOR sector:    {es_1:3d}/{n} ({round(es_1/n*100,1)}%)")
    print(f"  Top1 estuvo en top 3 real:   {es_top3:3d}/{n} ({round(es_top3/n*100,1)}%)")
    print(f"  Top1 estuvo en top 5 real:   {es_top5:3d}/{n} ({round(es_top5/n*100,1)}%)")
    print(f"  Top1 estuvo en peor 3 real:  {es_peor:3d}/{n} ({round(es_peor/n*100,1)}%)")
    print(f"\n  Ranking real medio del Top1: {rank_medio} de {n_etfs_medio}")
    print(f"  Ranking aleatorio seria:     {round(n_etfs_medio/2,1)}")
    if rank_medio < n_etfs_medio/2:
        print(f"  → Top1 tiende a estar en la MEJOR mitad del ranking real ✓")
    else:
        print(f"  → Top1 NO tiende a estar mejor que el azar ✗")

    print(f"\n  Distribucion del ranking real del Top1:")
    dist=Counter(rank_reales)
    for rank in sorted(dist.keys()):
        cnt=dist[rank]
        bar="█"*cnt
        print(f"    Puesto {rank:2d}: {cnt:3d} veces {bar}")

    # ── 3. Spearman ───────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("3. CORRELACION SPEARMAN — score vs rentabilidad real por mes")
    print(f"{'='*70}")

    sp_vals=[m["spearman"] for m in spearman_por_mes if m["spearman"] is not None]
    if sp_vals:
        sp_medio=round(sum(sp_vals)/len(sp_vals),3)
        sp_pos=sum(1 for s in sp_vals if s>0)
        sp_sig=sum(1 for s in sp_vals if s>0.3)
        print(f"\n  Spearman medio: {sp_medio}")
        print(f"  Meses Spearman > 0:   {sp_pos}/{len(sp_vals)} ({round(sp_pos/len(sp_vals)*100,1)}%)")
        print(f"  Meses Spearman > 0.3: {sp_sig}/{len(sp_vals)} ({round(sp_sig/len(sp_vals)*100,1)}%)")
        if sp_medio>0.15: print(f"  → Predice CONSISTENTEMENTE el ranking real")
        elif sp_medio>0.05: print(f"  → Prediccion DEBIL del ranking real")
        else: print(f"  → NO predice el ranking real")

        print(f"\n  Spearman por año:")
        by_year=defaultdict(list)
        for m in spearman_por_mes:
            if m["spearman"] is not None: by_year[m["year"]].append(m["spearman"])
        for yr in sorted(by_year.keys()):
            sp_y=round(sum(by_year[yr])/len(by_year[yr]),3)
            nota="→ predice bien" if sp_y>0.2 else "→ predice mal" if sp_y<0 else "→ neutral"
            print(f"    {yr}: {sp_y:>6.3f}  {nota}")
    else:
        sp_medio=None

    # ── 4. Distribucion del alpha ─────────────────────────────────────
    print(f"\n{'='*70}")
    print("4. DISTRIBUCION DEL ALPHA DEL TOP1 MES A MES")
    print(f"{'='*70}")

    alphas_top1=[md["top1"]["alpha"] for md in all_months]
    am=round(sum(alphas_top1)/n,2)
    pv,_=newey_west_pvalue(alphas_top1,NW_LAGS)
    positivos=sum(1 for a in alphas_top1 if a>0)

    print(f"\n  Alpha medio: {am:+.2f}% | p_NW={pv} | Bate IWDA: {positivos}/{n} ({round(positivos/n*100,1)}%)")
    print(f"\n  Distribucion:")
    rangos=[
        (">+10%",  lambda a:a>10,  "← grandes ganancias"),
        ("+2 a +10%", lambda a:2<a<=10, ""),
        ("-2 a +2%", lambda a:-2<=a<=2, "← neutral"),
        ("-10 a -2%", lambda a:-10<=a<-2, ""),
        ("<-10%",  lambda a:a<-10,  "← grandes perdidas"),
    ]
    for label,fn,nota in rangos:
        cnt=sum(1 for a in alphas_top1 if fn(a))
        print(f"    {label:12s}: {cnt:3d} meses ({round(cnt/n*100,1)}%) {nota}")

    alphas_sorted=sorted(all_months,key=lambda x:x["top1"]["alpha"],reverse=True)
    print(f"\n  5 MEJORES meses:")
    for md in alphas_sorted[:5]:
        print(f"    {md['date']} {md['top1']['sym']:8s} score={md['top1']['score']:5.1f} alpha={md['top1']['alpha']:+7.2f}%")
    print(f"\n  5 PEORES meses:")
    for md in alphas_sorted[-5:]:
        print(f"    {md['date']} {md['top1']['sym']:8s} score={md['top1']['score']:5.1f} alpha={md['top1']['alpha']:+7.2f}%")

    # ── 5. Señal actual ───────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("5. SEÑAL ACTUAL — scores HOY")
    print(f"{'='*70}")

    scores_hoy=[]
    for sym,data in etf_data.items():
        sc=momentum_score(data["prices"])
        if sc is not None:
            scores_hoy.append({"sym":sym,"score":sc,"sector":data["sector"]})
    scores_hoy.sort(key=lambda x:-x["score"])

    print(f"\n  {'Pos':4s} {'ETF':8s} {'Sector':20s} {'Score':>7}")
    print(f"  {'-'*44}")
    for i,e in enumerate(scores_hoy,1):
        señal=" ← INVERTIR" if i==1 else " ← Top2" if i==2 else ""
        print(f"  {i:4d} {e['sym']:8s} {e['sector']:20s} {e['score']:>7.1f}{señal}")

    # Guardar
    out={
        "fecha":TODAY.isoformat(),"n_senales":n,
        "alpha_medio":am,"pvalue_nw":pv,
        "rank_real_medio":rank_medio,
        "spearman_medio":sp_medio,
        "pct_top1_mejor":round(es_1/n*100,1),
        "pct_top1_top3":round(es_top3/n*100,1),
        "señal_actual":scores_hoy[0] if scores_hoy else None,
        "scores_hoy":scores_hoy
    }
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*70}")
    print("RESUMEN")
    print(f"{'='*70}")
    print(f"  Alpha medio Top1: {am:+.2f}% | p_NW={pv}")
    print(f"  Top1 fue el mejor real: {round(es_1/n*100,1)}% | en top3: {round(es_top3/n*100,1)}%")
    print(f"  Ranking real medio: {rank_medio} de {n_etfs_medio}")
    print(f"  Spearman medio: {sp_medio}")
    if scores_hoy:
        print(f"  SEÑAL HOY: {scores_hoy[0]['sym']} ({scores_hoy[0]['sector']}) score={scores_hoy[0]['score']:.1f}")
    print(f"{'='*70}")

if __name__=="__main__":
    main()
