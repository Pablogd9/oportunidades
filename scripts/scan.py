#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor del escaner de oportunidades - version 6 (quant profesional).

Score tecnico (70%): percentiles del propio historico del ETF.
Score macro (30%): factores externos especificos por sector.
"""

import json, math, os, re, urllib.request, datetime

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI   = os.path.join(ROOT, "universe.json")
MACRO = os.path.join(ROOT, "data", "macro.json")
OUT   = os.path.join(ROOT, "data", "output.json")
UA    = {"User-Agent": "Mozilla/5.0 (compatible; QuantScanner/6.0)"}
WARN  = []

CARTERA = [
    {"id": "SEMI", "symbol": "SEMI.AS", "name": "iShares MSCI Global Semiconductors", "sector": "Semiconductores"},
    {"id": "BTC",  "symbol": "BTC-EUR",  "name": "Bitcoin",                             "sector": "Bitcoin y Cripto"},
]

W_TECH = {
    "rel_strength": 0.25,
    "ema200":       0.25,
    "mom6m":        0.20,
    "entry":        0.20,
    "consistency":  0.10,
}

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_history(symbol, rng="2y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d"
    try:
        d   = _get(url)
        res = d["chart"]["result"][0]
        ts  = res.get("timestamp") or []
        cls = (res.get("indicators") or {}).get("quote",[{}])[0].get("close") or []
        pairs = {}
        for t, c in zip(ts, cls):
            if c is None: continue
            day = datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
            pairs[day] = float(c)
        series = sorted(pairs.items())
        return [c for _, c in series], [d for d, _ in series]
    except Exception as e:
        WARN.append(f"{symbol}: {e}")
        return None, None

def fetch_pe(symbol):
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=summaryDetail,defaultKeyStatistics"
    try:
        d  = _get(url)
        r  = d["quoteSummary"]["result"][0]
        sd = r.get("summaryDetail", {})
        ks = r.get("defaultKeyStatistics", {})
        pe   = (sd.get("trailingPE") or {}).get("raw") or (ks.get("trailingPE") or {}).get("raw")
        beta = (ks.get("beta") or {}).get("raw") or (sd.get("beta") or {}).get("raw")
        dy   = (sd.get("dividendYield") or {}).get("raw")
        return {
            "pe":   round(pe,1)     if pe   else None,
            "beta": round(beta,2)   if beta else None,
            "dy":   round(dy*100,2) if dy   else None,
        }
    except:
        return {"pe": None, "beta": None, "dy": None}

def ema_n(prices, n):
    if len(prices) < n: return None
    k = 2.0/(n+1); ema = sum(prices[:n])/n
    for p in prices[n:]: ema = p*k + ema*(1-k)
    return ema

def sma_n(prices, n):
    if len(prices) < n: return None
    return sum(prices[-n:]) / n

def ret_n(prices, n):
    if len(prices) < n+1: return None
    p0, p1 = prices[-(n+1)], prices[-1]
    return (p1/p0-1)*100 if p0 > 0 else None

def vol_annual(prices, n=60):
    if len(prices) < n+1: return None
    rets = [prices[i]/prices[i-1]-1 for i in range(max(1,len(prices)-n), len(prices))]
    if len(rets) < 5: return None
    mean = sum(rets)/len(rets)
    sd = math.sqrt(sum((r-mean)**2 for r in rets)/(len(rets)-1))
    return sd * math.sqrt(252) * 100

def drawdown_from_max(prices, n=252):
    if len(prices) < 2: return None
    window = prices[-min(n,len(prices)):]
    peak = max(window)
    return round((prices[-1]/peak-1)*100,2) if peak > 0 else None

def ann_ret(prices, n=252):
    actual = min(n, len(prices)-1)
    if actual < 20: return None
    return round((prices[-1]/prices[-actual-1])**(252/actual)*100-100, 1)

def consistency_6m(prices):
    if len(prices) < 130: return None
    monthly = []
    for i in range(6):
        start = -(21*(i+1)+1); end = -(21*i+1) if i > 0 else -1
        if abs(start) >= len(prices): continue
        p0=prices[start]; p1=prices[end]
        if p0 > 0: monthly.append(p1/p0-1)
    if len(monthly) < 4: return None
    return round(sum(1 for r in monthly if r > 0)/len(monthly)*100, 0)

def percentile_in_own_history(value, series):
    if value is None or not series: return 50.0
    below = sum(1 for v in series if v <= value)
    return round(below/len(series)*100, 1)

def compute_technical_score(prices, iwda_prices):
    if not prices or len(prices) < 60: return None, {}
    n = len(prices)
    details = {}

    # Factor 1: Fuerza relativa vs MSCI World 6M
    rel_strength_now = None
    rel_strength_history = []
    if iwda_prices and len(iwda_prices) >= 126:
        r_e = ret_n(prices, min(126,n-1))
        r_i = ret_n(iwda_prices, min(126,len(iwda_prices)-1))
        if r_e is not None and r_i is not None:
            rel_strength_now = r_e - r_i
        for i in range(126, min(n,378)):
            p_e = prices[:n-i+126] if n-i+126>126 else prices[:126]
            p_i = iwda_prices[:len(iwda_prices)-i+126] if len(iwda_prices)-i+126>126 else iwda_prices[:126]
            re=ret_n(p_e,126); ri=ret_n(p_i,126)
            if re is not None and ri is not None: rel_strength_history.append(re-ri)
    pct_rel = percentile_in_own_history(rel_strength_now, rel_strength_history)
    details["rel_strength"] = {
        "value": round(rel_strength_now,2) if rel_strength_now else None,
        "percentile": pct_rel,
        "interpretation": (
            "Lidera al mercado global" if rel_strength_now and rel_strength_now > 5
            else "Va por detrás del mercado" if rel_strength_now and rel_strength_now < -5
            else "En línea con el mercado"
        )
    }

    # Factor 2: EMA200
    e200 = ema_n(prices, min(200,n))
    dist_ema200_now = ((prices[-1]/e200-1)*100) if e200 else None
    ema200_history = []
    for i in range(1, min(253,n-200)):
        pc=prices[:n-i]; e=ema_n(pc,min(200,len(pc)))
        if e: ema200_history.append((pc[-1]/e-1)*100)
    pct_ema = percentile_in_own_history(dist_ema200_now, ema200_history)
    details["ema200"] = {
        "value": round(dist_ema200_now,2) if dist_ema200_now else None,
        "ema200_abs": round(e200,4) if e200 else None,
        "percentile": pct_ema,
        "above": dist_ema200_now > 0 if dist_ema200_now is not None else None,
        "interpretation": (
            f"Muy por encima de EMA200 (+{dist_ema200_now:.1f}%)" if dist_ema200_now and dist_ema200_now > 15
            else f"Por encima de EMA200 (+{dist_ema200_now:.1f}%)" if dist_ema200_now and dist_ema200_now > 0
            else f"Por debajo de EMA200 ({dist_ema200_now:.1f}%)" if dist_ema200_now
            else "Sin datos EMA200"
        )
    }

    # Factor 3: Momentum 6M
    mom6m_now = ret_n(prices, min(126,n-1))
    mom6m_history = []
    for i in range(1, min(253,n-126)):
        pc=prices[:n-i]; r=ret_n(pc,min(126,len(pc)-1))
        if r is not None: mom6m_history.append(r)
    pct_mom6 = percentile_in_own_history(mom6m_now, mom6m_history)
    details["mom6m"] = {
        "value": round(mom6m_now,2) if mom6m_now else None,
        "percentile": pct_mom6,
        "interpretation": (
            f"Momentum 6M excepcional (+{mom6m_now:.1f}%)" if mom6m_now and mom6m_now > 30
            else f"Momentum 6M fuerte (+{mom6m_now:.1f}%)" if mom6m_now and mom6m_now > 10
            else f"Momentum 6M positivo (+{mom6m_now:.1f}%)" if mom6m_now and mom6m_now > 0
            else f"Momentum 6M negativo ({mom6m_now:.1f}%)" if mom6m_now
            else "Sin datos momentum"
        )
    }

    # Factor 4: Punto de entrada
    dist_max_now = drawdown_from_max(prices, 252)
    dist_max_history = []
    for i in range(1, min(253,n-252)):
        pc=prices[:n-i]; d=drawdown_from_max(pc,min(252,len(pc)))
        if d is not None: dist_max_history.append(d)
    dist_max_inv_hist = [-d for d in dist_max_history if d is not None]
    dist_max_inv_now = -dist_max_now if dist_max_now is not None else None
    pct_entry = percentile_in_own_history(dist_max_inv_now, dist_max_inv_hist)
    details["entry"] = {
        "dist_from_max": dist_max_now,
        "percentile": pct_entry,
        "interpretation": (
            f"Excelente entrada: {dist_max_now:.0f}% bajo máximos" if dist_max_now and dist_max_now < -25
            else f"Buena entrada: {dist_max_now:.0f}% bajo máximos" if dist_max_now and dist_max_now < -10
            else f"Cerca de máximos ({dist_max_now:.0f}%) — entrada más exigente" if dist_max_now
            else "Sin datos"
        )
    }

    # Factor 5: Consistencia
    consist_now = consistency_6m(prices)
    consist_history = []
    for i in range(1, min(253,n-130)):
        pc=prices[:n-i]; c=consistency_6m(pc)
        if c is not None: consist_history.append(c)
    pct_consist = percentile_in_own_history(consist_now, consist_history)
    details["consistency"] = {
        "value": consist_now,
        "percentile": pct_consist,
        "interpretation": (
            f"Muy consistente ({consist_now:.0f}% meses positivos)" if consist_now and consist_now >= 80
            else f"Consistente ({consist_now:.0f}% meses positivos)" if consist_now and consist_now >= 60
            else f"Inconsistente ({consist_now:.0f}% meses positivos)" if consist_now
            else "Sin datos consistencia"
        )
    }

    score_tech = (
        W_TECH["rel_strength"] * pct_rel +
        W_TECH["ema200"]       * pct_ema +
        W_TECH["mom6m"]        * pct_mom6 +
        W_TECH["entry"]        * pct_entry +
        W_TECH["consistency"]  * pct_consist
    )

    mom3m = ret_n(prices, min(63,n-1))
    penalty = 1.0
    if mom3m is not None and mom3m < -10:
        penalty = 0.6
        details["penalty"] = {"applied": True, "reason": f"Caída fuerte 3M ({mom3m:.1f}%) — score penalizado ×0.6", "mom3m": round(mom3m,2)}
    else:
        details["penalty"] = {"applied": False, "mom3m": round(mom3m,2) if mom3m else None}

    details["extra"] = {
        "r1m":  round(ret_n(prices,21),2)  if ret_n(prices,21)  else None,
        "r3m":  round(mom3m,2)             if mom3m             else None,
        "r6m":  round(mom6m_now,2)         if mom6m_now         else None,
        "r12m": round(ret_n(prices,252),2) if ret_n(prices,252) else None,
        "vol":  round(vol_annual(prices),1) if vol_annual(prices) else None,
        "drawdown": dist_max_now,
        "ann_ret":  ann_ret(prices),
    }

    return round(score_tech * penalty, 1), details

def compute_macro_score(macro_profile, macro):
    if not macro: return 50, {}
    rates  = macro.get("interest_rates", {})
    vix    = macro.get("vix", {})
    dxy    = macro.get("dxy", {})
    inr    = macro.get("inr", {})
    ux     = macro.get("uranium_spot", {})
    halving= macro.get("bitcoin_halving", {})
    senti  = macro.get("market_sentiment", {})
    rates_score = rates.get("score", 50)
    vix_score   = vix.get("score", 50)
    dxy_inv     = dxy.get("score_inverse", 50)
    ux_score    = ux.get("score", 50)
    halv_score  = halving.get("halving_score", 50)
    contrarían  = senti.get("contrarian_buy", False)
    details = {}

    if macro_profile == "growth_rates_sensitive":
        score = rates_score*0.60 + vix_score*0.40
        details = {"tipos":{"weight":"60%","score":rates_score,"desc":rates.get("interpretation","")}, "vix":{"weight":"40%","score":vix_score,"desc":vix.get("interpretation","")}}
    elif macro_profile == "defensive_government":
        vix_inv = 100 - vix_score
        score = vix_inv*0.50 + rates_score*0.30 + 50*0.20
        details = {"vix_miedo":{"weight":"50%","score":vix_inv,"desc":"Defensa se beneficia del miedo geopolítico"}, "tipos":{"weight":"30%","score":rates_score,"desc":rates.get("interpretation","")}}
    elif macro_profile == "em_dollar_sensitive":
        score = dxy_inv*0.50 + rates_score*0.35 + 50*0.15
        if inr.get("trend") == "down": score *= 0.85; details["rupia"] = {"desc":"Rupia depreciándose — penalización aplicada"}
        elif inr.get("trend") == "up": score = min(100, score*1.05); details["rupia"] = {"desc":"Rupia apreciándose — bonus aplicado"}
        details.update({"dolar":{"weight":"50%","score":dxy_inv,"desc":dxy.get("interpretation","")}, "tipos":{"weight":"35%","score":rates_score,"desc":rates.get("interpretation","")}})
    elif macro_profile == "defensive_growth":
        score = rates_score*0.40 + vix_score*0.30 + 70*0.30
        details = {"tipos":{"weight":"40%","score":rates_score,"desc":rates.get("interpretation","")}, "vix":{"weight":"30%","score":vix_score,"desc":vix.get("interpretation","")}, "base":{"weight":"30%","score":70,"desc":"Demanda estructural no cíclica"}}
    elif macro_profile == "rates_debt_sensitive":
        score = rates_score*0.70 + vix_score*0.30
        details = {"tipos":{"weight":"70%","score":rates_score,"desc":rates.get("interpretation","")}, "vix":{"weight":"30%","score":vix_score,"desc":vix.get("interpretation","")}}
    elif macro_profile == "defensive_demographics":
        vix_inv = 100 - vix_score
        score = vix_inv*0.40 + rates_score*0.30 + 65*0.30
        details = {"refugio":{"weight":"40%","score":vix_inv,"desc":"Sector refugio en mercados bajistas"}, "tipos":{"weight":"30%","score":rates_score,"desc":rates.get("interpretation","")}, "demograf":{"weight":"30%","score":65,"desc":"Demografía de envejecimiento favorable"}}
    elif macro_profile == "crypto_halving":
        score = rates_score*0.35 + dxy_inv*0.30 + halv_score*0.35
        if contrarían: score = min(100, score*1.15); details["contrarian"] = {"desc":"VIX extremo y bajando — oportunidad contrarian histórica"}
        details.update({"tipos":{"weight":"35%","score":rates_score,"desc":rates.get("interpretation","")}, "dolar":{"weight":"30%","score":dxy_inv,"desc":dxy.get("interpretation","")}, "halving":{"weight":"35%","score":halv_score,"desc":halving.get("description","")}})
    elif macro_profile == "uranium_spot":
        score = ux_score*0.60 + rates_score*0.20 + vix_score*0.20
        details = {"uranio_spot":{"weight":"60%","score":ux_score,"desc":ux.get("interpretation","")}, "tipos":{"weight":"20%","score":rates_score,"desc":rates.get("interpretation","")}, "vix":{"weight":"20%","score":vix_score,"desc":vix.get("interpretation","")}}
    else:
        score = 50

    return round(min(100, max(0, score)), 1), details

def compute_final_score(score_tech, score_macro):
    return round(score_tech*0.70 + score_macro*0.30, 1)

def ema200_signal(prices):
    if len(prices) < 200: return "neutral"
    e200 = ema_n(prices, 200)
    if e200 is None: return "neutral"
    dd = drawdown_from_max(prices)
    months_below = 0
    for i in range(6):
        idx = -(21*(i+1))
        if abs(idx) > len(prices): break
        end_idx = len(prices) + idx + 21
        wp = prices[:end_idx]
        if len(wp) < 200: break
        e = ema_n(wp, 200)
        if e and wp[-1] < e: months_below += 1
        else: break
    if prices[-1] > e200: return "green"
    elif months_below >= 3 and dd is not None and dd < -15: return "red"
    else: return "yellow"

def build_portfolio_signals(cartera):
    signals = []
    for asset in cartera:
        prices, dates = fetch_history(asset["symbol"], "2y")
        if not prices or len(prices) < 60:
            signals.append({**asset, "signal":"neutral","signal_text":"Sin datos","dist_ema200":None,"r3m":None,"r12m":None,"drawdown":None,"sparkline":[],"spark_dates":[]})
            continue
        signal = ema200_signal(prices)
        e200 = ema_n(prices, 200)
        dist_e = round((prices[-1]/e200-1)*100,1) if e200 else None
        r3m = ret_n(prices, 63); r12m = ret_n(prices, 252); dd = drawdown_from_max(prices)
        text = ("Tesis intacta — EMA200 alcista. Sigue aportando." if signal=="green"
                else "Atención — por debajo de EMA200. Vigilar próximos meses." if signal=="yellow"
                else "Señal de salida — 3 meses bajo EMA200 y caída >15%. Considera rotar.")
        signals.append({**asset, "signal":signal, "signal_text":text,
            "dist_ema200":dist_e, "r3m":round(r3m,2) if r3m else None,
            "r12m":round(r12m,2) if r12m else None, "drawdown":dd,
            "sparkline":[round(p,4) for p in prices[-60:]], "spark_dates":dates[-60:] if dates else []})
    return signals

def build_reasons(etf_data, macro_details):
    ups, dns = [], []
    td = etf_data.get("tech_details", {})
    rs = td.get("rel_strength", {})
    if rs.get("value") is not None:
        pct = rs.get("percentile",50); val = rs["value"]
        if pct > 70: ups.append(f"Lidera al mercado global (+{val:.1f}% sobre MSCI World 6M) — percentil {pct:.0f}")
        elif pct < 30: dns.append(f"Va por detrás del mercado ({val:.1f}% vs MSCI World 6M) — percentil {pct:.0f}")
    em = td.get("ema200", {})
    if em.get("value") is not None:
        pct = em.get("percentile",50); val = em["value"]
        if pct > 70 and val > 0: ups.append(f"{em['interpretation']} — momento excepcional (percentil {pct:.0f})")
        elif val > 0: ups.append(f"{em['interpretation']}")
        elif pct < 30: dns.append(f"{em['interpretation']} — momento débil (percentil {pct:.0f})")
    m6 = td.get("mom6m", {})
    if m6.get("value") is not None:
        pct = m6.get("percentile",50)
        if pct > 75: ups.append(f"{m6['interpretation']} — percentil histórico {pct:.0f}")
        elif pct < 25: dns.append(f"{m6['interpretation']} — percentil histórico {pct:.0f}")
    en = td.get("entry", {})
    if en.get("dist_from_max") is not None:
        pct = en.get("percentile",50)
        if pct > 65: ups.append(f"{en['interpretation']} — mejor que {pct:.0f}% del tiempo")
        elif pct < 35: dns.append(f"{en['interpretation']}")
    co = td.get("consistency", {})
    if co.get("value") is not None:
        if co["percentile"] > 70: ups.append(f"{co['interpretation']}")
        elif co["percentile"] < 30: dns.append(f"{co['interpretation']}")
    pen = td.get("penalty", {})
    if pen.get("applied"): dns.append(pen.get("reason",""))
    for key, md in macro_details.items():
        if isinstance(md, dict) and md.get("desc"):
            score = md.get("score", 50)
            if score > 70: ups.append(f"Macro: {md['desc']}")
            elif score < 30: dns.append(f"Macro: {md['desc']}")
    return ups[:4], dns[:3]

def best_etf_per_sector(records):
    sectors = {}
    for r in records:
        s = r["sector"]
        if s not in sectors or r["score_final"] > sectors[s]["score_final"]:
            sectors[s] = r
    return list(sectors.values())

def build_recommendation(sector_ranking, month_str, portfolio_signals):
    if not sector_ranking:
        return {"mes":month_str,"accion_principal":"Sin datos suficientes","distribucion":[],"nota":""}
    top1 = sector_ranking[0]
    top2 = sector_ranking[1] if len(sector_ranking) > 1 else None
    ya_tiene = any(s["symbol"] == top1["symbol"] for s in portfolio_signals)
    accion = (f"Añade más a lo que ya tienes: {top1['name']} ({top1['symbol']}) — sigue siendo el #1"
              if ya_tiene else f"Aporta este mes en: {top1['name']} ({top1['symbol']})")
    score1 = top1["score_final"]
    if score1 >= 70:   dist1,dist2,calidad = 350,150,"🟢 Señal fuerte"
    elif score1 >= 55: dist1,dist2,calidad = 300,200,"🟡 Señal moderada"
    else:              dist1,dist2,calidad = 250,250,"🟠 Señal débil — diversifica más"
    distribucion = [{"rank":1,"name":top1["name"],"symbol":top1["symbol"],"sector":top1["sector"],"score":score1,"euros":dist1,"pct":round(dist1/500*100)}]
    if top2: distribucion.append({"rank":2,"name":top2["name"],"symbol":top2["symbol"],"sector":top2["sector"],"score":top2["score_final"],"euros":dist2,"pct":round(dist2/500*100)})
    return {"mes":month_str,"calidad":calidad,"score_top1":score1,"accion_principal":accion,
            "distribucion":distribucion,"por_que":top1.get("reasons_up",[])[:2],
            "nota":"Revisa las señales de tu cartera actual. Si alguna está en 🔴 rojo, rota antes de añadir nueva posición."}

def main():
    with open(UNI, encoding="utf-8") as f:
        universe = json.load(f)["etfs"]
    macro = {}
    if os.path.exists(MACRO):
        with open(MACRO, encoding="utf-8") as f:
            macro = json.load(f)
    else:
        print("  Warning: macro.json no encontrado.")
    print("Descargando IWDA benchmark...")
    iwda_prices, _ = fetch_history("IWDA.AS", "2y")
    print(f"Analizando {len(universe)} ETFs (modelo v6)...")
    records = []
    for etf in universe:
        sym = etf["symbol"]
        print(f"  {sym}...", end=" ", flush=True)
        prices, dates = fetch_history(sym, "2y")
        if not prices or len(prices) < 60: print("sin datos"); continue
        score_tech, tech_details = compute_technical_score(prices, iwda_prices)
        if score_tech is None: print("insuficiente"); continue
        score_macro, macro_details = compute_macro_score(etf.get("macro_profile",""), macro)
        score_final = compute_final_score(score_tech, score_macro)
        fund = fetch_pe(sym)
        extra = tech_details.get("extra", {})
        rec = {
            "id":etf["id"],"name":etf["name"],"symbol":sym,"sector":etf["sector"],
            "conviction":etf.get("conviction",4),"macro_profile":etf.get("macro_profile",""),
            "last":round(prices[-1],4),
            "score_tech":score_tech,"score_macro":score_macro,"score_final":score_final,
            "pct_rel_strength":tech_details.get("rel_strength",{}).get("percentile"),
            "pct_ema200":tech_details.get("ema200",{}).get("percentile"),
            "pct_mom6m":tech_details.get("mom6m",{}).get("percentile"),
            "pct_entry":tech_details.get("entry",{}).get("percentile"),
            "pct_consistency":tech_details.get("consistency",{}).get("percentile"),
            "rel_strength":tech_details.get("rel_strength",{}).get("value"),
            "dist_ema200":tech_details.get("ema200",{}).get("value"),
            "ema200_abs":tech_details.get("ema200",{}).get("ema200_abs"),
            "dist_from_max":tech_details.get("entry",{}).get("dist_from_max"),
            "consistency_pct":tech_details.get("consistency",{}).get("value"),
            "mom_penalty":not tech_details.get("penalty",{}).get("applied",False),
            "r1m":extra.get("r1m"),"r3m":extra.get("r3m"),"r6m":extra.get("r6m"),
            "r12m":extra.get("r12m"),"vol":extra.get("vol"),
            "drawdown":extra.get("drawdown"),"ann_ret":extra.get("ann_ret"),
            "pe":fund.get("pe"),"beta":fund.get("beta"),"dy":fund.get("dy"),
            "sparkline":[round(p,4) for p in prices[-60:]],
            "spark_dates":dates[-60:] if dates else [],
            "tech_details":tech_details,"macro_details":macro_details,
        }
        ups, dns = build_reasons(rec, macro_details)
        rec["reasons_up"] = ups; rec["reasons_down"] = dns
        del rec["tech_details"]; del rec["macro_details"]
        records.append(rec)
        print(f"tech={score_tech:.0f} macro={score_macro:.0f} final={score_final:.0f}{'⚠️' if not rec['mom_penalty'] else ''}")
    if not records: print("ERROR: sin datos"); return
    records.sort(key=lambda x: x["score_final"], reverse=True)
    sector_ranking = best_etf_per_sector(records)
    sector_ranking.sort(key=lambda x: x["score_final"], reverse=True)
    print("\nAnalizando cartera actual...")
    portfolio_signals = build_portfolio_signals(CARTERA)
    for s in portfolio_signals:
        icon = "✅" if s["signal"]=="green" else ("⚠️" if s["signal"]=="yellow" else "🔴")
        print(f"  {icon} {s['symbol']}: {s['signal_text']}")
    month_str = datetime.date.today().strftime("%B %Y")
    recommendation = build_recommendation(sector_ranking, month_str, portfolio_signals)
    macro_context = {
        "tipos":macro.get("interest_rates",{}).get("interpretation","Sin datos"),
        "vix":macro.get("vix",{}).get("interpretation","Sin datos"),
        "dolar":macro.get("dxy",{}).get("interpretation","Sin datos"),
        "halving":macro.get("bitcoin_halving",{}).get("description","Sin datos"),
        "fred":macro.get("fred_available",False),
        "updated":macro.get("updated",""),
    }
    out = {
        "updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z",
        "total_analyzed":len(records),"model_version":"6.0",
        "recommendation":recommendation,"portfolio_signals":portfolio_signals,
        "sector_ranking":sector_ranking,"all":records,
        "macro_context":macro_context,"warnings":WARN,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\n{'='*60}")
    print(f"RECOMENDACIÓN {month_str} — {recommendation['calidad']}")
    print(f"  {recommendation['accion_principal']}")
    for d in recommendation.get("distribucion",[]):
        print(f"  #{d['rank']} {d['symbol']:10s} score={d['score']:5.1f} → €{d['euros']} ({d['pct']}%)")
    print(f"\nRANKING SECTORES:")
    for i,r in enumerate(sector_ranking[:5]):
        print(f"  #{i+1} {r['sector']:20s} {r['symbol']:10s} score={r['score_final']:5.1f} (T:{r['score_tech']:.0f} M:{r['score_macro']:.0f})")
    print(f"{'='*60}")
    print(f"Avisos: {len(WARN)}")

if __name__ == "__main__":
    main()
