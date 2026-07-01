#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_maestro.py — Comparacion exhaustiva de todos los modelos.

Dos bases:
  A: Momentum 12M SIN skip-1 (incluye el ultimo mes)
  B: Momentum 12M CON skip-1 (Factor5 validado)

Para cada base, 8 variantes:
  1. Solo Top1
  2. Top1 + Top2 70/30
  3. + Punto de entrada 70/30
  4. + Filtro EMA200
  5. + Filtro VIX -> IWDA
  6. + Filtro VIX -> Defensivos
  7. + Filtro Concentracion temporal
  8. + Filtro Fuerza relativa 1M

Total: 16 modelos en un solo backtest + simulacion DCA €500/mes.
"""

import json, math, os, random, datetime, urllib.request
from collections import Counter, defaultdict

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest_maestro.json")
TODAY       = datetime.date.today()
WINDOW_YEARS= 5
NW_LAGS     = 2
APORTACION  = 500
random.seed(42)

BACKTEST_UNIVERSE = [
    ("SMH","Semiconductores"),("IBB","Biotecnologia"),("ITA","Defensa"),
    ("IGV","Software"),("VHT","Salud"),("PHO","Agua"),
    ("IHI","Salud2"),("ICLN","EnergiaLimpia"),("GRID","Infraestructura"),
    ("COPX","Cobre"),("LIT","Litio"),("INDA","India"),("ROBO","Robotica"),
    ("CIBR","Ciberseguridad"),("PAVE","Infraestructura2"),
]
DEFENSIVE_SECTORS = {"ITA","VHT","IHI","PHO","CIBR"}
BENCHMARK   = "IWDA.AS"
SPLIT_DATE  = datetime.date(2022, 1, 1)
VIX_UMBRAL  = 25
CONC_UMBRAL = 0.60
W_MOM       = 0.70
W_ENT       = 0.30
W_TOP1      = 0.70
W_TOP2      = 0.30

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
        poly=(0.31938153*t_-0.356563782*t_**2+1.781477937*t_**3-1.821255978*t_**4+1.330274429*t_**5)
        return 1.0-(1.0/math.sqrt(2*math.pi))*math.exp(-x**2/2)*poly if x>=0 else ncdf(-x)
    pv=round(min(1.0,2*(1.0-ncdf(abs(tstat)))),4)
    return pv,round(tstat,3)

def mom_skip1(prices):
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

def mom_no_skip(prices):
    if not prices or len(prices)<252: return None
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    if n<252: return None
    m=ret_range(pw,-252,-1)
    if m is None: return None
    mn=m/(vol/20.0)
    hist=[]
    for i in range(252,min(n,756)):
        pc=pw[:n-i]
        if len(pc)>=252:
            r=ret_range(pc,-252,-1)
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
                hist.append(((pc[-1]/mx-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return round(100-pct_hist(dd_norm,hist),1)

def ema200_ok(prices):
    if not prices or len(prices)<200: return True
    k=2.0/201; ema=sum(prices[:200])/200
    for p in prices[200:]: ema=p*k+ema*(1-k)
    return prices[-1]>=ema

def fuerza_rel_1m(prices,iwda_prices):
    if not prices or len(prices)<22: return True
    if not iwda_prices or len(iwda_prices)<22: return True
    rs=ret_range(prices,-22,-1); ri=ret_range(iwda_prices,-22,-1)
    if rs is None or ri is None: return True
    return rs>=ri

def concentracion_ok(prices):
    if not prices or len(prices)<273: return True
    mt=ret_range(prices,-273,-21); mr=ret_range(prices,-63,-21)
    if mt is None or mr is None: return True
    if abs(mt)<0.5: return True
    return (mr/mt)<=CONC_UMBRAL

def sig(pv):
    if pv is None: return "---"
    if pv<0.05: return "p<0.05 ✓✓"
    if pv<0.10: return "p<0.10 ✓"
    if pv<0.20: return "p<0.20 ~"
    return "p>0.20 ✗"

def calcular_stats(snaps):
    if not snaps: return None,None,None
    alphas=[s["alpha"] for s in snaps]
    am=round(sum(alphas)/len(alphas),3)
    bate=round(sum(1 for a in alphas if a>0)/len(alphas)*100,1)
    pv,t=newey_west_pvalue(alphas,NW_LAGS)
    return am,bate,pv

def get_top(etfs,score_key,filtros=None):
    cands=sorted(etfs,key=lambda x:-x.get(score_key,0))
    if filtros:
        f=[e for e in cands if all(e.get(f,True) for f in filtros)]
        if f: cands=f
    return (cands[0] if cands else None),(cands[1] if len(cands)>1 else None)

def get_top_defensivo(etfs,score_key):
    d=sorted([e for e in etfs if e["defensive"]],key=lambda x:-x.get(score_key,0))
    return d[0] if d else sorted(etfs,key=lambda x:-x.get(score_key,0))[0]

def main():
    print("="*75)
    print("BACKTEST MAESTRO — 16 modelos en un solo backtest")
    print(f"Fecha: {TODAY} | Base A: sin skip-1 | Base B: con skip-1")
    print("="*75)

    print("\nCargando ETFs...")
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

    print("\nCargando VIX...")
    vix_p,vix_d=None,None
    for sym in ["^VIX","VIX"]:
        vix_p,vix_d=load_from_cache(sym)
        if vix_p: break
    if not vix_p:
        try:
            url="https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=max&interval=1d"
            req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req,timeout=20) as r:
                dd=json.loads(r.read().decode())
            res=dd["chart"]["result"][0]
            ts=res.get("timestamp",[]); cls=res.get("indicators",{}).get("quote",[{}])[0].get("close",[])
            pairs={}
            for t,c in zip(ts,cls):
                if c: pairs[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")]=float(c)
            series=sorted(pairs.items())
            vix_p=[p for _,p in series]; vix_d=[d for d,_ in series]
            print(f"  VIX: {len(vix_p)}d")
        except Exception as e:
            print(f"  VIX no disponible: {e}")

    starts=sorted([datetime.date.fromisoformat(d["dates"][0]) for d in etf_data.values()])
    idx=min(int(len(starts)*0.75),len(starts)-1)
    bt_start=datetime.date(starts[idx].year+WINDOW_YEARS,starts[idx].month,1)

    months=[]; dt=bt_start
    while dt<=TODAY.replace(day=1):
        months.append((dt.year,dt.month))
        dt=datetime.date(dt.year+1,1,1) if dt.month==12 else datetime.date(dt.year,dt.month+1,1)
    months=[m for m in months if datetime.date(m[0],m[1],1)<=TODAY.replace(day=1)-datetime.timedelta(days=90)]
    print(f"\nDesde {bt_start} | {len(months)} señales | horizonte 3M")

    # Procesar todos los meses
    all_months_data=[]
    for y,m in months:
        ed=datetime.date(y,m,1)
        ri_val=period_return(iwda_p,iwda_d,y,m,3)
        if ri_val is None: continue
        vix_val=price_at_date(vix_p,vix_d,ed) if vix_p else None
        vix_alto=vix_val is not None and vix_val>VIX_UMBRAL
        etfs=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            if len(pt)<273: continue
            it=prices_up_to(iwda_p,iwda_d,ed)
            sa=mom_no_skip(pt); sb=mom_skip1(pt)
            if sa is None and sb is None: continue
            r=period_return(data["prices"],data["dates"],y,m,3)
            if r is None: continue
            es=entrada_score(pt)
            score_a=sa if sa is not None else 50.0
            score_b=sb if sb is not None else 50.0
            etfs.append({
                "sym":sym,"r":r,"alpha":round(r-ri_val,2),
                "sa":score_a,"sb":score_b,
                "sa_ent":round(score_a*W_MOM+(es or 50)*W_ENT,1),
                "sb_ent":round(score_b*W_MOM+(es or 50)*W_ENT,1),
                "ema_ok":ema200_ok(pt),"fr1m_ok":fuerza_rel_1m(pt,it),
                "conc_ok":concentracion_ok(pt),"defensive":sym in DEFENSIVE_SECTORS,
            })
        if not etfs: continue
        all_months_data.append({"y":y,"m":m,"date":ed.isoformat(),"ri":ri_val,
                                "vix_alto":vix_alto,"etfs":etfs})

    modelos_def={
        "A1_top1":          ("sa",    False,[""],         None),
        "A2_top1top2":      ("sa",    True, [""],         None),
        "A3_entrada":       ("sa_ent",False,[""],         None),
        "A4_ema200":        ("sa",    False,["ema_ok"],   None),
        "A5_vix_iwda":      ("sa",    False,[""],         "iwda"),
        "A6_vix_def":       ("sa",    False,[""],         "def"),
        "A7_concentracion": ("sa",    False,["conc_ok"],  None),
        "A8_fuerza1m":      ("sa",    False,["fr1m_ok"],  None),
        "B1_top1":          ("sb",    False,[""],         None),
        "B2_top1top2":      ("sb",    True, [""],         None),
        "B3_entrada":       ("sb_ent",False,[""],         None),
        "B4_ema200":        ("sb",    False,["ema_ok"],   None),
        "B5_vix_iwda":      ("sb",    False,[""],         "iwda"),
        "B6_vix_def":       ("sb",    False,[""],         "def"),
        "B7_concentracion": ("sb",    False,["conc_ok"],  None),
        "B8_fuerza1m":      ("sb",    False,["fr1m_ok"],  None),
    }

    series={k:[] for k in modelos_def}

    for md in all_months_data:
        y,m,ri=md["y"],md["m"],md["ri"]
        etfs=md["etfs"]; vix_alto=md["vix_alto"]; date=md["date"]

        for key,(score_key,usar_top2,filtros,vix_action) in modelos_def.items():
            if vix_action and vix_alto:
                if vix_action=="iwda":
                    series[key].append({"date":date,"year":y,"sym":"IWDA","alpha":0.0,"ret":ri,"ri":ri})
                    continue
                elif vix_action=="def":
                    top=get_top_defensivo(etfs,score_key)
                    series[key].append({"date":date,"year":y,"sym":top["sym"],
                                       "alpha":round(top["r"]-ri,2),"ret":top["r"],"ri":ri})
                    continue

            fil=[f for f in filtros if f] if filtros else None
            t1,t2=get_top(etfs,score_key,fil)
            if t1 is None: continue

            if usar_top2 and t2:
                rp=t1["r"]*W_TOP1+t2["r"]*W_TOP2
                series[key].append({"date":date,"year":y,"sym":t1["sym"],
                                   "alpha":round(rp-ri,2),"ret":round(rp,2),"ri":ri})
            else:
                series[key].append({"date":date,"year":y,"sym":t1["sym"],
                                   "alpha":t1["alpha"],"ret":t1["r"],"ri":ri})

    nombres={
        "A1_top1":"Solo Top1","A2_top1top2":"Top1+Top2 70/30",
        "A3_entrada":"+ Entrada 70/30","A4_ema200":"+ EMA200",
        "A5_vix_iwda":"+ VIX->IWDA","A6_vix_def":"+ VIX->Def",
        "A7_concentracion":"+ Concentracion","A8_fuerza1m":"+ Fuerza rel 1M",
        "B1_top1":"Solo Top1","B2_top1top2":"Top1+Top2 70/30",
        "B3_entrada":"+ Entrada 70/30","B4_ema200":"+ EMA200",
        "B5_vix_iwda":"+ VIX->IWDA","B6_vix_def":"+ VIX->Def",
        "B7_concentracion":"+ Concentracion","B8_fuerza1m":"+ Fuerza rel 1M",
    }

    print(f"\n{'='*90}")
    print("TABLA COMPARATIVA")
    print(f"{'='*90}")
    print(f"\n  {'Modelo':25s} {'Base':11s} {'Alpha':>8} {'Bate%':>6} {'p_NW':>7}  {'Sig':12s} {'M1(17-21)':>10} {'M2(22-26)':>10}")
    print(f"  {'-'*88}")

    resultados={}
    prev_base=""
    for key in modelos_def:
        snaps=series[key]
        base="A (sin skip)" if key.startswith("A") else "B (skip-1) "
        if base!=prev_base:
            print(f"\n  BASE {base}:")
            prev_base=base
        am,bate,pv=calcular_stats(snaps)
        if am is None: continue
        m1=[s for s in snaps if datetime.date.fromisoformat(s["date"])<SPLIT_DATE]
        m2=[s for s in snaps if datetime.date.fromisoformat(s["date"])>=SPLIT_DATE]
        am1,_,pv1=calcular_stats(m1)
        am2,_,pv2=calcular_stats(m2)
        mejor=" ← MEJOR" if pv and pv<0.0483 else ""
        print(f"  {nombres[key]:25s} {'A' if key.startswith('A') else 'B':11s} "
              f"{am:>+7.2f}% {bate:>5.1f}% {str(pv):>7s}  {sig(pv):12s} "
              f"{(str(am1)+'%') if am1 else '---':>10s} {(str(am2)+'%') if am2 else '---':>10s}{mejor}")
        resultados[key]={"nombre":nombres[key],"alpha":am,"bate":bate,"pvalue_nw":pv,
                        "mitad1":am1,"mitad2":am2}

    print(f"\n{'='*90}")
    print("SIMULACION DCA — €500/mes siguiendo cada modelo vs IWDA")
    print(f"{'='*90}")
    print(f"\n  {'Modelo':25s} {'Base':11s} {'Sistema':>12s} {'IWDA':>12s} {'Alpha €':>10s}")
    print(f"  {'-'*72}")

    prev_base=""
    for key in modelos_def:
        snaps=series[key]
        if not snaps: continue
        base="A (sin skip)" if key.startswith("A") else "B (skip-1) "
        if base!=prev_base:
            print(f"\n  BASE {base}:")
            prev_base=base
        cartera=0.0; bench=0.0; n_valid=0
        for s in snaps:
            ed=datetime.date.fromisoformat(s["date"])
            sym=s["sym"]
            if sym=="IWDA":
                pe_s=price_at_date(iwda_p,iwda_d,ed); pt_s=iwda_p[-1]
            else:
                data=etf_data.get(sym)
                if not data: continue
                pe_s=price_at_date(data["prices"],data["dates"],ed); pt_s=data["prices"][-1]
            pe_iw=price_at_date(iwda_p,iwda_d,ed); pt_iw=iwda_p[-1]
            if not all([pe_s,pt_s,pe_iw,pt_iw]) or pe_s<=0 or pe_iw<=0: continue
            cartera+=APORTACION*(1+(pt_s/pe_s-1))
            bench+=APORTACION*(1+(pt_iw/pe_iw-1))
            n_valid+=1
        if n_valid==0: continue
        ae=round(cartera-bench,0)
        mejor=" ←" if ae>0 else ""
        print(f"  {nombres[key]:25s} {'A' if key.startswith('A') else 'B':11s} "
              f"€{cartera:>9,.0f}  €{bench:>9,.0f}  €{ae:>+8,.0f}{mejor}")

    out={"fecha":TODAY.isoformat(),"n_meses":len(all_months_data),"resultados":resultados}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*90}")
    print("REFERENCIA Factor5 (B1_top1): alpha=+3.02% p_NW=0.0483")
    mejores=[(v["alpha"],k,v["pvalue_nw"]) for k,v in resultados.items()
             if v["pvalue_nw"] and v["pvalue_nw"]<0.0483]
    if mejores:
        print(f"\nModelos que MEJORAN al Factor5:")
        for am,k,pv in sorted(mejores,reverse=True):
            print(f"  {k} ({nombres[k]}): alpha={am:+.2f}% p_NW={pv}")
    else:
        print(f"\nNingun modelo mejora al Factor5 (B1_top1)")
    print(f"{'='*90}")

if __name__=="__main__":
    main()
PYEOF
