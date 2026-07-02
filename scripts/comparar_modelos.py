#!/usr/bin/env python3
"""
comparar_modelos.py — Calcula p_NW por mitad para A1, A3, B1, B3.
Usa exactamente el mismo codigo del Factor5 validado.
"""

import json, math, os, datetime

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
TODAY       = datetime.date.today()
WINDOW_YEARS= 5
NW_LAGS     = 2
SPLIT_DATE  = datetime.date(2022, 1, 1)
HORIZONTE   = 3

UNIVERSE = ["SMH","IBB","ITA","IGV","VHT","PHO","IHI","ICLN","GRID",
            "COPX","LIT","INDA","ROBO","CIBR","PAVE"]
BENCHMARK = "IWDA.AS"

def load(symbol):
    path=os.path.join(CACHE,f"{symbol.replace('.','-')}.json")
    if os.path.exists(path):
        with open(path) as f: d=json.load(f)
        if d.get("dates") and d.get("prices"): return d["prices"],d["dates"]
    return None,None

def ret_range(p,s,e):
    if abs(s)>=len(p) or abs(e)>=len(p): return None
    p0=p[s]; p1=p[e]
    return (p1/p0-1)*100 if p0>0 else None

def vol_std(p,n=252):
    n=min(n,len(p)-1)
    if n<5: return 20.0
    r=[p[i]/p[i-1]-1 for i in range(len(p)-n,len(p))]
    m=sum(r)/len(r)
    return max(5.0,math.sqrt(sum((x-m)**2 for x in r)/(len(r)-1))*math.sqrt(252)*100)

def pct_hist(v,s):
    if v is None or not s: return 50.0
    return round(sum(1 for x in s if x<=v)/len(s)*100,1)

def prices_up_to(p,d,target):
    cutoff=target.isoformat()
    for i,dt in enumerate(d):
        if dt>cutoff: return p[:i]
    return p[:]

def price_at(p,d,target):
    ts=target.isoformat(); bp=None; bd=float('inf')
    for i,dt in enumerate(d):
        diff=abs((datetime.date.fromisoformat(dt)-datetime.date.fromisoformat(ts)).days)
        if diff<bd: bd=diff; bp=p[i]
        if dt>ts and diff>5: break
    return bp

def period_ret(p,d,y,m,hz=3):
    first=datetime.date(y,m,1)
    em=m+hz; ey=y
    while em>12: em-=12; ey+=1
    last=datetime.date(ey,em,1)-datetime.timedelta(days=1)
    p0=price_at(p,d,first); p1=price_at(p,d,last)
    return round((p1/p0-1)*100,2) if p0 and p1 and p0>0 else None

def nw_pvalue(alphas,lags=NW_LAGS):
    n=len(alphas)
    if n<10: return None
    mean=sum(alphas)/n
    var=sum((a-mean)**2 for a in alphas)/n
    for lag in range(1,lags+1):
        cov=sum((alphas[i]-mean)*(alphas[i-lag]-mean) for i in range(lag,n))/n
        var+=2*(1.0-lag/(lags+1))*cov
    se=math.sqrt(max(var,0)/n) if var>0 else 0.0001
    t=mean/se
    def ncdf(x):
        t_=1.0/(1.0+0.2316419*abs(x))
        poly=(0.31938153*t_-0.356563782*t_**2+1.781477937*t_**3
              -1.821255978*t_**4+1.330274429*t_**5)
        return 1.0-(1.0/math.sqrt(2*math.pi))*math.exp(-x**2/2)*poly if x>=0 else ncdf(-x)
    return round(min(1.0,2*(1.0-ncdf(abs(t)))),4)

def momentum_score(prices, skip):
    """Exactamente igual que Factor5."""
    if not prices or len(prices)<273: return None
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    if n<273: return None
    if skip==1:
        s=-273; e=-21
    else:
        s=-252; e=-1
    if abs(s)>=n or abs(e)>=n: return None
    m=ret_range(pw,s,e)
    if m is None: return None
    mn=m/(vol/20.0)
    hist=[]
    min_n=abs(s)
    for i in range(min_n,min(n,min_n+483)):
        pc=pw[:n-i]
        if len(pc)>=min_n:
            r=ret_range(pc,s,e)
            if r is not None:
                hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return pct_hist(mn,hist)

