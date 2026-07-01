#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_factor7.py — EMA200 y VIX como filtros de regimen.

Prueba 4 modelos simultaneamente vs Factor5 (base):

  M0: Factor5 base (sin filtros)
  M1: Factor5 + filtro EMA200
  M2: Factor5 + filtro VIX (3 opciones: IWDA, Defensivos, Ignorar)
  M3: Factor5 + EMA200 + VIX (3 opciones)

Cuando el filtro actua, compara:
  OpA: ir a IWDA ese mes
  OpB: ir al mejor sector defensivo disponible
  OpC: ignorar el filtro, usar momentum puro
"""

import json, math, os, random, datetime, urllib.request
from collections import Counter, defaultdict

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest_factor7.json")
TODAY       = datetime.date.today()
N_BOOTSTRAP = 1000
WINDOW_YEARS= 5
NW_LAGS     = 2
random.seed(42)

BACKTEST_UNIVERSE = [
    ("SMH","Semiconductores","growth"),
    ("IBB","Biotecnologia","growth"),
    ("ITA","Defensa","defensive"),
    ("IGV","Software","growth"),
    ("VHT","Salud","defensive"),
    ("PHO","Agua","defensive"),
    ("IHI","Salud2","defensive"),
    ("ICLN","EnergiaLimpia","growth"),
    ("GRID","Infraestructura","mixed"),
    ("COPX","Cobre","cyclical"),
    ("LIT","Litio","cyclical"),
    ("INDA","India","growth"),
    ("ROBO","Robotica","growth"),
    ("CIBR","Ciberseguridad","defensive"),
    ("PAVE","Infraestructura2","mixed"),
]
DEFENSIVE_SECTORS = {"ITA","VHT","IHI","PHO","CIBR"}
BENCHMARK  = "IWDA.AS"
SPLIT_DATE = datetime.date(2022, 1, 1)
VIX_UMBRAL = 25

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

def ema200_ok(prices):
    if not prices or len(prices)<200: return True
    k=2.0/201; ema=sum(prices[:200])/200
    for p in prices[200:]: ema=p*k+ema*(1-k)
    return prices[-1] >= ema

def get_vix_at_date(vix_prices, vix_dates, target_date):
    return price_at_date(vix_prices, vix_dates, target_date)

def sig(pv):
    if pv is None: return "Sin datos"
    if pv<0.05: return "SIGNIFICATIVO p<0.05"
    if pv<0.10: return "Marginal p<0.10"
    if pv<0.20: return "Debil p<0.20"
    return "No significativo"

def calcular_alpha_serie(snaps):
    if not snaps: return None,None,None,None
    alphas=[s["alpha"] for s in snaps]
    am=round(sum(alphas)/len(alphas),3)
    bate=round(sum(1 for a in alphas if a>0)/len(alphas)*100,1)
    pv_nw,tstat,_,_=newey_west_pvalue(alphas,NW_LAGS)
    return am,bate,pv_nw,tstat

def main():
    print("="*70)
    print("BACKTEST FACTOR 7 — EMA200 y VIX como filtros de regimen")
    print(f"Fecha: {TODAY} | ETFs: {len(BACKTEST_UNIVERSE)} | VIX umbral: {VIX_UMBRAL}")
    print("="*70)

    print("\nCargando ETFs...")
    etf_data={}
    for sym,sec,tipo in BACKTEST_UNIVERSE:
        p,d=load_from_cache(sym)
        if not p or len(p)<273:
            print(f"  {sym:8s} insuficiente"); continue
        etf_data[sym]={"sector":sec,"tipo":tipo,"prices":p,"dates":d}
        print(f"  {sym:8s} {len(p):5d}d [{tipo}]")

    iwda_p,iwda_d=load_from_cache(BENCHMARK)
    if not iwda_p: print("ERROR sin IWDA"); return

    print("\nCargando VIX...")
    vix_p,vix_d=load_from_cache("^VIX")
    if not vix_p: vix_p,vix_d=load_from_cache("VIX")
    if not vix_p:
        print("  VIX no en cache — descargando...")
        try:
            url="https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=max&interval=1d"
            req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req,timeout=20) as r:
                d=json.loads(r.read().decode())
            res=d["chart"]["result"][0]
            ts=res.get("timestamp",[])
            cls=res.get("indicators",{}).get("quote",[{}])[0].get("close",[])
            pairs={}
            for t,c in zip(ts,cls):
                if c: pairs[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")]=float(c)
            series=sorted(pairs.items())
            vix_p=[p for _,p in series]; vix_d=[d for d,_ in series]
            print(f"  VIX: {len(vix_p)}d | {vix_d[0]} -> {vix_d[-1]}")
        except Exception as e:
            print(f"  ERROR VIX: {e}"); vix_p=None; vix_d=None
    else:
        print(f"  VIX del cache: {len(vix_p)}d")

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

    snaps_m0=[]; snaps_m1=[]
    snaps_m2a=[]; snaps_m2b=[]; snaps_m2c=[]
    snaps_m3a=[]; snaps_m3b=[]; snaps_m3c=[]
    vix_alto_meses=0; ema_filtro_meses=0; ambos_filtro_meses=0

    for y,m in months:
        ed=datetime.date(y,m,1)
        vix_val=get_vix_at_date(vix_p,vix_d,ed) if vix_p else None
        vix_alto=vix_val is not None and vix_val>VIX_UMBRAL

        scores=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            if len(pt)<273: continue
            sc=momentum_score(pt)
            if sc is None: continue
            r=period_return(data["prices"],data["dates"],y,m,3)
            ri=period_return(iwda_p,iwda_d,y,m,3)
            if r is None or ri is None: continue
            ema_ok=ema200_ok(pt)
            scores.append({"sym":sym,"score":sc,"ret":r,"ema_ok":ema_ok,
                          "defensive":sym in DEFENSIVE_SECTORS,"alpha":round(r-ri,2)})

        if not scores: continue
        scores.sort(key=lambda x:-x["score"])
        ri=period_return(iwda_p,iwda_d,y,m,3)
        if ri is None: continue
        t1=scores[0]

        # M0 base
        snaps_m0.append({"date":ed.isoformat(),"year":y,"sym":t1["sym"],
                        "score":t1["score"],"ret":t1["ret"],"ri":ri,
                        "alpha":round(t1["ret"]-ri,2),"vix":vix_val})

        # M1 EMA200
        scores_ema=[s for s in scores if s["ema_ok"]] or scores
        t1_m1=scores_ema[0]
        ema_cambio=(t1_m1["sym"]!=t1["sym"])
        if ema_cambio: ema_filtro_meses+=1
        snaps_m1.append({"date":ed.isoformat(),"year":y,"sym":t1_m1["sym"],
                        "ret":t1_m1["ret"],"ri":ri,
                        "alpha":round(t1_m1["ret"]-ri,2),"filtro":ema_cambio})

        # M2 VIX
        if vix_alto:
            vix_alto_meses+=1
            snaps_m2a.append({"date":ed.isoformat(),"year":y,"sym":"IWDA","ret":ri,"ri":ri,"alpha":0.0})
            def_scores=[s for s in scores if s["defensive"]] or scores
            t1_d=def_scores[0]
            snaps_m2b.append({"date":ed.isoformat(),"year":y,"sym":t1_d["sym"],
                             "ret":t1_d["ret"],"ri":ri,"alpha":round(t1_d["ret"]-ri,2)})
            snaps_m2c.append({"date":ed.isoformat(),"year":y,"sym":t1["sym"],
                             "ret":t1["ret"],"ri":ri,"alpha":round(t1["ret"]-ri,2)})
        else:
            for sl in [snaps_m2a,snaps_m2b,snaps_m2c]:
                sl.append({"date":ed.isoformat(),"year":y,"sym":t1["sym"],
                          "ret":t1["ret"],"ri":ri,"alpha":round(t1["ret"]-ri,2)})

        # M3 EMA200+VIX
        filtro_ambos=vix_alto or ema_cambio
        if filtro_ambos: ambos_filtro_meses+=1
        if filtro_ambos:
            snaps_m3a.append({"date":ed.isoformat(),"year":y,"sym":"IWDA","ret":ri,"ri":ri,"alpha":0.0})
            de_ema=[s for s in scores if s["defensive"] and s["ema_ok"]]
            if not de_ema: de_ema=[s for s in scores if s["defensive"]] or scores
            t1_de=de_ema[0]
            snaps_m3b.append({"date":ed.isoformat(),"year":y,"sym":t1_de["sym"],
                             "ret":t1_de["ret"],"ri":ri,"alpha":round(t1_de["ret"]-ri,2)})
            snaps_m3c.append({"date":ed.isoformat(),"year":y,"sym":t1["sym"],
                             "ret":t1["ret"],"ri":ri,"alpha":round(t1["ret"]-ri,2)})
        else:
            for sl in [snaps_m3a,snaps_m3b,snaps_m3c]:
                sl.append({"date":ed.isoformat(),"year":y,"sym":t1["sym"],
                          "ret":t1["ret"],"ri":ri,"alpha":round(t1["ret"]-ri,2)})

    print(f"\n  Meses VIX > {VIX_UMBRAL}: {vix_alto_meses}/{len(months)} ({round(vix_alto_meses/len(months)*100,1) if months else 0}%)")
    print(f"  Meses EMA200 cambio decision: {ema_filtro_meses}/{len(months)}")
    print(f"  Meses algun filtro actuo: {ambos_filtro_meses}/{len(months)}")

    modelos=[
        ("M0 Factor5 base",          snaps_m0),
        ("M1 EMA200",                 snaps_m1),
        ("M2A VIX->IWDA",            snaps_m2a),
        ("M2B VIX->Defensivos",      snaps_m2b),
        ("M2C VIX->ignorar",         snaps_m2c),
        ("M3A EMA200+VIX->IWDA",     snaps_m3a),
        ("M3B EMA200+VIX->Def",      snaps_m3b),
        ("M3C EMA200+VIX->ignorar",  snaps_m3c),
    ]

    print(f"\n{'='*70}")
    print("COMPARACION DE MODELOS")
    print(f"{'='*70}")
    print(f"\n  {'Modelo':30s} {'Alpha':>8} {'Bate%':>6} {'p_NW':>8}  Significancia")
    print(f"  {'-'*70}")

    resultados={}
    for nombre,snaps in modelos:
        if not snaps: continue
        am,bate,pv_nw,tstat=calcular_alpha_serie(snaps)
        if am is None: continue
        print(f"  {nombre:30s} {am:>+7.2f}% {bate:>5.1f}% {str(pv_nw):>8s}  {sig(pv_nw)}")
        resultados[nombre]={"alpha":am,"bate":bate,"pvalue_nw":pv_nw}

    if vix_alto_meses>0:
        print(f"\n{'='*70}")
        print(f"MESES VIX ALTO (VIX>{VIX_UMBRAL}) — que habria pasado")
        print(f"{'='*70}")
        meses_vix=[s for s in snaps_m0 if s.get("vix") and s["vix"]>VIX_UMBRAL]
        if meses_vix:
            am_vix=round(sum(s["alpha"] for s in meses_vix)/len(meses_vix),2)
            print(f"\n  M0 (momentum puro) en VIX alto: alpha={am_vix:+.2f}% (n={len(meses_vix)})")
            fechas_vix={s["date"] for s in meses_vix}
            for nombre,snaps in [("M2A IWDA",snaps_m2a),("M2B Defensivos",snaps_m2b)]:
                ss=[s for s in snaps if s["date"] in fechas_vix]
                if ss:
                    am_s=round(sum(s["alpha"] for s in ss)/len(ss),2)
                    print(f"  {nombre} en VIX alto: alpha={am_s:+.2f}%")
            print(f"\n  Por año en VIX alto:")
            by_year=defaultdict(list)
            for s in meses_vix: by_year[s["year"]].append(s["alpha"])
            for yr in sorted(by_year):
                als=by_year[yr]
                print(f"    {yr}: n={len(als):2d} alpha={round(sum(als)/len(als),2):+.2f}%")

    print(f"\n{'='*70}")
    print("VALIDACION POR MITADES")
    print(f"{'='*70}")
    for nombre,snaps in [("M0 base",snaps_m0),("M1 EMA200",snaps_m1),
                         ("M2A VIX->IWDA",snaps_m2a),("M3B EMA+VIX->Def",snaps_m3b)]:
        m1s=[s for s in snaps if datetime.date.fromisoformat(s["date"])<SPLIT_DATE]
        m2s=[s for s in snaps if datetime.date.fromisoformat(s["date"])>=SPLIT_DATE]
        am1,_,pv1,_=calcular_alpha_serie(m1s)
        am2,_,pv2,_=calcular_alpha_serie(m2s)
        if am1 is None or am2 is None: continue
        print(f"\n  {nombre}:")
        print(f"    Mitad 1 (2017-21): alpha={am1:+.2f}% p_NW={pv1}")
        print(f"    Mitad 2 (2022-26): alpha={am2:+.2f}% p_NW={pv2}")

    out={"fecha":TODAY.isoformat(),"vix_umbral":VIX_UMBRAL,
         "meses_vix_alto":vix_alto_meses,"resultados":resultados}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*70}")
    print("REFERENCIA: Factor5 alpha=+3.02% p_NW=0.0483 p_boot=0.003")
    print(f"{'='*70}")

if __name__=="__main__":
    main()
