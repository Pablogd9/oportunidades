#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor del escaner de oportunidades - version 3.
Mejoras vs v2:
- Limite de 2 ETFs por sector en el Top10 (evita sesgo de concentracion).
- Penalizacion por sobreextension (momentum > 30% en 6M reduce score).
- ETFs apalancados excluidos del Top10 (no aptos para largo plazo).
- Nuevas metricas: consistencia de tendencia, ratio recuperacion.
"""

import json, math, os, re, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI  = os.path.join(ROOT, "universe.json")
OUT  = os.path.join(ROOT, "data", "output.json")
UA   = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityScanner/3.0)"}
WARN = []

WEIGHTS = {
    "momentum_adj": 0.35,
    "tendencia":    0.25,
    "sharpe_impl":  0.20,
    "entrada":      0.12,
    "valoracion":   0.08,
}

LEVERAGED = {"Apalancado"}
MAX_PER_SECTOR = 2

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
    rets = [prices[i]/prices[i-1]-1 for i in range(max(1,len(prices)-n), len(prices))]
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

def consistency_6m(prices):
    if len(prices) < 130: return None
    monthly_rets = []
    for i in range(6):
        start = -(21*(i+1)+1)
        end   = -(21*i+1) if i > 0 else -1
        if abs(start) >= len(prices): continue
        p0 = prices[start]
        p1 = prices[end]
        if p0 > 0:
            monthly_rets.append(p1/p0 - 1)
    if not monthly_rets: return None
    positive = sum(1 for r in monthly_rets if r > 0)
    return round(positive / len(monthly_rets) * 100, 0)

def recovery_ratio(prices, n=252):
    dd = drawdown_from_max(prices, n)
    ar = ann_ret(prices, n)
    if dd is None or ar is None or dd == 0: return None
    return round(ar / abs(dd), 2)

def overextension_penalty(r6m):
    if r6m is None: return 1.0
    if r6m > 50: return 0.70
    if r6m > 30: return 0.85
    return 1.0

def compute_factors(prices):
    if not prices or len(prices) < 60: return None
    r12 = ret_n(prices, min(252, len(prices)-1))
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
    r6m = ret_n(prices, 126)
    return {
        "mom_adj": mom_adj, "trend": trend,
        "sharpe_impl": sharpe_impl, "entry": entry,
        "r1m":  ret_n(prices,21), "r3m":  ret_n(prices,63),
        "r6m":  r6m, "r12m": r12,
        "vol":  vol, "rsi":  rsi,
        "sma50": sma50, "sma200": sma200, "dist_sma50": dist_sma50,
        "drawdown": drawdown_from_max(prices),
        "ann_ret":  ann_ret(prices),
        "consistency_6m": consistency_6m(prices),
        "recovery_ratio": recovery_ratio(prices),
        "overext_penalty": overextension_penalty(r6m),
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
        s = r.get("sector","")
        pe = r.get("pe")
        vals = sectors.get(s, [])
        if not pe or len(vals) < 2:
            r["norm"]["pe"] = 0.5; continue
        mn, mx = min(vals), max(vals)
        rng = mx - mn
        r["norm"]["pe"] = 1 - ((pe - mn)/rng) if rng > 0 else 0.5

def compute_score(r):
    base = (
        WEIGHTS["momentum_adj"] * r["norm"].get("mom_adj", 0.5) +
        WEIGHTS["tendencia"]    * r["norm"].get("trend",   0.5) +
        WEIGHTS["sharpe_impl"]  * r["norm"].get("sharpe_impl", 0.5) +
        WEIGHTS["entrada"]      * r["norm"].get("entry",   0.5) +
        WEIGHTS["valoracion"]   * r["norm"].get("pe",      0.5)
    ) * 100
    penalty = r["factors"].get("overext_penalty", 1.0)
    return round(base * penalty, 1)

def build_reasons(r, score):
    ups, dns = [], []
    mom = r["factors"].get("mom_adj")
    if mom is not None:
        if mom > 20:   ups.append(f"Momentum ajustado muy fuerte (+{mom:.1f}%) — tendencia sólida")
        elif mom > 5:  ups.append(f"Momentum ajustado positivo (+{mom:.1f}%)")
        elif mom < -15:dns.append(f"Momentum negativo ({mom:.1f}%) — tendencia débil")
    trend = r["factors"].get("trend")
    if trend is not None:
        if trend > 15:   ups.append(f"Muy por encima de SMA200 (+{trend:.1f}%) — tendencia alcista fuerte")
        elif trend > 5:  ups.append(f"Por encima de SMA200 (+{trend:.1f}%) — tendencia positiva")
        elif trend < -5: dns.append(f"Por debajo de SMA200 ({trend:.1f}%) — tendencia bajista")
    sh = r["factors"].get("sharpe_impl")
    vol = r["factors"].get("vol")
    if sh is not None:
        if sh > 1.5:   ups.append(f"Excelente calidad de retorno (Sharpe impl. {sh:.2f})")
        elif sh > 0.8: ups.append(f"Buena relación retorno/riesgo (Sharpe impl. {sh:.2f})")
        elif sh < 0:
            if vol: dns.append(f"Retorno negativo con alta volatilidad ({vol:.0f}%)")
    rsi = r["factors"].get("rsi")
    dist = r["factors"].get("dist_sma50", 0)
    if rsi is not None:
        if rsi < 30:      ups.append(f"RSI en sobreventa ({rsi:.0f}) — posible rebote técnico")
        elif rsi < 45:    ups.append(f"RSI neutral-bajo ({rsi:.0f}) — zona de entrada favorable")
        elif 45<=rsi<=60: ups.append(f"RSI neutral ({rsi:.0f}) — momento de entrada equilibrado")
        elif rsi > 70:    dns.append(f"RSI en sobrecompra ({rsi:.0f}) — entrada tardía")
    if dist > 15:         dns.append(f"Precio muy estirado sobre SMA50 (+{dist:.0f}%) — riesgo de corrección")
    pe = r.get("pe")
    pe_norm = r["norm"].get("pe", 0.5)
    if pe:
        if pe_norm > 0.7:  ups.append(f"PER ({pe:.0f}x) bajo para su sector — valoración atractiva")
        elif pe_norm < 0.3:dns.append(f"PER ({pe:.0f}x) alto para su sector — valoración exigente")
    cons = r["factors"].get("consistency_6m")
    if cons is not None:
        if cons >= 80: ups.append(f"Tendencia muy consistente ({cons:.0f}% meses positivos en 6M)")
        elif cons <= 40: dns.append(f"Tendencia inconsistente ({cons:.0f}% meses positivos en 6M)")
    penalty = r["factors"].get("overext_penalty", 1.0)
    if penalty < 1.0:
        r6m = r["factors"].get("r6m")
        dns.append(f"Sobreextensión detectada (+{r6m:.0f}% en 6M) — score penalizado {int((1-penalty)*100)}%")
    dd = r["factors"].get("drawdown")
    if dd is not None and dd < -25:
        ups.append(f"Caída desde máximos del {dd:.0f}% — potencial de recuperación")
    rr = r["factors"].get("recovery_ratio")
    if rr is not None and rr > 1.5:
        ups.append(f"Excelente ratio recuperación ({rr:.1f}) — resiliente a las caídas")
    return ups[:4], dns[:3]

def build_top10_diversified(records):
    non_lev = [r for r in records if r.get("sector") not in LEVERAGED]
    sector_count = {}
    top10 = []
    for r in non_lev:
        s = r.get("sector","")
        if sector_count.get(s, 0) >= MAX_PER_SECTOR: continue
        top10.append(r)
        sector_count[s] = sector_count.get(s, 0) + 1
        if len(top10) >= 10: break
    return top10

def main():
    raw = open(UNI, encoding="utf-8").read()
    universe = json.loads(raw)["etfs"]
    print(f"Analizando {len(universe)} ETFs (modelo v3)...")
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
            "id": etf["id"], "name": etf["name"], "symbol": sym,
            "sector": etf["sector"], "last": round(prices[-1], 4),
            "factors": factors, "norm": {},
            "pe": fund.get("pe"), "beta": fund.get("beta"), "dy": fund.get("dy"),
            "sparkline":   [round(p,4) for p in prices[-60:]],
            "spark_dates": dates[-60:],
        }
        records.append(rec)
        print(f"ok")
    if not records:
        print("ERROR: sin datos"); return
    normalize_cross(records, "mom_adj")
    normalize_cross(records, "trend")
    normalize_cross(records, "sharpe_impl")
    normalize_cross(records, "entry")
    normalize_pe_within_sector(records)
    for r in records:
        r["score"] = compute_score(r)
        r["score_momentum"]   = round(r["norm"].get("mom_adj",0.5)*100, 0)
        r["score_tendencia"]  = round(r["norm"].get("trend",0.5)*100, 0)
        r["score_sharpe"]     = round(r["norm"].get("sharpe_impl",0.5)*100, 0)
        r["score_entrada"]    = round(r["norm"].get("entry",0.5)*100, 0)
        r["score_valoracion"] = round(r["norm"].get("pe",0.5)*100, 0)
        r["r1m"]  = r["factors"].get("r1m")
        r["r3m"]  = r["factors"].get("r3m")
        r["r6m"]  = r["factors"].get("r6m")
        r["r12m"] = r["factors"].get("r12m")
        r["vol"]  = r["factors"].get("vol")
        r["rsi"]  = r["factors"].get("rsi")
        r["drawdown"]        = r["factors"].get("drawdown")
        r["ann_ret"]         = r["factors"].get("ann_ret")
        r["consistency_6m"]  = r["factors"].get("consistency_6m")
        r["recovery_ratio"]  = r["factors"].get("recovery_ratio")
        r["overext_penalty"] = r["factors"].get("overext_penalty")
        for k in list(r.keys()):
            if k in ("factors","norm"): del r[k]
        ups, dns = build_reasons(r, r["score"])
        r["reasons_up"] = ups
        r["reasons_down"] = dns
    records.sort(key=lambda x: x["score"], reverse=True)
    top10 = build_top10_diversified(records)
    best_sector = {}
    for r in records:
        s = r["sector"]
        if s not in best_sector: best_sector[s] = r
    out = {
        "updated":        datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "total_analyzed": len(records),
        "model_version":  "3.0",
        "factor_weights": WEIGHTS,
        "top10":          top10,
        "all":            records,
        "best_by_sector": list(best_sector.values()),
        "warnings":       WARN,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\nOK. {len(records)} ETFs. Top 3 diversificado:")
    for r in top10[:3]:
        print(f"  {r['score']:5.1f} — {r['name'][:45]} ({r['symbol']}) [{r['sector']}]")
    print(f"Avisos: {len(WARN)}")

if __name__ == "__main__":
    main()