def entrada_score(prices):
    """Igual que Factor6/Maestro."""
    if not prices or len(prices)<252: return None
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    if n<252: return None
    mx=max(pw[-252:])
    if mx<=0: return None
    dd=(pw[-1]/mx-1)*100; dd_n=dd/(vol/20.0)
    hist=[]
    for i in range(252,min(n,756)):
        pc=pw[:n-i]
        if len(pc)>=252:
            m=max(pc[-252:])
            if m>0:
                hist.append(((pc[-1]/m-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return round(100-pct_hist(dd_n,hist),1)

def run_model(etf_data, iwda_p, iwda_d, months, skip, peso_entrada):
    snaps=[]; snaps_m1=[]; snaps_m2=[]
    for y,m in months:
        ed=datetime.date(y,m,1)
        ri=period_ret(iwda_p,iwda_d,y,m,HORIZONTE)
        if ri is None: continue
        scores=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            ms=momentum_score(pt,skip)
            if ms is None: continue
            r=period_ret(data["prices"],data["dates"],y,m,HORIZONTE)
            if r is None: continue
            if peso_entrada>0:
                es=entrada_score(pt)
                if es is None: es=50.0
                sc=ms*(1-peso_entrada)+es*peso_entrada
            else:
                sc=ms
            scores.append({"sym":sym,"score":sc,"alpha":round(r-ri,2)})
        if not scores: continue
        scores.sort(key=lambda x:-x["score"])
        t1=scores[0]
        snap={"date":ed.isoformat(),"year":y,"sym":t1["sym"],"alpha":t1["alpha"]}
        snaps.append(snap)
        if ed<SPLIT_DATE: snaps_m1.append(snap)
        else: snaps_m2.append(snap)

    def stats(ss):
        if not ss: return None,None
        als=[x["alpha"] for x in ss]
        return round(sum(als)/len(als),3), nw_pvalue(als)

    ag,pg=stats(snaps)
    am1,pm1=stats(snaps_m1)
    am2,pm2=stats(snaps_m2)
    return ag,pg,am1,pm1,am2,pm2,len(snaps)

def main():
    print("Cargando datos...")
    etf_data={}
    for sym in UNIVERSE:
        p,d=load(sym)
        if p and len(p)>500:
            etf_data[sym]={"prices":p,"dates":d}
            print(f"  {sym:8s} {len(p):5d}d")
    iwda_p,iwda_d=load(BENCHMARK)
    if not iwda_p: print("ERROR sin IWDA"); return

    starts=sorted([datetime.date.fromisoformat(d["dates"][0]) for d in etf_data.values()])
    idx=min(int(len(starts)*0.75),len(starts)-1)
    bt=datetime.date(starts[idx].year+WINDOW_YEARS,starts[idx].month,1)
    months=[]; dt=bt
    while dt<=TODAY.replace(day=1):
        months.append((dt.year,dt.month))
        dt=datetime.date(dt.year+1,1,1) if dt.month==12 else datetime.date(dt.year,dt.month+1,1)
    months=[m for m in months
            if datetime.date(m[0],m[1],1)<=TODAY.replace(day=1)-datetime.timedelta(days=HORIZONTE*32)]
    print(f"\nDesde {bt} | {len(months)} señales | horizonte {HORIZONTE}M")

    modelos=[
        ("A1 (sin skip, puro)",     0, 0.00),
        ("A3 (sin skip + entrada)", 0, 0.30),
        ("B1 (skip-1, puro)",       1, 0.00),
        ("B3 (skip-1 + entrada)",   1, 0.30),
    ]

    print(f"\n{'='*85}")
    print(f"COMPARACION A1 A3 B1 B3 — p_NW global y por mitad")
    print(f"{'='*85}")
    print(f"\n{'Modelo':25s} {'N':>4} {'Alpha':>8} {'p_NW':>7} "
          f"{'M1':>7} {'p_M1':>7} {'M2':>7} {'p_M2':>7} {'Diff':>6}")
    print(f"  {'-'*80}")

    for nombre,sk,pe in modelos:
        ag,pg,am1,pm1,am2,pm2,n=run_model(etf_data,iwda_p,iwda_d,months,sk,pe)
        if ag is None: continue
        diff=round(abs((am1 or 0)-(am2 or 0)),3)
        sig=""
        if pg and pg<0.05: sig=" ✓✓"
        elif pg and pg<0.10: sig=" ✓"
        print(f"  {nombre:25s} {n:>4} {ag:>+7.3f}% {str(pg):>7}{sig} "
              f"{(am1 or 0):>+6.3f}% {str(pm1):>7} "
              f"{(am2 or 0):>+6.3f}% {str(pm2):>7} "
              f"{diff:>5.3f}%")

    print(f"\n{'='*85}")
    print(f"REFERENCIA F5 (B1): alpha=+2.98% p_NW=0.0483")
    print(f"REFERENCIA M  (B3): alpha=+3.44% p_NW=0.0447")
    print(f"REFERENCIA M  (A3): alpha=+3.84% p_NW=0.0231")
    print(f"{'='*85}")

if __name__=="__main__":
    main()
