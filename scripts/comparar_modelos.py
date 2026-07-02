#!/usr/bin/env python3
"""Calcula p_NW por mitad para A1, A3, B1, B3."""

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

def prices_up_to(p,d,t):
    c=t.isoformat()
    for i,dt in enumerate(d):
        if dt>c: return p[:i]
    return p[:]

def price_at(p,d,t):
    ts=t.isoformat(); bp=None; bd=float('inf')
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
        p=(0.31938153*t_-0.356563782*t_**2+1.781477937*t_**3
           -1.821255978*t_**4+1.330274429*t_**5)
        return 1.0-(1.0/math.sqrt(2*math.pi))*math.exp(-x**2/2)*p if x>=0 else ncdf(-x)
    return round(min(1.0,2*(1.0-ncdf(abs(t)))),4)

def mom_score(pt, sk):
    wd=WINDOW_YEARS*252
    pw=pt[-wd:] if len(pt)>wd else pt
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    lb_d=273; sk_d=int(sk*21)
    if n<lb_d+sk_d: return None
    s=-(lb_d+sk_d); e=-sk_d if sk_d>0 else -1
    m=ret_range(pw,s,e)
    if m is None: return None
    mn=m/(vol/20.0)
    hist=[]
    for i in range(lb_d+sk_d,min(n,lb_d+sk_d+400)):
        pc=pw[:n-i]
        if len(pc)>=lb_d+sk_d:
            r=ret_range(pc,s,e)
            if r is not None: hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return pct_hist(mn,hist)

def entrada_score(pt):
    wd=WINDOW_YEARS*252
    pw=pt[-wd:] if len(pt)>wd else pt
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

def run_model(etf_data, iwda_p, iwda_d, months, sk, pe):
    snaps=[]; snaps_m1=[]; snaps_m2=[]
    for y,m in months:
        ed=datetime.date(y,m,1)
        ri=period_ret(iwda_p,iwda_d,y,m,HORIZONTE)
        if ri is None: continue
        scores=[]
        for sym,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],ed)
            if len(pt)<300: continue
            ms=mom_score(pt,sk)
            if ms is None: continue
            r=period_ret(data["prices"],data["dates"],y,m,HORIZONTE)
            if r is None: continue
            if pe>0:
                es=entrada_score(pt)
                sc=ms*(1-pe)+es*pe
            else:
                sc=ms
            scores.append({"sym":sym,"score":sc,"alpha":round(r-ri,2)})
        if not scores: continue
        scores.sort(key=lambda x:-x["score"])
        t1=scores[0]
        snap={"date":ed.isoformat(),"year":y,"alpha":t1["alpha"]}
        snaps.append(snap)
        if ed<SPLIT_DATE: snaps_m1.append(snap)
        else: snaps_m2.append(snap)

    def s(ss):
        if not ss: return None,None
        als=[x["alpha"] for x in ss]
        return round(sum(als)/len(als),3), nw_pvalue(als)

    am_g,pv_g=s(snaps)
    am_m1,pv_m1=s(snaps_m1)
    am_m2,pv_m2=s(snaps_m2)
    return am_g,pv_g,am_m1,pv_m1,am_m2,pv_m2

def main():
    print("Cargando...")
    etf_data={}
    for sym in UNIVERSE:
        p,d=load(sym)
        if p and len(p)>500: etf_data[sym]={"prices":p,"dates":d}
    iwda_p,iwda_d=load(BENCHMARK)

    starts=sorted([datetime.date.fromisoformat(d["dates"][0]) for d in etf_data.values()])
    idx=min(int(len(starts)*0.75),len(starts)-1)
    bt=datetime.date(starts[idx].year+WINDOW_YEARS,starts[idx].month,1)
    months=[]; dt=bt
    while dt<=TODAY.replace(day=1):
        months.append((dt.year,dt.month))
        dt=datetime.date(dt.year+1,1,1) if dt.month==12 else datetime.date(dt.year,dt.month+1,1)
    months=[m for m in months
            if datetime.date(m[0],m[1],1)<=TODAY.replace(day=1)-datetime.timedelta(days=HORIZONTE*32)]

    print(f"\n{'='*70}")
    print(f"COMPARACION A1 A3 B1 B3 — p_NW por mitad")
    print(f"{'='*70}")
    print(f"\n{'Modelo':4} {'SK':3} {'PE':5} {'Alpha':>8} {'p_NW':>7} {'M1':>7} {'p_M1':>7} {'M2':>7} {'p_M2':>7} {'Diff':>6}")
    print(f"  {'-'*72}")

    modelos=[
        ("A1", 0, 0.00),
        ("A3", 0, 0.30),
        ("B1", 1, 0.00),
        ("B3", 1, 0.30),
    ]

    for nombre,sk,pe in modelos:
        ag,pg,am1,pm1,am2,pm2=run_model(etf_data,iwda_p,iwda_d,months,sk,pe)
        diff=round(abs(am1-am2),3) if am1 and am2 else None
        print(f"  {nombre:4} {sk:3d} {pe:5.2f} "
              f"{ag:>+7.3f}% {str(pg):>7} "
              f"{am1:>+6.3f}% {str(pm1):>7} "
              f"{am2:>+6.3f}% {str(pm2):>7} "
              f"{str(diff):>6}%")

    print(f"\n{'='*70}")

if __name__=="__main__":
    main()
