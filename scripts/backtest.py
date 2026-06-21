#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest walk-forward del modelo v8 — horizonte largo plazo.

Cambios vs v7:
  - Bate = Top1 supera a IWDA (no promedio Top2).
  - Distribucion 70/30 en retorno ponderado.
  - Cartera acumulativa: €500/mes durante 36 meses vs €500/mes en IWDA.
  - Retorno desde cada fecha HASTA HOY.
  - Filtro sobrevaloración incluido.
"""

import json, math, os, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI  = os.path.join(ROOT, "universe.json")
OUT  = os.path.join(ROOT, "data", "backtest.json")
UA   = {"User-Agent": "Mozilla/5.0 (compatible; Backtest/7.0)"}

BITCOIN_HALVING_DATE = datetime.date(2024, 4, 19)
W_TECH  = {"rel_strength":0.25,"ema200":0.25,"mom6m":0.20,"entry":0.20,"consistency":0.10}
W_FINAL = {"tech":0.85,"macro":0.15}
TODAY   = datetime.date.today()
APORTACION_MENSUAL = 500

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

def percentile_in_history(value,series):
    if value is None or not series: return 50.0
    return round(sum(1 for v in series if v<=value)/len(series)*100,1)

def prices_up_to(all_prices,all_dates,target_date):
    cutoff=target_date.isoformat()
    for i,d in enumerate(all_dates):
        if d>cutoff: return all_prices[:i]
    return all_prices[:]

def return_from_to_today(all_prices,all_dates,from_date):
    from_str=from_date.isoformat(); start_idx=None
    for i,d in enumerate(all_dates):
        if d>=from_str: start_idx=i; break
    if start_idx is None or start_idx>=len(all_prices)-1: return None
    p0=all_prices[start_idx]; p1=all_prices[-1]
    return round((p1/p0-1)*100,2) if p0>0 else None

def months_held(from_date):
    return round((TODAY-from_date).days/30.44,1)

def compute_overval_simple(prices):
    signals = 0
    if len(prices) >= 252:
        mom3m_now = ret_n(prices, 63)
        mom3m_history = []
        n = len(prices)
        for i in range(1, min(504, n-63)):
            r = ret_n(prices[:n-i], 63)
            if r is not None: mom3m_history.append(r)
        if mom3m_now is not None and mom3m_history:
            avg = sum(mom3m_history)/len(mom3m_history)
            if avg > 0 and mom3m_now > avg * 3: signals += 1
            elif avg > 0 and mom3m_now > avg * 2: signals += 0.5
    dist_at = drawdown_alltime(prices)
    if dist_at is not None and dist_at > -2: signals += 1
    elif dist_at is not None and dist_at > -5: signals += 0.5
    if signals >= 2: return 0.5
    elif signals >= 1: return 0.7
    elif signals >= 0.5: return 0.85
    return 1.0

def compute_score_at_date(prices,iwda_prices):
    if not prices or len(prices)<60: return None
    n=len(prices); vol=vol_std(prices,min(252,n-1))
    rs_now=None; rs_hist=[]
    if iwda_prices and len(iwda_prices)>=126:
        r_e=ret_n(prices,min(126,n-1)); r_i=ret_n(iwda_prices,min(126,len(iwda_prices)-1))
        if r_e is not None and r_i is not None: rs_now=(r_e-r_i)/(vol/20.0)
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
    dist_52w=drawdown_from_max(prices,252); dist_at=drawdown_alltime(prices)
    entry_combined=dist_52w*0.60+dist_at*0.40 if dist_52w is not None and dist_at is not None else dist_52w
    dd_hist=[]
    for i in range(1,min(756,n-252)):
        pc=prices[:n-i]; d=drawdown_from_max(pc,min(252,len(pc)))
        if d is not None: dd_hist.append(-d)
    pct_entry=percentile_in_history(-entry_combined if entry_combined is not None else None,dd_hist)
    co_now=consistency_6m(prices); co_hist=[]
    for i in range(1,min(756,n-130)):
        pc=prices[:n-i]; c=consistency_6m(pc)
        if c is not None: co_hist.append(c)
    pct_co=percentile_in_history(co_now,co_hist)
    score=(W_TECH["rel_strength"]*pct_rs+W_TECH["ema200"]*pct_ema+
           W_TECH["mom6m"]*pct_m6+W_TECH["entry"]*pct_entry+W_TECH["consistency"]*pct_co)
    m3=ret_n(prices,min(63,n-1))
    if m3 is not None and m3<-10: score*=0.6
    score*=compute_overval_simple(prices)
    return round(score,1)

def macro_score_simple(eval_date,macro_profile):
    if macro_profile=="crypto_halving":
        months=(eval_date-BITCOIN_HALVING_DATE).days/30.44
        if months<=18: return min(100,100-months*2)*0.40+50*0.60
        elif months<=30: return 60
        else: return 45
    if macro_profile in ("defensive_government","defensive_demographics"): return 65
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

    print(f"\nCalculando retornos HASTA HOY ({TODAY}) — {len(eval_dates)} fechas...")
    print(f"Bate IWDA = Top1 supera a IWDA. Distribucion 70/30.\n")

    snapshots=[]
    cartera_sistema=0.0; cartera_iwda=0.0
    cartera_detalle=[]; cartera_iwda_det=[]

    for eval_date in eval_dates:
        meses=months_held(eval_date)
        print(f"  === {eval_date} (hace {meses:.0f}M) ===")
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
                "sector":edata["sector"],"score_final":sf})
        if not etf_scores: continue
        sector_best={}
        for r in sorted(etf_scores,key=lambda x:x["score_final"],reverse=True):
            s=r["sector"]
            if s not in sector_best: sector_best[s]=r
        sector_ranking=sorted(sector_best.values(),key=lambda x:x["score_final"],reverse=True)
        top1=sector_ranking[0]
        top2=sector_ranking[1] if len(sector_ranking)>1 else None
        edata1=etf_data[top1["id"]]
        ret_top1_hoy=return_from_to_today(edata1["prices"],edata1["dates"],eval_date)
        ret_top2_hoy=None
        if top2:
            edata2=etf_data[top2["id"]]
            ret_top2_hoy=return_from_to_today(edata2["prices"],edata2["dates"],eval_date)
        iwda_hoy=return_from_to_today(iwda_p,iwda_d,eval_date)
        if ret_top1_hoy is not None and ret_top2_hoy is not None:
            ret_ponderado=round(ret_top1_hoy*0.70+ret_top2_hoy*0.30,2)
        elif ret_top1_hoy is not None:
            ret_ponderado=ret_top1_hoy
        else:
            ret_ponderado=None
        bate_top1=ret_top1_hoy>iwda_hoy if ret_top1_hoy is not None and iwda_hoy is not None else None
        alpha_pond=round(ret_ponderado-iwda_hoy,2) if ret_ponderado is not None and iwda_hoy is not None else None
        print(f"    #1 {top1['symbol']:10s} score={top1['score_final']:5.1f} ret_hoy={str(ret_top1_hoy)+'%' if ret_top1_hoy else '?'}")
        if top2: print(f"    #2 {top2['symbol']:10s} score={top2['score_final']:5.1f} ret_hoy={str(ret_top2_hoy)+'%' if ret_top2_hoy else '?'}")
        print(f"    → Pond(70/30): {ret_ponderado}% | IWDA: {iwda_hoy}% | Alpha: {alpha_pond}% | Top1 {'✓ BATE' if bate_top1 else '✗ no bate'}")
        if ret_top1_hoy is not None:
            v1=350*(1+ret_top1_hoy/100)
            cartera_detalle.append({"fecha":eval_date.isoformat(),"symbol":top1["symbol"],"invertido":350,"valor_hoy":round(v1,2)})
            cartera_sistema+=v1
        else:
            cartera_sistema+=350
        if top2 and ret_top2_hoy is not None:
            v2=150*(1+ret_top2_hoy/100)
            cartera_detalle.append({"fecha":eval_date.isoformat(),"symbol":top2["symbol"],"invertido":150,"valor_hoy":round(v2,2)})
            cartera_sistema+=v2
        else:
            cartera_sistema+=150
        if iwda_hoy is not None:
            vi=500*(1+iwda_hoy/100)
            cartera_iwda_det.append({"fecha":eval_date.isoformat(),"invertido":500,"valor_hoy":round(vi,2)})
            cartera_iwda+=vi
        else:
            cartera_iwda+=500
        snapshots.append({
            "date":eval_date.isoformat(),"meses_desde":meses,
            "top1":{"name":top1["name"],"symbol":top1["symbol"],"sector":top1["sector"],
                    "score":top1["score_final"],"ret_hasta_hoy":ret_top1_hoy},
            "top2":{"name":top2["name"],"symbol":top2["symbol"],"sector":top2["sector"],
                    "score":top2["score_final"],"ret_hasta_hoy":ret_top2_hoy} if top2 else None,
            "ret_ponderado_hoy":ret_ponderado,"iwda_hoy":iwda_hoy,
            "alpha_ponderado":alpha_pond,"bate_top1":bate_top1,
            "score_top1":top1["score_final"],"full_ranking":sector_ranking[:5],
        })

    total_invertido=len(eval_dates)*APORTACION_MENSUAL
    rentabilidad_sistema=round((cartera_sistema/total_invertido-1)*100,2)
    rentabilidad_iwda=round((cartera_iwda/total_invertido-1)*100,2)
    alpha_cartera=round(rentabilidad_sistema-rentabilidad_iwda,2)
    alphas=[s["alpha_ponderado"] for s in snapshots if s.get("alpha_ponderado") is not None]
    bate_list=[s["bate_top1"] for s in snapshots if s.get("bate_top1") is not None]
    rets=[s["ret_ponderado_hoy"] for s in snapshots if s.get("ret_ponderado_hoy") is not None]
    iwda_rets=[s["iwda_hoy"] for s in snapshots if s.get("iwda_hoy") is not None]
    score_buckets={
        "alto_70_100":{"fechas":[],"alphas":[],"rets":[]},
        "medio_55_70":{"fechas":[],"alphas":[],"rets":[]},
        "bajo_0_55":  {"fechas":[],"alphas":[],"rets":[]},
    }
    for s in snapshots:
        sc=s.get("score_top1"); alpha=s.get("alpha_ponderado"); ret=s.get("ret_ponderado_hoy")
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
        "metodologia":"Top1 bate IWDA. 70/30. Cartera acumulativa 36M hasta hoy.",
        "fecha_calculo":TODAY.isoformat(),"n_fechas":len(snapshots),
        "total_invertido":total_invertido,
        "valor_cartera_sistema":round(cartera_sistema,2),
        "valor_cartera_iwda":round(cartera_iwda,2),
        "rentabilidad_sistema":rentabilidad_sistema,
        "rentabilidad_iwda":rentabilidad_iwda,
        "alpha_cartera":alpha_cartera,
        "alpha_medio_ponderado":round(sum(alphas)/len(alphas),2) if alphas else None,
        "ret_medio_ponderado":round(sum(rets)/len(rets),2) if rets else None,
        "ret_medio_iwda":round(sum(iwda_rets)/len(iwda_rets),2) if iwda_rets else None,
        "top1_bate_iwda":sum(1 for b in bate_list if b),
        "total_con_dato":len(bate_list),
        "pct_top1_bate_iwda":round(sum(1 for b in bate_list if b)/len(bate_list)*100,1) if bate_list else None,
        "predictividad_score":predictividad,
        "interpretacion":(
            f"Cartera acumulativa (€{total_invertido}, €500/mes x {len(eval_dates)} meses): "
            f"sistema €{round(cartera_sistema,0):.0f} vs IWDA €{round(cartera_iwda,0):.0f}. "
            f"Alpha total: {alpha_cartera}%. "
            f"Top1 bate IWDA en {sum(1 for b in bate_list if b)}/{len(bate_list)} fechas."
        )
    }
    out={"updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z",
        "model_version":"8.0","summary":summary,"snapshots":snapshots,
        "cartera_detalle":cartera_detalle[:20],
        "metodologia":"v8: Top1 bate IWDA, 70/30, cartera acumulativa, filtro sobrevaloración."}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as fh:
        json.dump(out,fh,ensure_ascii=False,indent=2)
    print(f"\n{'='*65}")
    print(f"BACKTEST v8 — CARTERA ACUMULATIVA HASTA HOY ({TODAY})")
    print(f"\n  CARTERA ACUMULATIVA (€500/mes x {len(eval_dates)} meses = €{total_invertido}):")
    print(f"  Sistema:   €{round(cartera_sistema,0):.0f} (+{rentabilidad_sistema}%)")
    print(f"  IWDA:      €{round(cartera_iwda,0):.0f} (+{rentabilidad_iwda}%)")
    print(f"  Alpha:     {alpha_cartera:+.2f}% {'✓ SISTEMA GANA' if alpha_cartera>0 else '✗ IWDA GANA'}")
    print(f"\n  POR SEÑAL (Top1 bate IWDA):")
    print(f"  Alpha medio ponderado: {summary['alpha_medio_ponderado']}%")
    print(f"  Top1 bate IWDA:        {summary['top1_bate_iwda']}/{summary['total_con_dato']} ({summary['pct_top1_bate_iwda']}%)")
    print(f"\n  PREDICTIVIDAD DEL SCORE:")
    for bucket,data in predictividad.items():
        print(f"  {bucket:15s}: n={data['n_fechas']:2d} ret={str(data['ret_medio'])+'%':8s} alpha={str(data['alpha_medio'])+'%'}")
    print(f"\n{summary['interpretacion']}")
    print(f"{'='*65}")

if __name__ == "__main__":
    main()
