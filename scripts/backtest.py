#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest historico del modelo v3.
Mismos cambios que scan.py v3:
- Limite 2 ETFs por sector en el Top10.
- Penalizacion por sobreextension.
- Apalancados excluidos del Top10.
"""

import json, math, os, re, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI  = os.path.join(ROOT, "universe.json")
OUT  = os.path.join(ROOT, "data", "backtest.json")
UA   = {"User-Agent": "Mozilla/5.0 (compatible; Backtest/2.0)"}

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

def fetch_history_2y(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2y&interval=1d"
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
    except:
        return None, None

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

def overextension_penalty(r6m):
    if r6m is None: return 1.0
    if r6m > 50: return 0.70
    if r6m > 30: return 0.85
    return 1.0

def compute_raw_factors(prices):
    if not prices or len(prices) < 60: return None
    r12 = ret_n(prices, min(252, len(prices)-1))
    r1  = ret_n(prices, 21)
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
        "r6m": r6m, "overext_penalty": overextension_penalty(r6m),
    }

def normalize_and_score(records):
    def norm(key):
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
    for key in ["mom_adj","trend","sharpe_impl","entry"]:
        norm(key)
    for r in records:
        base = (
            WEIGHTS["momentum_adj"] * r["norm"].get("mom_adj", 0.5) +
            WEIGHTS["tendencia"]    * r["norm"].get("trend",   0.5) +
            WEIGHTS["sharpe_impl"]  * r["norm"].get("sharpe_impl", 0.5) +
            WEIGHTS["entrada"]      * r["norm"].get("entry",   0.5) +
            WEIGHTS["valoracion"]   * 0.5
        ) * 100
        penalty = r["factors"].get("overext_penalty", 1.0)
        r["score"] = round(base * penalty, 1)

def build_top10_diversified(records):
    non_lev = [r for r in records if r.get("sector") not in LEVERAGED]
    sector_count = {}
    top10 = []
    for r in sorted(non_lev, key=lambda x: x["score"], reverse=True):
        s = r.get("sector","")
        if sector_count.get(s, 0) >= MAX_PER_SECTOR: continue
        top10.append(r)
        sector_count[s] = sector_count.get(s, 0) + 1
        if len(top10) >= 10: break
    return top10

def prices_up_to(all_prices, all_dates, target_date):
    cutoff = target_date.isoformat()
    for i, d in enumerate(all_dates):
        if d > cutoff: return all_prices[:i]
    return all_prices[:]

def future_return_at(all_prices, all_dates, from_date, n_days):
    from_str = from_date.isoformat()
    start_idx = None
    for i, d in enumerate(all_dates):
        if d >= from_str: start_idx = i; break
    if start_idx is None: return None
    end_idx = min(start_idx + n_days, len(all_prices) - 1)
    if end_idx <= start_idx: return None
    p0 = all_prices[start_idx]
    p1 = all_prices[end_idx]
    return round((p1/p0 - 1)*100, 2) if p0 > 0 else None

def price_at(all_prices, all_dates, target_date):
    cutoff = target_date.isoformat()
    last = None
    for d, p in zip(all_dates, all_prices):
        if d <= cutoff: last = p
        else: break
    return round(last, 4) if last else None

def main():
    raw = open(UNI, encoding="utf-8").read()
    universe = json.loads(raw)["etfs"]
    print(f"Descargando historico de {len(universe)} ETFs (modelo v3)...")
    etf_data = {}
    for etf in universe:
        sym = etf["symbol"]
        print(f"  {sym}...", end=" ", flush=True)
        prices, dates = fetch_history_2y(sym)
        if not prices or len(prices) < 120:
            print("sin datos"); continue
        etf_data[etf["id"]] = {
            "id": etf["id"], "name": etf["name"],
            "symbol": sym, "sector": etf["sector"],
            "prices": prices, "dates": dates,
        }
        print(f"{len(prices)} dias")

    if not etf_data:
        print("ERROR: sin datos"); return

    today = datetime.date.today()
    eval_dates = []
    d = today.replace(day=1)
    for _ in range(15):
        d = (d - datetime.timedelta(days=1)).replace(day=1)
        eval_dates.append(d)
    eval_dates = sorted(eval_dates)

    print(f"\nCalculando backtest para {len(eval_dates)} fechas (v3)...")
    snapshots = []

    for eval_date in eval_dates:
        print(f"\n  === {eval_date} ===")
        records = []
        for eid, edata in etf_data.items():
            prices_cut = prices_up_to(edata["prices"], edata["dates"], eval_date)
            if len(prices_cut) < 60: continue
            factors = compute_raw_factors(prices_cut)
            if factors is None: continue
            records.append({
                "id": eid, "name": edata["name"], "sector": edata["sector"],
                "symbol": edata["symbol"], "factors": factors, "norm": {},
                "price_at_signal": price_at(edata["prices"], edata["dates"], eval_date),
            })
        if len(records) < 10: continue
        normalize_and_score(records)
        records.sort(key=lambda x: x["score"], reverse=True)

        top10 = build_top10_diversified(records)
        bottom5 = records[-5:]

        top10_with_rets = []
        for r in top10:
            edata = etf_data[r["id"]]
            ret_1m = future_return_at(edata["prices"], edata["dates"], eval_date, 21)
            ret_3m = future_return_at(edata["prices"], edata["dates"], eval_date, 63)
            ret_6m = future_return_at(edata["prices"], edata["dates"], eval_date, 126)
            acerto_3m = None if ret_3m is None else ret_3m > 0
            top10_with_rets.append({
                "id": r["id"], "name": r["name"], "symbol": r["symbol"],
                "sector": r["sector"], "score": r["score"],
                "price_signal": r["price_at_signal"],
                "ret_1m": ret_1m, "ret_3m": ret_3m, "ret_6m": ret_6m,
                "acerto_3m": acerto_3m,
            })
            status = "✓" if acerto_3m else ("✗" if acerto_3m is False else "?")
            print(f"    {r['symbol']:10s} [{r['sector'][:12]:12s}] score={r['score']:5.1f} ret3M={str(ret_3m)+'%' if ret_3m else '?':8s} {status}")

        bot5_with_rets = []
        for r in bottom5:
            edata = etf_data[r["id"]]
            ret_3m = future_return_at(edata["prices"], edata["dates"], eval_date, 63)
            bot5_with_rets.append({"id":r["id"],"name":r["name"],"score":r["score"],"ret_3m":ret_3m})

        top_rets = [e["ret_3m"] for e in top10_with_rets if e["ret_3m"] is not None]
        bot_rets = [e["ret_3m"] for e in bot5_with_rets if e["ret_3m"] is not None]
        avg_top = round(sum(top_rets)/len(top_rets), 2) if top_rets else None
        avg_bot = round(sum(bot_rets)/len(bot_rets), 2) if bot_rets else None
        spread  = round(avg_top - avg_bot, 2) if avg_top is not None and avg_bot is not None else None
        aciertos = sum(1 for e in top10_with_rets if e["acerto_3m"] is True)
        total_con_dato = sum(1 for e in top10_with_rets if e["acerto_3m"] is not None)
        sectores_top10 = list(set(e["sector"] for e in top10_with_rets))

        snapshots.append({
            "date": eval_date.isoformat(), "n_etfs": len(records),
            "top10": top10_with_rets, "bottom5": bot5_with_rets,
            "avg_top_3m": avg_top, "avg_bot_3m": avg_bot, "spread_3m": spread,
            "aciertos": aciertos, "total_con_dato": total_con_dato,
            "tasa_acierto": round(aciertos/total_con_dato*100, 0) if total_con_dato else None,
            "sectores_top10": sectores_top10,
            "n_sectores": len(sectores_top10),
        })

    spreads = [s["spread_3m"] for s in snapshots if s["spread_3m"] is not None]
    tasas   = [s["tasa_acierto"] for s in snapshots if s["tasa_acierto"] is not None]
    mean_spread = round(sum(spreads)/len(spreads), 2) if spreads else None
    mean_tasa   = round(sum(tasas)/len(tasas), 1) if tasas else None
    pos_spreads = sum(1 for s in spreads if s > 0)
    avg_sectores = round(sum(s["n_sectores"] for s in snapshots)/len(snapshots), 1) if snapshots else None

    summary = {
        "n_fechas": len(snapshots),
        "spread_medio_3m": mean_spread,
        "tasa_acierto_media": mean_tasa,
        "meses_positivos": pos_spreads,
        "meses_total": len(spreads),
        "avg_sectores_top10": avg_sectores,
        "interpretacion": (
            f"En {pos_spreads} de {len(spreads)} meses el Top10 superó al Bottom5. "
            f"Tasa de acierto media: {mean_tasa}%. "
            f"Media de {avg_sectores} sectores distintos en el Top10. "
            + ("El modelo muestra poder predictivo." if (mean_tasa or 0) > 55
               else "El modelo no muestra ventaja clara sobre el azar.")
        )
    }

    out = {
        "updated":  datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "model_version": "3.0",
        "summary":  summary,
        "snapshots": snapshots,
        "metodologia": "Scores calculados sin datos futuros. Top10 diversificado: max 2 ETFs por sector, sin apalancados. Penalizacion por sobreextension.",
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print(f"\n{'='*55}")
    print(f"BACKTEST v3 — MODELO DIVERSIFICADO LARGO PLAZO")
    print(f"  Fechas:           {len(snapshots)}")
    print(f"  Spread medio 3M:  {mean_spread}%  (v2 era -1.57%)")
    print(f"  Tasa acierto:     {mean_tasa}%   (v2 era 71.3%)")
    print(f"  Meses positivos:  {pos_spreads}/{len(spreads)}")
    print(f"  Sectores Top10:   {avg_sectores} de media")
    print(f"{'='*55}")

if __name__ == "__main__":
    main()
