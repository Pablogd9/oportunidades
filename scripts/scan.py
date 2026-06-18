#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor del escaner de oportunidades - version 2.
Modelo de factores basado en evidencia academica:

  1. Momentum ajustado (12M - 1M): Jegadeesh & Titman 1993.
  2. Tendencia (vs SMA200): time series momentum.
  3. Sharpe implicito (retorno 12M / volatilidad).
  4. Valoracion relativa (PER vs media del sector).
  5. Señal de entrada (RSI + distancia a SMA50).

Todos los factores se normalizan en [0,1] sobre el universo completo.
Sin dependencias externas. Solo libreria estandar Python.
"""

import json, math, os, re, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI  = os.path.join(ROOT, "universe.json")
OUT  = os.path.join(ROOT, "data", "output.json")
UA   = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityScanner/2.0)"}
WARN = []

WEIGHTS = {
    "momentum_adj": 0.35,
    "tendencia":    0.25,
    "sharpe_impl":  0.20,
    "entrada":      0.12,
    "valoracion":   0.08,
}

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_history(symbol, rng="1y"):
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
    rets = [prices[i]/prices[i-1]-1 for i in range(max(1, len(prices)-n), len(prices))]
    if len(rets) < 5: return None
    mean = sum(rets)/len(rets)
    sd = math.sqrt(sum((r-mean)**2 for r in rets)/(len(rets)-1))
    return sd * math.sqrt(252) * 100

def rsi_14(prices):
    if len(prices) < 15: return None
    changes = [prices[i]-prices[i-1] for i in range(1,len(prices))][-14:]
    gains  = [max(c,0) for c in changes]
    losses = [abs(min(c,0)) for c in changes]
    ag, al = sum(gains)/14, sum(losses)/14
    if al == 0: return 100.0
    return round(100 - 100/(1 + ag/al), 1)

def drawdown_from_max(prices, n=252):
    if len(prices) < 2: return None
    window = prices[-min(n, len(prices)):]
    peak = max(window)
    return round((prices[-1]/peak - 1)*100, 2) if peak > 0 else None

def ann_ret(prices, n=252):
    actual = min(n, len(prices)-1)
    if actual < 20: return None
    return round((prices[-1]/prices[-actual-1])**(252/actual)*100 - 100, 1)

def compute_factors(prices):
    if not prices or len(prices) < 60:
        return None
    r12 = ret_n(prices, 252)
    r1  = ret_n(prices, 21)
    if r12 is None: r12 = ret_n(prices, len(prices)-1)
    mom_adj = (r12 - r1) if (r12 is not None and r1 is not None) else r12
    sma200 = sma_n(prices, 200) or sma_n(prices, 100) or sma_n(prices, 60)
    trend = ((prices[-1]/sma200 - 1)*100) if sma200 else None
    vol = vol_annual(prices, 60)
    sharpe_impl = (r12 / vol) if (r12 is not None and vol and vol > 0) else None
    rsi = rsi_14(prices)
    sma50 = sma_n(prices, 50)
    dist_sma50 = ((prices[-1]/sma50 - 1)*100) if sma50 else 0
    if rsi is not None:
        rsi_score = max(0, 100 - abs(rsi - 50) * 2)
        stretch_penalty = max(0, min(1, dist_sma50/20)) if dist_sma50 > 10 else 0
        entry = rsi_score * (1 - stretch_penalty)
    else:
        entry = None
    return {
        "mom_adj":     round(mom_adj, 2)    if mom_adj    is not None else None,
        "trend":       round(trend, 2)      if trend      is not None else None,
        "sharpe_impl": round(sharpe_impl,3) if sharpe_impl is not None else None,
        "entry":       round(entry, 1)      if entry      is not None else None,
        "r1m":  round(ret_n(prices,21),2)   if ret_n(prices,21)  is not None else None,
        "r3m":  round(ret_n(prices,63),2)   if ret_n(prices,63)  is not None else None,
        "r6m":  round(ret_n(prices,126),2)  if ret_n(prices,126) is not None else None,
        "r12m": round(r12,2)                if r12               is not None else None,
        "vol":  round(vol,1)                if vol               is not None else None,
        "rsi":  rsi,
        "sma50":  round(sma50,4)  if sma50  else None,
        "sma200": round(sma200,4) if sma200 else None,
        "dist_sma50":  round(dist_sma50,1),
        "drawdown": drawdown_from_max(prices),
        "ann_ret":  ann_ret(prices),
    }

def normalize_cross(records, key):
    vals = [r[key] for r in records if r.get(key) is not None]
    if len(vals) < 2:
        for r in records: r[f"_n_{key}"] = 0.5
        return
    mn, mx = min(vals), max(vals)
    rng = mx - mn
    median = sorted(vals)[len(vals)//2]
    for r in records:
        v = r.get(key)
        if v is None: v = median
        r[f"_n_{key}"] = (v - mn) / rng if rng > 0 else 0.5

def normalize_pe_within_sector(records):
    sectors = {}
    for r in records:
        s = r.get("sector","")
        if s not in sectors: sectors[s] = []
        if r.get("pe"): sectors[s].append(r["pe"])
    for r in records:
        s = r.get("sector","")
        pe = r.get("pe")
        vals = sectors.get(s, [])
        if not pe or len(vals) < 2:
            r["_n_pe"] = 0.5
            continue
        mn, mx = min(vals), max(vals)
        rng = mx - mn
        r["_n_pe"] = 1 - ((pe - mn)/rng) if rng > 0 else 0.5

def compute_score(r):
    return round((
        WEIGHTS["momentum_adj"] * r.get("_n_mom_adj", 0.5) +
        WEIGHTS["tendencia"]    * r.get("_n_trend",   0.5) +
        WEIGHTS["sharpe_impl"]  * r.get("_n_sharpe_impl", 0.5) +
        WEIGHTS["entrada"]      * r.get("_n_entry",   0.5) +
        WEIGHTS["valoracion"]   * r.get("_n_pe",      0.5)
    ) * 100, 1)

def build_reasons(r):
    ups, dns = [], []
    mom = r.get("mom_adj")
    if mom is not None:
        if mom > 20:   ups.append(f"Momentum ajustado muy fuerte (+{mom:.1f}%) — tendencia sólida")
        elif mom > 5:  ups.append(f"Momentum ajustado positivo (+{mom:.1f}%)")
        elif mom < -15:dns.append(f"Momentum negativo ({mom:.1f}%) — tendencia débil")
    trend = r.get("trend")
    if trend is not None:
        if trend > 15:   ups.append(f"Muy por encima de SMA200 (+{trend:.1f}%) — tendencia alcista fuerte")
        elif trend > 5:  ups.append(f"Por encima de SMA200 (+{trend:.1f}%) — tendencia positiva")
        elif trend < -5: dns.append(f"Por debajo de SMA200 ({trend:.1f}%) — tendencia bajista")
    sh = r.get("sharpe_impl")
    vol = r.get("vol")
    if sh is not None:
        if sh > 1.5:   ups.append(f"Excelente calidad de retorno (Sharpe impl. {sh:.2f})")
        elif sh > 0.8: ups.append(f"Buena relación retorno/riesgo (Sharpe impl. {sh:.2f})")
        elif sh < 0:
            if vol: dns.append(f"Retorno negativo con alta volatilidad ({vol:.0f}%)")
    rsi = r.get("rsi")
    dist = r.get("dist_sma50", 0)
    if rsi is not None:
        if rsi < 30:       ups.append(f"RSI en sobreventa ({rsi:.0f}) — posible rebote técnico")
        elif rsi < 45:     ups.append(f"RSI neutral-bajo ({rsi:.0f}) — zona de entrada favorable")
        elif 45<=rsi<=60:  ups.append(f"RSI neutral ({rsi:.0f}) — momento de entrada equilibrado")
        elif rsi > 70:     dns.append(f"RSI en sobrecompra ({rsi:.0f}) — entrada tardía")
    if dist > 15:          dns.append(f"Precio muy estirado sobre SMA50 (+{dist:.0f}%) — riesgo de corrección")
    pe = r.get("pe")
    pe_norm = r.get("_n_pe", 0.5)
    if pe:
        if pe_norm > 0.7:  ups.append(f"PER ({pe:.0f}x) bajo para su sector — valoración atractiva")
        elif pe_norm < 0.3:dns.append(f"PER ({pe:.0f}x) alto para su sector — valoración exigente")
    dd = r.get("drawdown")
    if dd is not None and dd < -25:
        ups.append(f"Caída desde máximos del {dd:.0f}% — potencial de recuperación")
    return ups[:4], dns[:3]

def main():
    raw = open(UNI, encoding="utf-8").read()
    universe = json.loads(raw)["etfs"]
    print(f"Analizando {len(universe)} ETFs con modelo de factores v2...")
    records = []
    for etf in universe:
        sym = etf["symbol"]
        print(f"  {sym}...", end=" ", flush=True)
        prices, dates = fetch_history(sym, "1y")
        if not prices or len(prices) < 30:
            print("sin datos"); continue
        factors = compute_factors(prices)
        if not factors:
            print("insuficiente"); continue
        fund = fetch_pe(sym)
        rec = {
            "id": etf["id"], "name": etf["name"], "symbol": sym, "sector": etf["sector"],
            "last": round(prices[-1], 4),
            "mom_adj": factors["mom_adj"], "trend": factors["trend"],
            "sharpe_impl": factors["sharpe_impl"], "entry": factors["entry"],
            "r1m": factors["r1m"], "r3m": factors["r3m"],
            "r6m": factors["r6m"], "r12m": factors["r12m"],
            "vol": factors["vol"], "rsi": factors["rsi"],
            "sma50": factors["sma50"], "sma200": factors["sma200"],
            "dist_sma50": factors["dist_sma50"],
            "drawdown": factors["drawdown"], "ann_ret": factors["ann_ret"],
            "pe": fund.get("pe"), "beta": fund.get("beta"), "dy": fund.get("dy"),
            "sparkline":   [round(p,4) for p in prices[-60:]],
            "spark_dates": dates[-60:],
        }
        records.append(rec)
        print(f"ok score pendiente")
    if not records:
        print("ERROR: sin datos"); return
    normalize_cross(records, "mom_adj")
    normalize_cross(records, "trend")
    normalize_cross(records, "sharpe_impl")
    normalize_cross(records, "entry")
    normalize_pe_within_sector(records)
    for r in records:
        r["score"] = compute_score(r)
        r["score_momentum"]  = round(r.get("_n_mom_adj",0.5)*100, 0)
        r["score_tendencia"] = round(r.get("_n_trend",0.5)*100, 0)
        r["score_sharpe"]    = round(r.get("_n_sharpe_impl",0.5)*100, 0)
        r["score_entrada"]   = round(r.get("_n_entry",0.5)*100, 0)
        r["score_valoracion"]= round(r.get("_n_pe",0.5)*100, 0)
        for k in list(r.keys()):
            if k.startswith("_n_"): del r[k]
        ups, dns = build_reasons(r)
        r["reasons_up"] = ups
        r["reasons_down"] = dns
    records.sort(key=lambda x: x["score"], reverse=True)
    best_sector = {}
    for r in records:
        s = r["sector"]
        if s not in best_sector: best_sector[s] = r
    out = {
        "updated":        datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "total_analyzed": len(records),
        "model_version":  "2.0",
        "factor_weights": WEIGHTS,
        "top10":          records[:10],
        "all":            records,
        "best_by_sector": list(best_sector.values()),
        "warnings":       WARN,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\nOK. {len(records)} ETFs analizados. Top 5:")
    for r in records[:5]:
        print(f"  {r['score']:5.1f} — {r['name'][:45]} ({r['symbol']})")
    print(f"Avisos: {len(WARN)}")

if __name__ == "__main__":
    main()
