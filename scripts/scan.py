#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor del escaner de oportunidades - version 4 (largo plazo).

Criterios:
  1. Tendencia secular (40%): retorno 2 anos completos.
  2. Calidad de tendencia (25%): consistencia mensual 12M.
  3. Punto de entrada (20%): distancia al maximo del ultimo ano.
  4. Momentum reciente moderado (15%): retorno 3 meses.
"""

import json, math, os, re, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI  = os.path.join(ROOT, "universe.json")
OUT  = os.path.join(ROOT, "data", "output.json")
UA   = {"User-Agent": "Mozilla/5.0 (compatible; LongTermScanner/4.0)"}
WARN = []

WEIGHTS = {
    "secular":    0.40,
    "quality":    0.25,
    "entry":      0.20,
    "momentum3m": 0.15,
}

LEVERAGED      = {"Apalancado"}
MAX_PER_SECTOR = 2

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

def ret_n(prices, n):
    if len(prices) < n + 1: return None
    p0, p1 = prices[-(n+1)], prices[-1]
    return (p1 / p0 - 1) * 100 if p0 > 0 else None

def sma_n(prices, n):
    if len(prices) < n: return None
    return sum(prices[-n:]) / n

def vol_annual(prices, n=60):
    if len(prices) < n + 1: return None
    rets = [prices[i]/prices[i-1]-1 for i in range(max(1,len(prices)-n), len(prices))]
    if len(rets) < 5: return None
    mean = sum(rets)/len(rets)
    sd = math.sqrt(sum((r-mean)**2 for r in rets)/(len(rets)-1))
    return sd * math.sqrt(252) * 100

def drawdown_from_max(prices, n=252):
    if len(prices) < 2: return None
    window = prices[-min(n, len(prices)):]
    peak = max(window)
    return round((prices[-1]/peak - 1)*100, 2) if peak > 0 else None

def ann_ret(prices, n=252):
    actual = min(n, len(prices)-1)
    if actual < 20: return None
    return round((prices[-1]/prices[-actual-1])**(252/actual)*100 - 100, 1)

def consistency_12m(prices):
    if len(prices) < 270: return None
    monthly_rets = []
    for i in range(12):
        start = -(21*(i+1)+1)
        end   = -(21*i+1) if i > 0 else -1
        if abs(start) >= len(prices): continue
        p0 = prices[start]
        p1 = prices[end]
        if p0 > 0:
            monthly_rets.append(p1/p0 - 1)
    if len(monthly_rets) < 6: return None
    positive = sum(1 for r in monthly_rets if r > 0)
    return round(positive / len(monthly_rets) * 100, 0)

def distance_from_max_1y(prices):
    if len(prices) < 50: return None
    window = prices[-min(252, len(prices)):]
    peak = max(window)
    return round((prices[-1]/peak - 1)*100, 2) if peak > 0 else None

def secular_return(prices):
    if len(prices) < 60: return None
    return round((prices[-1]/prices[0] - 1)*100, 1)

def compute_factors(prices):
    if not prices or len(prices) < 60: return None
    secular  = secular_return(prices)
    quality  = consistency_12m(prices)
    dist_max = distance_from_max_1y(prices)
    entry_raw = min(100, max(0, -dist_max * 2)) if dist_max is not None else None
    mom3m    = ret_n(prices, 63)
    r1m      = ret_n(prices, 21)
    r6m      = ret_n(prices, 126)
    r12m     = ret_n(prices, 252)
    vol      = vol_annual(prices, 60)
    sma50    = sma_n(prices, 50)
    sma200   = sma_n(prices, 200)
    dd       = drawdown_from_max(prices)
    ar       = ann_ret(prices)
    dist_sma200 = ((prices[-1]/sma200 - 1)*100) if sma200 else None
    return {
        "secular":    secular,
        "quality":    quality,
        "entry_raw":  entry_raw,
        "mom3m":      mom3m,
        "dist_max":   dist_max,
        "r1m": r1m, "r3m": mom3m, "r6m": r6m, "r12m": r12m,
        "vol": vol, "drawdown": dd, "ann_ret": ar,
        "dist_sma200": dist_sma200,
        "sma50":  round(sma50,4)  if sma50  else None,
        "sma200": round(sma200,4) if sma200 else None,
    }

def normalize_cross(records, key):
    vals = [r["factors"][key] for r in records if r["factors"].get(key) is not None]
    if len(vals) < 2:
        for r in records: r["norm"][key] = 0.5
        return
    mn, mx = min(vals), max(vals)
    rng = mx - mn
    median = sorted(vals)[len(vals)//2]
    for r in records:
        v = r["factors"].get(key)
        if v is None: v = median
        r["norm"][key] = (v - mn) / rng if rng > 0 else 0.5

def normalize_pe_within_sector(records):
    sectors = {}
    for r in records:
        s = r.get("sector","")
        if s not in sectors: sectors[s] = []
        if r.get("pe"): sectors[s].append(r["pe"])
    for r in records:
        s  = r.get("sector","")
        pe = r.get("pe")
        vals = sectors.get(s, [])
        if not pe or len(vals) < 2:
            r["norm"]["pe"] = 0.5; continue
        mn, mx = min(vals), max(vals)
        rng = mx - mn
        r["norm"]["pe"] = 1 - ((pe-mn)/rng) if rng > 0 else 0.5

def compute_score(r):
    return round((
        WEIGHTS["secular"]    * r["norm"].get("secular",    0.5) +
        WEIGHTS["quality"]    * r["norm"].get("quality",    0.5) +
        WEIGHTS["entry"]      * r["norm"].get("entry_raw",  0.5) +
        WEIGHTS["momentum3m"] * r["norm"].get("mom3m",      0.5)
    ) * 100, 1)

def build_reasons(r):
    """r todavia tiene r['factors'] cuando se llama esta funcion."""
    ups, dns = [], []
    f = r["factors"]

    sec = f.get("secular")
    if sec is not None:
        if sec > 60:   ups.append(f"Tendencia secular muy fuerte (+{sec:.0f}% en 2 años)")
        elif sec > 20: ups.append(f"Tendencia secular positiva (+{sec:.0f}% en 2 años)")
        elif sec < 0:  dns.append(f"Tendencia secular negativa ({sec:.0f}% en 2 años)")

    qual = f.get("quality")
    if qual is not None:
        if qual >= 75:   ups.append(f"Tendencia muy consistente ({qual:.0f}% meses positivos en 12M)")
        elif qual >= 58: ups.append(f"Tendencia consistente ({qual:.0f}% meses positivos en 12M)")
        elif qual <= 42: dns.append(f"Tendencia inconsistente ({qual:.0f}% meses positivos)")

    dist = f.get("dist_max")
    if dist is not None:
        if dist < -30:   ups.append(f"Excelente punto de entrada: {dist:.0f}% bajo máximos")
        elif dist < -15: ups.append(f"Buen punto de entrada: {dist:.0f}% bajo máximos")
        elif dist > -5:  dns.append(f"Cerca de máximos históricos ({dist:.0f}%) — entrada exigente")

    m3 = f.get("mom3m")
    if m3 is not None:
        if m3 > 10:    ups.append(f"Momentum 3M positivo (+{m3:.1f}%) — mercado confirma la tendencia")
        elif m3 > 0:   ups.append(f"Momentum 3M levemente positivo (+{m3:.1f}%)")
        elif m3 < -15: dns.append(f"Corrección reciente fuerte ({m3:.1f}% en 3M)")

    d200 = f.get("dist_sma200")
    if d200 is not None:
        if d200 > 0:     ups.append(f"Por encima de la media de 200 días (+{d200:.1f}%)")
        elif d200 < -10: dns.append(f"Por debajo de la media de 200 días ({d200:.1f}%)")

    pe      = r.get("pe")
    pe_norm = r["norm"].get("pe", 0.5)
    if pe:
        if pe_norm > 0.7:  ups.append(f"PER ({pe:.0f}x) bajo para su sector")
        elif pe_norm < 0.3:dns.append(f"PER ({pe:.0f}x) alto para su sector")

    return ups[:4], dns[:3]

def build_recommendation(top3, month_str):
    if not top3: return {}
    t1 = top3[0]
    return {
        "mes": month_str,
        "accion_principal": f"Aporta este mes en: {t1['name']} ({t1['symbol']})",
        "por_que": t1.get("reasons_up", [])[:2],
        "score": t1["score"],
        "alternativa_2": f"{top3[1]['name']} ({top3[1]['symbol']})" if len(top3) > 1 else None,
        "alternativa_3": f"{top3[2]['name']} ({top3[2]['symbol']})" if len(top3) > 2 else None,
        "nota": "Si ya tienes el Top 1 y quieres diversificar, considera el Top 2. El sistema sugiere el mejor independientemente de lo que ya tengas."
    }

def build_top3_diversified(records):
    non_lev = [r for r in records if r.get("sector") not in LEVERAGED]
    sector_count = {}
    top3 = []
    for r in non_lev:
        s = r.get("sector","")
        if sector_count.get(s, 0) >= MAX_PER_SECTOR: continue
        top3.append(r)
        sector_count[s] = sector_count.get(s, 0) + 1
        if len(top3) >= 3: break
    return top3

def main():
    raw = open(UNI, encoding="utf-8").read()
    raw = re.sub(r'//[^\n]*', '', raw)
    universe = json.loads(raw)["etfs"]
    print(f"Analizando {len(universe)} ETFs (modelo v4 — largo plazo)...")
    records = []

    for etf in universe:
        sym = etf["symbol"]
        print(f"  {sym}...", end=" ", flush=True)
        prices, dates = fetch_history(sym, "2y")
        if not prices or len(prices) < 60:
            print("sin datos"); continue
        factors = compute_factors(prices)
        if not factors:
            print("insuficiente"); continue
        fund = fetch_pe(sym)
        rec = {
            "id":     etf["id"],
            "name":   etf["name"],
            "symbol": sym,
            "sector": etf["sector"],
            "last":   round(prices[-1], 4),
            "factors": factors,
            "norm":    {},
            "pe":   fund.get("pe"),
            "beta": fund.get("beta"),
            "dy":   fund.get("dy"),
            "sparkline":   [round(p,4) for p in prices[-60:]],
            "spark_dates": dates[-60:],
        }
        records.append(rec)
        print("ok")

    if not records:
        print("ERROR: sin datos"); return

    normalize_cross(records, "secular")
    normalize_cross(records, "quality")
    normalize_cross(records, "entry_raw")
    normalize_cross(records, "mom3m")
    normalize_pe_within_sector(records)

    for r in records:
        r["score"]          = compute_score(r)
        r["score_secular"]  = round(r["norm"].get("secular",   0.5)*100, 0)
        r["score_quality"]  = round(r["norm"].get("quality",   0.5)*100, 0)
        r["score_entry"]    = round(r["norm"].get("entry_raw", 0.5)*100, 0)
        r["score_momentum3m"] = round(r["norm"].get("mom3m",   0.5)*100, 0)
        r["score_valoracion"] = round(r["norm"].get("pe",      0.5)*100, 0)
        r["r1m"]         = r["factors"].get("r1m")
        r["r3m"]         = r["factors"].get("r3m")
        r["r6m"]         = r["factors"].get("r6m")
        r["r12m"]        = r["factors"].get("r12m")
        r["vol"]         = r["factors"].get("vol")
        r["drawdown"]    = r["factors"].get("drawdown")
        r["ann_ret"]     = r["factors"].get("ann_ret")
        r["dist_max"]    = r["factors"].get("dist_max")
        r["dist_sma200"] = r["factors"].get("dist_sma200")
        r["secular_ret"] = r["factors"].get("secular")
        r["quality_pct"] = r["factors"].get("quality")
        # build_reasons ANTES de borrar factors
        ups, dns = build_reasons(r)
        r["reasons_up"]   = ups
        r["reasons_down"] = dns
        # ahora si borramos factors y norm
        del r["factors"]
        del r["norm"]

    records.sort(key=lambda x: x["score"], reverse=True)
    top3  = build_top3_diversified(records)
    top10 = records[:10]

    best_sector = {}
    for r in records:
        s = r["sector"]
        if s not in best_sector: best_sector[s] = r

    month_str      = datetime.date.today().strftime("%B %Y")
    recommendation = build_recommendation(top3, month_str)

    out = {
        "updated":        datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "total_analyzed": len(records),
        "model_version":  "4.0",
        "factor_weights": WEIGHTS,
        "recommendation": recommendation,
        "top3":           top3,
        "top10":          top10,
        "all":            records,
        "best_by_sector": list(best_sector.values()),
        "warnings":       WARN,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print(f"\nOK. {len(records)} ETFs (modelo largo plazo v4)")
    print(f"\n{'='*55}")
    print(f"RECOMENDACIÓN DE ESTE MES:")
    print(f"  {recommendation.get('accion_principal','—')}")
    for r in top3:
        print(f"  #{top3.index(r)+1} {r['symbol']:10s} [{r['sector'][:15]:15s}] score={r['score']:5.1f} secular={r.get('secular_ret','?')}% quality={r.get('quality_pct','?')}%")
    print(f"{'='*55}")
    print(f"Avisos: {len(WARN)}")

if __name__ == "__main__":
    main()
