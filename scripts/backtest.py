#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest.py v10 — Backtest profesional con rolling window + splicing.

BACKTEST A — Calidad de señal mensual:
  Ventana calibracion: 5 anos deslizandose mes a mes
  Señales completamente independientes (sin solapamiento)
  P-value via bootstrap sobre ~200 señales

BACKTEST B — Simulacion real de cartera:
  500/mes siguiendo señales, capital nunca se vende
  Comparacion vs 500/mes en IWDA en euros reales

SPLICING:
  URNM → NLR como proxy pre-2019
  Validado con correlacion minima 0.65
  Escalado por volatilidad
"""

import json, math, os, random, datetime, urllib.request

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "backtest.json")
UA          = {"User-Agent": "Mozilla/5.0 (compatible; Backtest/10.0)"}
TODAY       = datetime.date.today()
APORTACION  = 500
N_BOOTSTRAP = 1000
WINDOW_YEARS= 5
random.seed(42)

BACKTEST_UNIVERSE = [
    ("SMH",          "SMH",  "Semiconductores",  "growth_rates_sensitive"),
    ("IBB",          "IBB",  "Biotecnologia",     "growth_rates_sensitive"),
    ("ITA",          "ITA",  "Defensa",           "defensive_government"),
    ("IGV",          "IGV",  "Software y Cloud",  "growth_rates_sensitive"),
    ("VHT",          "VHT",  "Salud",             "defensive_demographics"),
    ("PHO",          "PHO",  "Agua",              "water_scarcity"),
    ("XBI",          "XBI",  "Biotecnologia",     "growth_rates_sensitive"),
    ("IHI",          "IHI",  "Salud",             "defensive_demographics"),
    ("ICLN",         "ICLN", "Energia Limpia",    "clean_energy"),
    ("GRID",         "GRID", "Infraestructura",   "rates_debt_sensitive"),
    ("COPX",         "COPX", "Cobre y Metales",   "copper_transition"),
    ("LIT",          "LIT",  "Litio y Baterias",  "copper_transition"),
    ("INDA",         "INDA", "India",             "em_dollar_sensitive"),
    ("ROBO",         "ROBO", "Robotica e IA",     "growth_rates_sensitive"),
    ("CIBR",         "CIBR", "Ciberseguridad",    "defensive_growth"),
    ("PAVE",         "PAVE", "Infraestructura",   "rates_debt_sensitive"),
    ("URNM_SPLICED", "URNM", "Uranio y Nuclear",  "uranium_spot"),
]

SPLICE_CONFIG = {
    "URNM_SPLICED": {
        "real_symbol":  "URNM",
        "proxy_symbol": "NLR",
        "real_start":   "2019-12-03",
        "min_corr":     0.65,
    }
}

BENCHMARK = "IWDA.AS"

def _get(url, timeout=25):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def load_from_cache(symbol):
    path=os.path.join(CACHE,f"{symbol.replace('.','-')}.json")
    if os.path.exists(path):
        with open(path,encoding="utf-8") as f: d=json.load(f)
        if d.get("dates") and d.get("prices"): return d["prices"],d["dates"]
    return None,None

def fetch_yahoo_max(symbol):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=max&interval=1d"
    try:
        d=_get(url); res=d["chart"]["result"][0]
        ts=res.get("timestamp") or []
        cls=(res.get("indicators") or {}).get("quote",[{}])[0].get("close") or []
        pairs={}
        for t,c in zip(ts,cls):
            if c is None: continue
            pairs[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")]=float(c)
        series=sorted(pairs.items())
        return [p for _,p in series],[d for d,_ in series]
    except: return None,None

def load_series(symbol):
    p,d=load_from_cache(symbol)
    if p and len(p)>100: return p,d
    print(f"    Descargando {symbol}...")
    return fetch_yahoo_max(symbol)

def pearson_corr(x,y):
    n=min(len(x),len(y))
    if n<20: return 0.0
    x,y=x[-n:],y[-n:]
    mx,my=sum(x)/n,sum(y)/n
    cov=sum((x[i]-mx)*(y[i]-my) for i in range(n))/n
    sx=math.sqrt(sum((v-mx)**2 for v in x)/n)
    sy=math.sqrt(sum((v-my)**2 for v in y)/n)
    return cov/(sx*sy) if sx>0 and sy>0 else 0.0

def calc_returns(prices):
    return [prices[i]/prices[i-1]-1 for i in range(1,len(prices))] if len(prices)>=2 else []

def calc_vol(returns):
    if len(returns)<5: return 0.20
    mean=sum(returns)/len(returns)
    sd=math.sqrt(sum((r-mean)**2 for r in returns)/(len(returns)-1))
    return sd*(252**0.5)

def build_spliced_series(etf_id):
    cfg=SPLICE_CONFIG[etf_id]
    real_sym=cfg["real_symbol"]; proxy_sym=cfg["proxy_symbol"]
    real_start=cfg["real_start"]; min_corr=cfg["min_corr"]
    print(f"  Splicing {real_sym} con {proxy_sym}...")
    real_p,real_d=load_series(real_sym)
    proxy_p,proxy_d=load_series(proxy_sym)
    if not real_p or not proxy_p: return None,None
    ri=next((i for i,d in enumerate(real_d) if d>=real_start),None)
    pi=next((i for i,d in enumerate(proxy_d) if d>=real_start),None)
    if ri is None or pi is None: return None,None
    rr=calc_returns(real_p[ri:]); pr=calc_returns(proxy_p[pi:])
    n_ov=min(len(rr),len(pr))
    if n_ov<60: return None,None
    corr=pearson_corr(rr[:n_ov],pr[:n_ov])
    if corr<min_corr:
        print(f"    Proxy rechazado corr={corr:.2f} < {min_corr}"); return real_p,real_d
    scale=calc_vol(rr[:n_ov])/calc_vol(pr[:n_ov]) if calc_vol(pr[:n_ov])>0 else 1.0
    print(f"    corr={corr:.2f} scale={scale:.2f} solapamiento={n_ov}d")
    pre_rets=[r*scale for r in calc_returns(proxy_p[:pi])]
    pre_dates=proxy_d[1:pi]
    post_rets=calc_returns(real_p[ri:]); post_dates=real_d[ri+1:]
    sp=[100.0]
    for r in pre_rets+post_rets: sp.append(sp[-1]*(1+r))
    sd=[proxy_d[0]]+pre_dates+post_dates
    ml=min(len(sp),len(sd)); sp=sp[:ml]; sd=sd[:ml]
    print(f"    Sintetica: {len(sp)}d | {sd[0]} → {sd[-1]}")
    return sp,sd

def ema_n(prices,n):
    if len(prices)<n: return None
    k=2.0/(n+1); ema=sum(prices[:n])/n
    for p in prices[n:]: ema=p*k+ema*(1-k)
    return ema

def ret_n(prices,n):
    if len(prices)<n+1: return None
    return (prices[-1]/prices[-(n+1)]-1)*100

def vol_std(prices,n=252):
    n=min(n,len(prices)-1)
    if n<5: return 20.0
    rets=[prices[i]/prices[i-1]-1 for i in range(len(prices)-n,len(prices))]
    mean=sum(rets)/len(rets)
    sd=math.sqrt(sum((r-mean)**2 for r in rets)/(len(rets)-1))
    return max(5.0,sd*math.sqrt(252)*100)

def drawdown_from_max(prices,n=252):
    if len(prices)<2: return None
    window=prices[-min(n,len(prices)):]; peak=max(window)
    return round((prices[-1]/peak-1)*100,2) if peak>0 else None

def drawdown_alltime(prices):
    if len(prices)<2: return None
    peak=max(prices)
    return round((prices[-1]/peak-1)*100,2) if peak>0 else None

def consistency_6m(prices):
    if len(prices)<130: return None
    monthly=[]
    for i in range(6):
        start=-(21*(i+1)+1); end=-(21*i+1) if i>0 else -1
        if abs(start)>=len(prices): continue
        p0=prices[start]; p1=prices[end]
        if p0>0: monthly.append(p1/p0-1)
    if len(monthly)<4: return None
    return round(sum(1 for r in monthly if r>0)/len(monthly)*100,0)

def pct_hist(value,series):
    if value is None or not series: return 50.0
    return round(sum(1 for v in series if v<=value)/len(series)*100,1)

def prices_up_to(all_prices,all_dates,target_date):
    cutoff=target_date.isoformat()
    for i,d in enumerate(all_dates):
        if d>cutoff: return all_prices[:i]
    return all_prices[:]

def price_at_date(all_prices,all_dates,target_date):
    target_str=target_date.isoformat()
    best_price=None; best_diff=float('inf')
    for i,d in enumerate(all_dates):
        diff=abs((datetime.date.fromisoformat(d)-datetime.date.fromisoformat(target_str)).days)
        if diff<best_diff: best_diff=diff; best_price=all_prices[i]
        if d>target_str and diff>5: break
    return best_price

def monthly_return(all_prices,all_dates,year,month):
    first_day=datetime.date(year,month,1)
    last_day=datetime.date(year+1,1,1)-datetime.timedelta(days=1) if month==12 else datetime.date(year,month+1,1)-datetime.timedelta(days=1)
    p_start=price_at_date(all_prices,all_dates,first_day)
    p_end=price_at_date(all_prices,all_dates,last_day)
    if p_start and p_end and p_start>0: return round((p_end/p_start-1)*100,2)
    return None

def overval_simple(prices):
    sc=0
    if len(prices)>=252:
        m3=ret_n(prices,63); m3h=[]; n=len(prices)
        for i in range(1,min(252,n-63)):
            r=ret_n(prices[:n-i],63)
            if r is not None: m3h.append(r)
        if m3 is not None and m3h:
            avg=sum(m3h)/len(m3h)
            if avg>0 and m3>avg*3: sc+=1
            elif avg>0 and m3>avg*2: sc+=0.5
    dat=drawdown_alltime(prices)
    if dat is not None and dat>-2: sc+=1
    elif dat is not None and dat>-5: sc+=0.5
    if sc>=2: return 0.5
    elif sc>=1: return 0.7
    elif sc>=0.5: return 0.85
    return 1.0

def score_at_date(prices,iwda_prices):
    if not prices or len(prices)<60: return None
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    rs=None; rsh=[]
    if iwda_prices and len(iwda_prices)>=126:
        iw=iwda_prices[-wd:] if len(iwda_prices)>wd else iwda_prices
        re=ret_n(pw,min(126,n-1)); ri=ret_n(iw,min(126,len(iw)-1))
        if re is not None and ri is not None: rs=(re-ri)/(vol/20.0)
        for i in range(126,min(n,756)):
            pe=pw[:n-i+126] if n-i+126>126 else pw[:126]
            pi=iw[:len(iw)-i+126] if len(iw)-i+126>126 else iw[:126]
            ree=ret_n(pe,126); rii=ret_n(pi,126)
            if ree is not None and rii is not None:
                rsh.append((ree-rii)/(vol_std(pe,min(252,len(pe)-1))/20.0))
    prs=pct_hist(rs,rsh)
    e200=ema_n(pw,min(200,n)); de=((pw[-1]/e200-1)*100) if e200 else None
    en=(de/(vol/20.0)) if de else None; eh=[]
    for i in range(1,min(504,n-200)):
        pc=pw[:n-i]; e=ema_n(pc,min(200,len(pc)))
        if e: eh.append(((pc[-1]/e-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pe200=pct_hist(en,eh)
    m6=ret_n(pw,min(126,n-1)); m6n=(m6/(vol/20.0)) if m6 is not None else None; m6h=[]
    for i in range(1,min(756,n-126)):
        pc=pw[:n-i]; r=ret_n(pc,min(126,len(pc)-1))
        if r is not None: m6h.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pm6=pct_hist(m6n,m6h)
    d52=drawdown_from_max(pw,252); d5y=drawdown_alltime(pw)
    ec=d52*0.60+d5y*0.40 if d52 is not None and d5y is not None else d52
    dh=[]
    for i in range(1,min(756,n-252)):
        pc=pw[:n-i]; d=drawdown_from_max(pc,min(252,len(pc)))
        if d is not None: dh.append(-d)
    pen=pct_hist(-ec if ec is not None else None,dh)
    co=consistency_6m(pw); coh=[]
    for i in range(1,min(756,n-130)):
        pc=pw[:n-i]; c=consistency_6m(pc)
        if c is not None: coh.append(c)
    pco=pct_hist(co,coh)
    score=0.25*prs+0.25*pe200+0.20*pm6+0.20*pen+0.10*pco
    m3=ret_n(pw,min(63,n-1))
    if m3 is not None and m3<-10: score*=0.6
    score*=overval_simple(pw)
    return round(score,1)

def macro_score_simple(macro_profile,eval_date):
    halving=datetime.date(2024,4,19)
    mo=(eval_date-halving).days/30.44
    if macro_profile=="crypto_halving":
        if mo<=18: return min(100,100-mo*2)*0.40+50*0.60
        elif mo<=30: return 60
        else: return 45
    elif macro_profile in ("defensive_government","defensive_demographics"): return 65
    elif macro_profile in ("water_scarcity","copper_transition"): return 55
    elif macro_profile=="clean_energy": return 45
    elif macro_profile=="uranium_spot": return 55
    return 50

def bootstrap_pvalue(real_alpha,all_ids,etf_data,iwda_p,iwda_d,eval_months,n_sim=N_BOOTSTRAP):
    print(f"\n  Bootstrap {n_sim} simulaciones...",end=" ",flush=True)
    random_alphas=[]
    for _ in range(n_sim):
        rs=0.0; ri_s=0.0; nm=0
        for year,month in eval_months:
            avail=[eid for eid in all_ids if etf_data[eid]["prices"] and
                   len(prices_up_to(etf_data[eid]["prices"],etf_data[eid]["dates"],datetime.date(year,month,1)))>=252]
            if len(avail)<2: continue
            ch=random.sample(avail,2)
            r1=monthly_return(etf_data[ch[0]]["prices"],etf_data[ch[0]]["dates"],year,month)
            r2=monthly_return(etf_data[ch[1]]["prices"],etf_data[ch[1]]["dates"],year,month)
            ri=monthly_return(iwda_p,iwda_d,year,month)
            if r1 is not None and r2 is not None and ri is not None:
                rs+=r1*0.70+r2*0.30; ri_s+=ri; nm+=1
        if nm>0: random_alphas.append((rs-ri_s)/nm)
    if not random_alphas: print("sin datos"); return None,None,None
    pct=sum(1 for a in random_alphas if a<=real_alpha)/len(random_alphas)*100
    pvalue=round(1-pct/100,4)
    mean_r=round(sum(random_alphas)/len(random_alphas),3)
    print(f"alpha_aleatorio={mean_r:.2f}% | real={real_alpha:.2f}% | pct={pct:.0f}% | p={pvalue}")
    return pvalue,pct,mean_r

def main():
    print("="*65)
    print("BACKTEST v10 — Rolling Window + Splicing")
    print(f"Fecha: {TODAY} | ETFs: {len(BACKTEST_UNIVERSE)}")
    print("="*65)

    print("\nCargando datos...")
    etf_data={}
    for etf_id,symbol,sector,macro_profile in BACKTEST_UNIVERSE:
        print(f"  {etf_id:15s}",end=" ",flush=True)
        if etf_id in SPLICE_CONFIG:
            prices,dates=build_spliced_series(etf_id)
        else:
            prices,dates=load_series(symbol)
        if not prices or len(prices)<252:
            print(f"insuficiente ({len(prices) if prices else 0}d)"); continue
        years=round((datetime.date.fromisoformat(dates[-1])-datetime.date.fromisoformat(dates[0])).days/365.25,1)
        print(f"{len(prices):5d}d | {dates[0]} → {dates[-1]} | {years:.1f}A")
        etf_data[etf_id]={"symbol":symbol,"sector":sector,"macro_profile":macro_profile,"prices":prices,"dates":dates}

    print(f"  {'IWDA':15s}",end=" ",flush=True)
    iwda_p,iwda_d=load_series(BENCHMARK)
    if iwda_p: print(f"{len(iwda_p):5d}d | {iwda_d[0]} → {iwda_d[-1]}")
    else: print("ERROR"); return
    if not etf_data: print("ERROR: sin datos"); return

    min_start=max(datetime.date.fromisoformat(d["dates"][0]) for d in etf_data.values() if len(d["dates"])>WINDOW_YEARS*252)
    backtest_start=datetime.date(min_start.year+WINDOW_YEARS,min_start.month,1)
    eval_months=[]; d=backtest_start
    while d<=TODAY.replace(day=1):
        eval_months.append((d.year,d.month))
        d=datetime.date(d.year+1,1,1) if d.month==12 else datetime.date(d.year,d.month+1,1)

    print(f"\nPeriodo: {backtest_start} → {TODAY} | {len(eval_months)} meses")

    # BACKTEST A
    print("\n"+"─"*65)
    print("BACKTEST A — Calidad de señal mensual")
    print("─"*65)
    snapshots_a=[]; alpha_sum=0.0; n_valid=0

    for year,month in eval_months:
        eval_date=datetime.date(year,month,1)
        scores=[]
        for eid,data in etf_data.items():
            pt=prices_up_to(data["prices"],data["dates"],eval_date)
            if len(pt)<252: continue
            it=prices_up_to(iwda_p,iwda_d,eval_date)
            st=score_at_date(pt,it)
            if st is None: continue
            sm=macro_score_simple(data["macro_profile"],eval_date)
            sf=round(st*0.85+sm*0.15,1)
            scores.append({"id":eid,"symbol":data["symbol"],"sector":data["sector"],"score":sf})
        if not scores: continue
        seen=set(); sb=[]
        for r in sorted(scores,key=lambda x:-x["score"]):
            if r["sector"] not in seen: seen.add(r["sector"]); sb.append(r)
        if len(sb)<2: continue
        top1=sb[0]; top2=sb[1]
        r1=monthly_return(etf_data[top1["id"]]["prices"],etf_data[top1["id"]]["dates"],year,month)
        r2=monthly_return(etf_data[top2["id"]]["prices"],etf_data[top2["id"]]["dates"],year,month)
        ri=monthly_return(iwda_p,iwda_d,year,month)
        if r1 is None or ri is None: continue
        rp=r1*0.70+r2*0.30 if r2 is not None else r1
        alpha=round(rp-ri,2); bate=r1>ri
        alpha_sum+=alpha; n_valid+=1
        snapshots_a.append({"date":eval_date.isoformat(),
            "top1":{"symbol":top1["symbol"],"sector":top1["sector"],"score":top1["score"]},
            "top2":{"symbol":top2["symbol"],"sector":top2["sector"],"score":top2["score"]},
            "ret_top1":r1,"ret_top2":r2,"ret_ponderado":round(rp,2),
            "ret_iwda":ri,"alpha":alpha,"bate_top1":bate,"score_top1":top1["score"]})

    if not snapshots_a: print("ERROR: sin señales"); return
    alpha_medio=round(alpha_sum/n_valid,3)
    bates=[s["bate_top1"] for s in snapshots_a if s.get("bate_top1") is not None]
    pct_bate=round(sum(1 for b in bates if b)/len(bates)*100,1) if bates else 0
    print(f"\n  Señales: {n_valid} | Alpha: {alpha_medio:+.3f}%/mes ({alpha_medio*12:+.1f}%/año) | Bate IWDA: {pct_bate}%")
    buckets={"alto_70+":[],"medio_55-70":[],"bajo_55-":[]}
    for s in snapshots_a:
        sc=s.get("score_top1",0)
        if sc>=70: buckets["alto_70+"].append(s["alpha"])
        elif sc>=55: buckets["medio_55-70"].append(s["alpha"])
        else: buckets["bajo_55-"].append(s["alpha"])
    print("  Predictividad:")
    for b,alphas in buckets.items():
        if alphas: print(f"    {b:12s}: n={len(alphas):3d} | alpha={round(sum(alphas)/len(alphas),2):+.2f}%")
    all_ids=list(etf_data.keys())
    pvalue,pct_real,mean_rand=bootstrap_pvalue(alpha_medio,all_ids,etf_data,iwda_p,iwda_d,eval_months)
    significance=""
    if pvalue is not None:
        if pvalue<0.05:    significance="✓✓ ESTADISTICAMENTE SIGNIFICATIVO (p<0.05)"
        elif pvalue<0.10:  significance="✓  Marginalmente significativo (p<0.10)"
        elif pvalue<0.20:  significance="~  Debilmente significativo (p<0.20)"
        else:              significance="✗  No significativo — puede ser azar"
    print(f"  P-value: {pvalue} | {significance}")

    # BACKTEST B
    print("\n"+"─"*65)
    print("BACKTEST B — Simulacion real €500/mes")
    print("─"*65)
    cartera_sis=0.0; cartera_iwd=0.0; n_meses_b=0; snapshots_b=[]
    for s in snapshots_a:
        eval_date=datetime.date.fromisoformat(s["date"])
        r1_total=None
        eid1=next((eid for eid in etf_data if etf_data[eid]["symbol"]==s["top1"]["symbol"]),None)
        if eid1:
            pe=price_at_date(etf_data[eid1]["prices"],etf_data[eid1]["dates"],eval_date)
            pt=etf_data[eid1]["prices"][-1]
            if pe and pt and pe>0: r1_total=round((pt/pe-1)*100,2)
        r2_total=None
        eid2=next((eid for eid in etf_data if etf_data[eid]["symbol"]==s["top2"]["symbol"]),None) if s.get("top2") else None
        if eid2:
            pe2=price_at_date(etf_data[eid2]["prices"],etf_data[eid2]["dates"],eval_date)
            pt2=etf_data[eid2]["prices"][-1]
            if pe2 and pt2 and pe2>0: r2_total=round((pt2/pe2-1)*100,2)
        pe_iw=price_at_date(iwda_p,iwda_d,eval_date)
        ri_total=round((iwda_p[-1]/pe_iw-1)*100,2) if pe_iw and pe_iw>0 else None
        if r1_total is None or ri_total is None: continue
        rp_total=r1_total*0.70+r2_total*0.30 if r2_total is not None else r1_total
        cartera_sis+=APORTACION*(1+rp_total/100)
        cartera_iwd+=APORTACION*(1+ri_total/100)
        n_meses_b+=1
        snapshots_b.append({"date":s["date"],"top1_symbol":s["top1"]["symbol"],
            "ret_total":round(rp_total,2),"ret_iwda":ri_total,
            "alpha_total":round(rp_total-ri_total,2),
            "valor_sis":round(APORTACION*(1+rp_total/100),2),
            "valor_iwd":round(APORTACION*(1+ri_total/100),2)})

    total=n_meses_b*APORTACION
    ret_sis=round((cartera_sis/total-1)*100,2) if total>0 else 0
    ret_iwd=round((cartera_iwd/total-1)*100,2) if total>0 else 0
    alpha_b=round(ret_sis-ret_iwd,2)
    print(f"\n  {n_meses_b} meses | €{total:,.0f} invertidos")
    print(f"  Sistema: €{cartera_sis:,.0f} (+{ret_sis}%)")
    print(f"  IWDA:    €{cartera_iwd:,.0f} (+{ret_iwd}%)")
    print(f"  Alpha:   {alpha_b:+.2f}% | €{cartera_sis-cartera_iwd:+,.0f}")
    print(f"  {'✓ SISTEMA GANA' if alpha_b>0 else '✗ IWDA GANA'}")

    summary={"fecha":TODAY.isoformat(),"model_version":"10.0","universo":len(etf_data),
        "metodologia":{"rolling_window_anos":WINDOW_YEARS,
            "backtest_A":"Señales mensuales independientes, ventana 1 mes, p-value bootstrap",
            "backtest_B":"Simulacion €500/mes acumulativo hasta hoy",
            "splicing":"URNM con proxy NLR pre-2019, correlacion minima 0.65"},
        "backtest_A":{"n_senales":n_valid,"alpha_medio_mes":alpha_medio,
            "alpha_anualizado":round(alpha_medio*12,2),"pct_bate_iwda":pct_bate,
            "predictividad":{b:{"n":len(a),"alpha_medio":round(sum(a)/len(a),2) if a else None} for b,a in buckets.items()},
            "bootstrap":{"pvalue":pvalue,"percentil_real":pct_real,"alpha_medio_aleatorio":mean_rand,
                         "n_simulaciones":N_BOOTSTRAP,"significancia":significance}},
        "backtest_B":{"n_meses":n_meses_b,"total_invertido":total,
            "valor_sistema":round(cartera_sis,2),"valor_iwda":round(cartera_iwd,2),
            "ret_sistema":ret_sis,"ret_iwda":ret_iwd,"alpha_total":alpha_b,
            "diferencia_euros":round(cartera_sis-cartera_iwd,2)},
        "interpretacion":(f"A({n_valid}señales): alpha {alpha_medio:+.3f}%/mes ({alpha_medio*12:+.1f}%/año). {significance}. "
            f"B({n_meses_b}meses): sistema €{cartera_sis:,.0f} vs IWDA €{cartera_iwd:,.0f} (alpha {alpha_b:+.2f}%)")}

    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f: json.dump({"updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z","summary":summary,"snapshots_a":snapshots_a,"snapshots_b":snapshots_b},f,ensure_ascii=False,indent=2)

    print(f"\n{'='*65}")
    print(f"BACKTEST A: {n_valid}señales | alpha {alpha_medio:+.3f}%/mes | p={pvalue} | {significance}")
    print(f"BACKTEST B: €{cartera_sis:,.0f} sistema vs €{cartera_iwd:,.0f} IWDA (€{cartera_sis-cartera_iwd:+,.0f})")
    print(f"{'='*65}")

if __name__=="__main__":
    main()
