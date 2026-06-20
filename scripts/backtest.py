#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest walk-forward del modelo v7 — horizonte largo plazo.

Para cada mes del historico:
1. Calcula scores con datos disponibles HASTA ese mes.
2. Identifica el Top2 de ese momento.
3. Mide rentabilidad desde ese mes HASTA HOY (no a 3 meses).
4. Compara vs IWDA desde ese mismo mes hasta hoy.
5. Responde: si hubieras seguido el sistema ese mes, ¿estarías mejor que con IWDA?
"""

import json, math, os, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI  = os.path.join(ROOT, "universe.json")
OUT  = os.path.join(ROOT, "data", "backtest.json")
UA   = {"User-Agent": "Mozilla/5.0 (compatible; Backtest/6.0)"}

BITCOIN_HALVING_DATE = datetime.date(2024, 4, 19)
W_TECH  = {"rel_strength":0.25,"ema200":0.25,"mom6m":0.20,"entry":0.20,"consistency":0.10}
W_FINAL = {"tech":0.85,"macro":0.15}
TODAY   = datetime.date.today()

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_5y(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5y&interval=1d"
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
    return max(5.0, sd*math.sqrt(252)*100)

def drawdown_from_max(prices,n=252):
    if len(prices)<2: return None
    window=prices[-min(n,len(prices)):]; peak=max(window)
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

def percentile_in_history(value,series):
    if value is None or not series: return 50.0
    return round(sum(1 for v in series if v<=value)/len(series)*100,1)

def prices_up_to(all_prices,all_dates,target_date):
    cutoff=target_date.isoformat()
    for i,d in enumerate(all_dates):
        if d>cutoff: return all_prices[:i]
    return all_prices[:]

def return_from_to_today(all_prices, all_dates, from_date):
    from_str = from_date.isoformat()
    start_idx = None
    for i,d in enumerate(all_dates):
        if d >= from_str: start_idx=i; break
    if start_idx is None: return None
    if start_idx >= len(all_prices)-1: return None
    p0 = all_prices[start_idx]
    p1 = all_prices[-1]
    return round((p1/p0-1)*100, 2) if p0>0 else None

def months_held(from_date):
    return round((TODAY - from_date).days / 30.44, 1)

def compute_score_at_date(prices,iwda_prices):
    if not prices or len(prices)<60: return None
    n=len(prices)
    vol=vol_std(prices,min(252,n-1))
    rs_now=None; rs_hist=[]
    if iwda_prices and len(iwda_prices)>=126:
        r_e=ret_n(prices,min(126,n-1)); r_i=ret_n(iwda_prices,min(126,len(iwda_prices)-1))
        if r_e is not None and r_i is not None:
            rs_now=(r_e-r_i)/(vol/20.0)
        for i in range(126,min(n,756)):
            p_e=prices[:n-i+126] if n-i+126>126 else prices[:126]
            p_i=iwda_prices[:len(iwda_prices)-i+126] if len(iwda_prices)-i+126>126 else iwda_prices[:126]
            re=ret_n(p_e,126); ri=ret_n(p_i,126)
            if re is not None and ri is not None:
                vh=vol_std(p_e,min(252,len(p_e)-1))
                rs_hist.append((re-ri)/(vh/20.0))
    pct_rs=percentile_in_history(rs_now,rs_hist)
    e200=ema_n(prices,min(200,n)); ema_now=((prices[-1]/e200-1)*100) if e200 else None
    ema_norm=(ema_now/(vol/20.0)) if ema_now else None
    ema_hist=[]
    for i in range(1,min(504,n-200)):
        pc=prices[:n-i]; e=ema_n(pc,min(200,len(pc)))
        if e:
            d=(pc[-1]/e-1)*100; vh=vol_std(pc,min(252,len(pc)-1))
            ema_hist.append(d/(vh/20.0))
    pct_ema=percentile_in_history(ema_norm,ema_hist)
    m6_now=ret_n(prices,min(126,n-1))
    m6_norm=(m6_now/(vol/20.0)) if m6_now is not None else None
    m6_hist=[]
    for i in range(1,min(756,n-126)):
        pc=prices[:n-i]; r=ret_n(pc,min(126,len(pc)-1))
        if r is not None:
            vh=vol_std(pc,min(252,len(pc)-1))
            m6_hist.append(r/(vh/20.0))
    pct_m6=percentile_in_history(m6_norm,m6_hist)
    dd_now=drawdown_from_max(prices,252); dd_hist=[]
    for i in range(1,min(756,n-252)):
        pc=prices[:n-i]; d=drawdown_from_max(pc,min(252,len(pc)))
        if d is not None: dd_hist.append(-d)
    pct_entry=percentile_in_history(-dd_now if dd_now is not None else None,dd_hist)
    co_now=consistency_6m(prices); co_hist=[]
    for i in range(1,min(756,n-130)):
        pc=prices[:n-i]; c=consistency_6m(pc)
        if c is not None: co_hist.append(c)
    pct_co=percentile_in_history(co_now,co_hist)
    score=(W_TECH["rel_strength"]*pct_rs+W_TECH["ema200"]*pct_ema+
           W_TECH["mom6m"]*pct_m6+W_TECH["entry"]*pct_entry+W_TECH["consistency"]*pct_co)
    m3=ret_n(prices,min(63,n-1))
    if m3 is not None and m3<-10: score*=0.6
    return round(score,1)

def macro_score_simple(eval_date,macro_profile):
    if macro_profile=="crypto_halving":
        months=(eval_date-BITCOIN_HALVING_DATE).days/30.44
        if months<=18:   return min(100,100-months*2)*0.40+50*0.60
        elif months<=30: return 60
        else:            return 45
    if macro_profile=="defensive_government": return 65
    if macro_profile=="defensive_demographics": return 65
    return 50

def main():
    with open(UNI,encoding="utf-8") as f:
        universe=json.load(f)["etfs"]
    print(f"Descargando historico 5A de {len(universe)} ETFs...")
    etf_data={}
    for etf in universe:
        sym=etf["symbol"]
        print(f"  {sym}...",end=" ",flush=True)
        prices,dates=fetch_5y(sym)
        if not prices or len(prices)<120: print("sin datos"); continue
        etf_data[etf["id"]]={**etf,"prices":prices,"dates":dates}
        print(f"{len(prices)} dias")
    print("  IWDA...",end=" ")
    iwda_p,iwda_d=fetch_5y("IWDA.AS")
    print(f"{len(iwda_p) if iwda_p else 0} dias")
    if not etf_data: print("ERROR: sin datos"); return

    eval_dates=[]
    d=TODAY.replace(day=1)
    for _ in range(36):
        d=(d-datetime.timedelta(days=1)).replace(day=1)
        eval_dates.append(d)
    eval_dates=sorted(eval_dates)

    print(f"\nCalculando retornos HASTA HOY ({TODAY}) para {len(eval_dates)} fechas...")
    snapshots=[]

    for eval_date in eval_dates:
        meses=months_held(eval_date)
        print(f"\n  === Comprado en {eval_date} (hace {meses:.0f}M) ===")
        etf_scores=[]
        for eid,edata in etf_data.items():
            p_cut=prices_up_to(edata["prices"],edata["dates"],eval_date)
            if len(p_cut)<60: continue
            iwda_cut=prices_up_to(iwda_p,iwda_d,eval_date) if iwda_p else None
            st=compute_score_at_date(p_cut,iwda_cut)
            if st is None: continue
            sm=macro_score_simple(eval_date,edata.get("macro_profile",""))
            sf=round(st*W_FINAL["tech"]+sm*W_FINAL["macro"],1)
            etf_scores.append({"id":eid,"name":edata["name"],"symbol":edata["symbol"],
                "sector":edata["sector"],"score_final":sf,"score_tech":st,"score_macro":sm})
        if not etf_scores: continue
        sector_best={}
        for r in sorted(etf_scores,key=lambda x:x["score_final"],reverse=True):
            s=r["sector"]
            if s not in sector_best: sector_best[s]=r
        sector_ranking=sorted(sector_best.values(),key=lambda x:x["score_final"],reverse=True)
        top2=sector_ranking[:2]; top2_with_rets=[]
        for r in top2:
            edata=etf_data[r["id"]]
            ret_hoy=return_from_to_today(edata["prices"],edata["dates"],eval_date)
            top2_with_rets.append({**r,"ret_hasta_hoy":ret_hoy,"meses_mantenido":meses})
            print(f"    #{sector_ranking.index(r)+1} {r['symbol']:10s} [{r['sector']:20s}] score={r['score_final']:5.1f} ret_hoy={str(ret_hoy)+'%' if ret_hoy is not None else '?'}")
        iwda_hoy=return_from_to_today(iwda_p,iwda_d,eval_date)
        top2_rets=[e["ret_hasta_hoy"] for e in top2_with_rets if e["ret_hasta_hoy"] is not None]
        avg_top2=round(sum(top2_rets)/len(top2_rets),2) if top2_rets else None
        alpha=round(avg_top2-iwda_hoy,2) if avg_top2 is not None and iwda_hoy is not None else None
        bate=avg_top2>iwda_hoy if avg_top2 is not None and iwda_hoy is not None else None
        print(f"    → Top2: {avg_top2}% | IWDA: {iwda_hoy}% | Alpha: {alpha}% | {'✓ BATE' if bate else '✗ no bate'}")
        snapshots.append({
            "date":eval_date.isoformat(),"meses_desde":meses,
            "top2":top2_with_rets,"full_ranking":sector_ranking,
            "avg_top2_hoy":avg_top2,"iwda_hoy":iwda_hoy,
            "alpha_hoy":alpha,"bate_iwda":bate,
            "score_top1":sector_ranking[0]["score_final"] if sector_ranking else None,
        })

    alphas=[s["alpha_hoy"] for s in snapshots if s.get("alpha_hoy") is not None]
    bate_list=[s["bate_iwda"] for s in snapshots if s.get("bate_iwda") is not None]
    rets=[s["avg_top2_hoy"] for s in snapshots if s.get("avg_top2_hoy") is not None]
    iwda_rets=[s["iwda_hoy"] for s in snapshots if s.get("iwda_hoy") is not None]

    score_buckets={
        "alto_70_100":{"fechas":[],"alphas":[],"rets":[]},
        "medio_55_70":{"fechas":[],"alphas":[],"rets":[]},
        "bajo_0_55":  {"fechas":[],"alphas":[],"rets":[]},
    }
    for s in snapshots:
        sc=s.get("score_top1"); alpha=s.get("alpha_hoy"); ret=s.get("avg_top2_hoy")
        if sc is None: continue
        bucket="alto_70_100" if sc>=70 else "medio_55_70" if sc>=55 else "bajo_0_55"
        score_buckets[bucket]["fechas"].append(s["date"])
        if alpha is not None: score_buckets[bucket]["alphas"].append(alpha)
        if ret is not None:   score_buckets[bucket]["rets"].append(ret)

    predictividad={}
    for bucket,data in score_buckets.items():
        ab=data["alphas"]; rb=data["rets"]
        predictividad[bucket]={"n_fechas":len(data["fechas"]),
            "ret_medio":round(sum(rb)/len(rb),2) if rb else None,
            "alpha_medio":round(sum(ab)/len(ab),2) if ab else None,
            "fechas":data["fechas"]}

    summary={
        "metodologia":        "Retorno desde cada fecha de señal HASTA HOY — horizonte largo plazo real",
        "fecha_calculo":      TODAY.isoformat(),
        "n_fechas":           len(snapshots),
        "alpha_medio_hoy":    round(sum(alphas)/len(alphas),2)       if alphas    else None,
        "ret_medio_top2_hoy": round(sum(rets)/len(rets),2)           if rets      else None,
        "ret_medio_iwda_hoy": round(sum(iwda_rets)/len(iwda_rets),2) if iwda_rets else None,
        "meses_bate_iwda":    sum(1 for b in bate_list if b),
        "meses_total":        len(bate_list),
        "pct_bate_iwda":      round(sum(1 for b in bate_list if b)/len(bate_list)*100,1) if bate_list else None,
        "predictividad_score":predictividad,
        "interpretacion":(
            f"En {sum(1 for b in bate_list if b)} de {len(bate_list)} fechas, "
            f"seguir el sistema habría dado mejor resultado que IWDA hasta hoy. "
            f"Alpha medio: {round(sum(alphas)/len(alphas),2) if alphas else '?'}%."
        )
    }
    out={"updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z",
        "model_version":"7.0","summary":summary,"snapshots":snapshots,
        "metodologia":"Retorno desde señal hasta HOY. Horizonte largo plazo real."}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as fh:
        json.dump(out,fh,ensure_ascii=False,indent=2)
    print(f"\n{'='*65}")
    print(f"BACKTEST v7 — HASTA HOY ({TODAY})")
    print(f"  Fechas evaluadas:      {len(snapshots)}")
    print(f"  Alpha medio vs IWDA:   {summary['alpha_medio_hoy']}%")
    print(f"  Ret. medio Top2 (hoy): {summary['ret_medio_top2_hoy']}%")
    print(f"  Ret. medio IWDA (hoy): {summary['ret_medio_iwda_hoy']}%")
    print(f"  Bate IWDA:             {summary['meses_bate_iwda']}/{summary['meses_total']} fechas ({summary['pct_bate_iwda']}%)")
    print(f"\nPREDICTIVIDAD (¿score alto = mejor retorno hasta hoy?):")
    for bucket,data in predictividad.items():
        print(f"  {bucket:15s}: n={data['n_fechas']:2d} ret={str(data['ret_medio'])+'%':8s} alpha={str(data['alpha_medio'])+'%'}")
    print(f"\n{summary['interpretacion']}")
    print(f"{'='*65}")

if __name__ == "__main__":
    main()
