
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest walk-forward v9 — con p-value estadistico.

Novedades:
  - Bootstrap de 1000 portfolios aleatorios para calcular p-value del alpha.
  - Bate = Top1 supera IWDA. Distribucion 70/30.
  - Cartera acumulativa €500/mes hasta hoy.
  - Universo ampliado a 13 sectores.
"""

import json, math, os, random, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI  = os.path.join(ROOT, "universe.json")
OUT  = os.path.join(ROOT, "data", "backtest.json")
UA   = {"User-Agent": "Mozilla/5.0 (compatible; Backtest/9.0)"}

BITCOIN_HALVING = datetime.date(2024,4,19)
W_TECH  = {"rel_strength":0.25,"ema200":0.25,"mom6m":0.20,"entry":0.20,"consistency":0.10}
W_FINAL = {"tech":0.85,"macro":0.15}
TODAY   = datetime.date.today()
APORTACION = 500
N_BOOTSTRAP = 1000
random.seed(42)

def _get(url,timeout=25):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_5y(symbol):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5y&interval=1d"
    try:
        d=_get(url); res=d["chart"]["result"][0]
        ts=res.get("timestamp") or []
        cls=(res.get("indicators") or {}).get("quote",[{}])[0].get("close") or []
        pairs={}
        for t,c in zip(ts,cls):
            if c is None: continue
            pairs[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")]=float(c)
        series=sorted(pairs.items())
        return [c for _,c in series],[d for d,_ in series]
    except: return None,None

def ema_n(prices,n):
    if len(prices)<n: return None
    k=2.0/(n+1); ema=sum(prices[:n])/n
    for p in prices[n:]: ema=p*k+ema*(1-k)
    return ema

def ret_n(prices,n):
    if len(prices)<n+1: return None
    p0,p1=prices[-(n+1)],prices[-1]
    return (p1/p0-1)*100 if p0>0 else None

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

def prices_up_to(all_prices,all_dates,target):
    cutoff=target.isoformat()
    for i,d in enumerate(all_dates):
        if d>cutoff: return all_prices[:i]
    return all_prices[:]

def return_to_today(all_prices,all_dates,from_date):
    from_str=from_date.isoformat(); si=None
    for i,d in enumerate(all_dates):
        if d>=from_str: si=i; break
    if si is None or si>=len(all_prices)-1: return None
    p0=all_prices[si]; p1=all_prices[-1]
    return round((p1/p0-1)*100,2) if p0>0 else None

def months_held(from_date):
    return round((TODAY-from_date).days/30.44,1)

def overval_simple(prices):
    sc=0
    if len(prices)>=252:
        m3=ret_n(prices,63); m3h=[]; n=len(prices)
        for i in range(1,min(504,n-63)):
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
    n=len(prices); vol=vol_std(prices,min(252,n-1))
    rs=None; rsh=[]
    if iwda_prices and len(iwda_prices)>=126:
        re=ret_n(prices,min(126,n-1)); ri=ret_n(iwda_prices,min(126,len(iwda_prices)-1))
        if re is not None and ri is not None: rs=(re-ri)/(vol/20.0)
        for i in range(126,min(n,756)):
            pe=prices[:n-i+126] if n-i+126>126 else prices[:126]
            pi=iwda_prices[:len(iwda_prices)-i+126] if len(iwda_prices)-i+126>126 else iwda_prices[:126]
            ree=ret_n(pe,126); rii=ret_n(pi,126)
            if ree is not None and rii is not None:
                rsh.append((ree-rii)/(vol_std(pe,min(252,len(pe)-1))/20.0))
    prs=pct_hist(rs,rsh)
    e200=ema_n(prices,min(200,n)); de=((prices[-1]/e200-1)*100) if e200 else None
    en=(de/(vol/20.0)) if de else None; eh=[]
    for i in range(1,min(504,n-200)):
        pc=prices[:n-i]; e=ema_n(pc,min(200,len(pc)))
        if e: eh.append(((pc[-1]/e-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pe200=pct_hist(en,eh)
    m6=ret_n(prices,min(126,n-1)); m6n=(m6/(vol/20.0)) if m6 is not None else None; m6h=[]
    for i in range(1,min(756,n-126)):
        pc=prices[:n-i]; r=ret_n(pc,min(126,len(pc)-1))
        if r is not None: m6h.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pm6=pct_hist(m6n,m6h)
    d52=drawdown_from_max(prices,252); dat=drawdown_alltime(prices)
    ec=d52*0.60+dat*0.40 if d52 is not None and dat is not None else d52
    dh=[]
    for i in range(1,min(756,n-252)):
        pc=prices[:n-i]; d=drawdown_from_max(pc,min(252,len(pc)))
        if d is not None: dh.append(-d)
    pen=pct_hist(-ec if ec is not None else None,dh)
    co=consistency_6m(prices); coh=[]
    for i in range(1,min(756,n-130)):
        pc=prices[:n-i]; c=consistency_6m(pc)
        if c is not None: coh.append(c)
    pco=pct_hist(co,coh)
    s=(W_TECH["rel_strength"]*prs+W_TECH["ema200"]*pe200+W_TECH["mom6m"]*pm6+
       W_TECH["entry"]*pen+W_TECH["consistency"]*pco)
    m3=ret_n(prices,min(63,n-1))
    if m3 is not None and m3<-10: s*=0.6
    s*=overval_simple(prices)
    return round(s,1)

def macro_simple(eval_date,mp):
    if mp=="crypto_halving":
        mo=(eval_date-BITCOIN_HALVING).days/30.44
        if mo<=18: return min(100,100-mo*2)*0.40+50*0.60
        elif mo<=30: return 60
        else: return 45
    if mp in ("defensive_government","defensive_demographics"): return 65
    if mp in ("water_scarcity","copper_transition"): return 55
    if mp=="clean_energy": return 45
    return 50

def bootstrap_pvalue(real_alpha,all_etf_ids,etf_data,iwda_p,iwda_d,eval_dates,n_sim=N_BOOTSTRAP):
    print(f"\n  Bootstrap ({n_sim} simulaciones)...",end=" ",flush=True)
    random_alphas=[]
    for sim in range(n_sim):
        cs=0.0; ci=0.0
        for eval_date in eval_dates:
            available=[eid for eid in all_etf_ids
                      if etf_data[eid]["prices"] and
                      len(prices_up_to(etf_data[eid]["prices"],etf_data[eid]["dates"],eval_date))>=60]
            if len(available)<2: continue
            chosen=random.sample(available,2)
            r1=return_to_today(etf_data[chosen[0]]["prices"],etf_data[chosen[0]]["dates"],eval_date)
            r2=return_to_today(etf_data[chosen[1]]["prices"],etf_data[chosen[1]]["dates"],eval_date)
            ri=return_to_today(iwda_p,iwda_d,eval_date)
            if r1 is not None: cs+=350*(1+r1/100)
            else: cs+=350
            if r2 is not None: cs+=150*(1+r2/100)
            else: cs+=150
            if ri is not None: ci+=500*(1+ri/100)
            else: ci+=500
        total=len(eval_dates)*APORTACION
        if total>0 and ci>0:
            random_alphas.append(round((cs/total-1)*100,2)-round((ci/total-1)*100,2))
    if not random_alphas: print("sin datos"); return None,None,None
    pct=sum(1 for a in random_alphas if a<=real_alpha)/len(random_alphas)*100
    pvalue=round(1-pct/100,4)
    mean_random=round(sum(random_alphas)/len(random_alphas),2)
    print(f"alpha medio aleatorio={mean_random}% | real={real_alpha}% | percentil={pct:.0f}% | p-value={pvalue}")
    return pvalue,pct,mean_random

def main():
    with open(UNI,encoding="utf-8") as f: uni_data=json.load(f)
    universe=[e for e in uni_data["etfs"] if e.get("universe","primary")=="primary"]
    print(f"Descargando historico 5A de {len(universe)} ETFs...")
    etf_data={}
    for etf in universe:
        sym=etf["symbol"]; print(f"  {sym}...",end=" ",flush=True)
        prices,dates=fetch_5y(sym)
        if not prices or len(prices)<120: print("sin datos"); continue
        etf_data[etf["id"]]={**etf,"prices":prices,"dates":dates}
        print(f"{len(prices)} dias")
    print("  IWDA...",end=" ")
    iwda_p,iwda_d=fetch_5y("IWDA.AS")
    print(f"{len(iwda_p) if iwda_p else 0} dias")
    if not etf_data: print("ERROR"); return

    eval_dates=[]
    d=TODAY.replace(day=1)
    for _ in range(36):
        d=(d-datetime.timedelta(days=1)).replace(day=1)
        eval_dates.append(d)
    eval_dates=sorted(eval_dates)

    print(f"\nCalculando backtest ({len(eval_dates)} fechas) hasta hoy ({TODAY})...")
    snapshots=[]; cartera_sis=0.0; cartera_iwd=0.0

    for eval_date in eval_dates:
        m=months_held(eval_date)
        print(f"\n  === {eval_date} (hace {m:.0f}M) ===")
        scores=[]
        for eid,edata in etf_data.items():
            pc=prices_up_to(edata["prices"],edata["dates"],eval_date)
            if len(pc)<60: continue
            ic=prices_up_to(iwda_p,iwda_d,eval_date) if iwda_p else None
            st=score_at_date(pc,ic)
            if st is None: continue
            sm=macro_simple(eval_date,edata.get("macro_profile",""))
            sf=round(st*W_FINAL["tech"]+sm*W_FINAL["macro"],1)
            scores.append({"id":eid,"name":edata["name"],"symbol":edata["symbol"],
                "sector":edata["sector"],"score_final":sf})
        if not scores: continue
        sector_best={}
        for r in sorted(scores,key=lambda x:x["score_final"],reverse=True):
            s=r["sector"]
            if s not in sector_best: sector_best[s]=r
        sr=sorted(sector_best.values(),key=lambda x:x["score_final"],reverse=True)
        top1=sr[0]; top2=sr[1] if len(sr)>1 else None
        e1=etf_data[top1["id"]]
        r1=return_to_today(e1["prices"],e1["dates"],eval_date)
        r2=None
        if top2:
            e2=etf_data[top2["id"]]
            r2=return_to_today(e2["prices"],e2["dates"],eval_date)
        ri=return_to_today(iwda_p,iwda_d,eval_date)
        rp=round(r1*0.70+r2*0.30,2) if r1 is not None and r2 is not None else r1
        bate=r1>ri if r1 is not None and ri is not None else None
        alpha=round(rp-ri,2) if rp is not None and ri is not None else None
        print(f"    #1 {top1['symbol']:10s} score={top1['score_final']:5.1f} ret={str(r1)+'%' if r1 else '?'}")
        if top2: print(f"    #2 {top2['symbol']:10s} score={top2['score_final']:5.1f} ret={str(r2)+'%' if r2 else '?'}")
        print(f"    → 70/30: {rp}% | IWDA: {ri}% | Alpha: {alpha}% | {'✓' if bate else '✗'}")
        if r1 is not None: cartera_sis+=350*(1+r1/100)
        else: cartera_sis+=350
        if top2 and r2 is not None: cartera_sis+=150*(1+r2/100)
        else: cartera_sis+=150
        if ri is not None: cartera_iwd+=500*(1+ri/100)
        else: cartera_iwd+=500
        snapshots.append({"date":eval_date.isoformat(),"meses":m,
            "top1":{"name":top1["name"],"symbol":top1["symbol"],"sector":top1["sector"],
                    "score":top1["score_final"],"ret_hoy":r1},
            "top2":{"name":top2["name"],"symbol":top2["symbol"],"sector":top2["sector"],
                    "score":top2["score_final"],"ret_hoy":r2} if top2 else None,
            "ret_ponderado":rp,"iwda_hoy":ri,"alpha":alpha,"bate_top1":bate,
            "score_top1":top1["score_final"],"ranking":sr[:5]})

    total=len(eval_dates)*APORTACION
    ret_sis=round((cartera_sis/total-1)*100,2)
    ret_iwd=round((cartera_iwd/total-1)*100,2)
    alpha_car=round(ret_sis-ret_iwd,2)
    alphas=[s["alpha"] for s in snapshots if s.get("alpha") is not None]
    bates=[s["bate_top1"] for s in snapshots if s.get("bate_top1") is not None]
    rets=[s["ret_ponderado"] for s in snapshots if s.get("ret_ponderado") is not None]
    iwdas=[s["iwda_hoy"] for s in snapshots if s.get("iwda_hoy") is not None]
    buckets={"alto_70+":{"a":[],"r":[]},"medio_55-70":{"a":[],"r":[]},"bajo_-55":{"a":[],"r":[]}}
    for s in snapshots:
        sc=s.get("score_top1"); al=s.get("alpha"); re=s.get("ret_ponderado")
        if sc is None: continue
        b="alto_70+" if sc>=70 else "medio_55-70" if sc>=55 else "bajo_-55"
        if al is not None: buckets[b]["a"].append(al)
        if re is not None: buckets[b]["r"].append(re)
    pred={}
    for b,data in buckets.items():
        pred[b]={"n":len(data["a"]),"ret_medio":round(sum(data["r"])/len(data["r"]),2) if data["r"] else None,
                 "alpha_medio":round(sum(data["a"])/len(data["a"]),2) if data["a"] else None}
    all_etf_ids=list(etf_data.keys())
    pvalue,pct_real,mean_rand=bootstrap_pvalue(alpha_car,all_etf_ids,etf_data,iwda_p,iwda_d,eval_dates)
    significance=""
    if pvalue is not None:
        if pvalue<0.05: significance="✓✓ ESTADISTICAMENTE SIGNIFICATIVO (p<0.05)"
        elif pvalue<0.10: significance="✓ Marginalmente significativo (p<0.10)"
        elif pvalue<0.20: significance="~ Débilmente significativo (p<0.20)"
        else: significance="✗ No significativo — puede ser azar"
    summary={"metodologia":"Top1 bate IWDA. 70/30. Cartera acumulativa hasta hoy. Con p-value bootstrap.",
        "fecha":TODAY.isoformat(),"n_fechas":len(snapshots),"total_invertido":total,
        "valor_sistema":round(cartera_sis,2),"valor_iwda":round(cartera_iwd,2),
        "rentabilidad_sistema":ret_sis,"rentabilidad_iwda":ret_iwd,"alpha_cartera":alpha_car,
        "alpha_medio_señales":round(sum(alphas)/len(alphas),2) if alphas else None,
        "ret_medio_ponderado":round(sum(rets)/len(rets),2) if rets else None,
        "ret_medio_iwda":round(sum(iwdas)/len(iwdas),2) if iwdas else None,
        "top1_bate_iwda":sum(1 for b in bates if b),"total_con_dato":len(bates),
        "pct_bate_iwda":round(sum(1 for b in bates if b)/len(bates)*100,1) if bates else None,
        "predictividad":pred,
        "bootstrap":{"pvalue":pvalue,"percentil_real":pct_real,
                     "alpha_medio_aleatorio":mean_rand,"n_simulaciones":N_BOOTSTRAP,
                     "significancia":significance},
        "interpretacion":(f"Cartera acumulativa (€{total}, €{APORTACION}/mes x {len(eval_dates)} meses): "
            f"sistema €{round(cartera_sis,0):.0f} vs IWDA €{round(cartera_iwd,0):.0f}. "
            f"Alpha total: {alpha_car}%. {significance}.")}
    out={"updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z",
        "model_version":"9.0","summary":summary,"snapshots":snapshots,
        "metodologia":"v9: cartera acumulativa, Top1 bate IWDA, 70/30, bootstrap p-value."}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as fh: json.dump(out,fh,ensure_ascii=False,indent=2)
    print(f"\n{'='*65}")
    print(f"BACKTEST v9 — CARTERA ACUMULATIVA HASTA HOY ({TODAY})")
    print(f"\n  CARTERA (€{APORTACION}/mes x {len(eval_dates)} meses = €{total}):")
    print(f"  Sistema:  €{round(cartera_sis,0):.0f} (+{ret_sis}%)")
    print(f"  IWDA:     €{round(cartera_iwd,0):.0f} (+{ret_iwd}%)")
    print(f"  Alpha:    {alpha_car:+.2f}% {'✓ SISTEMA GANA' if alpha_car>0 else '✗ IWDA GANA'}")
    print(f"\n  SIGNIFICANCIA ESTADISTICA (bootstrap n={N_BOOTSTRAP}):")
    print(f"  P-value:  {pvalue}")
    print(f"  {significance}")
    print(f"  Alpha aleatorio medio: {mean_rand}%")
    print(f"\n  PREDICTIVIDAD DEL SCORE:")
    for b,d in pred.items():
        print(f"  {b:12s}: n={d['n']:2d} ret={str(d['ret_medio'])+'%':8s} alpha={str(d['alpha_medio'])+'%'}")
    print(f"\n{summary['interpretacion']}")
    print(f"{'='*65}")

if __name__ == "__main__":
    main()
