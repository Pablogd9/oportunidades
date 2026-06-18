#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest historico del modelo v5.
Mismos criterios que scan.py v5:
- EMA200 en vez de SMA200.
- Penalizacion momentum fuerte (x0.5 si cae >10% en 3M).
- Umbral minimo score 55.
- Max 1 ETF por sector en Top3.
- Sin apalancados.
"""

import json, math, os, re, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI  = os.path.join(ROOT, "universe.json")
OUT  = os.path.join(ROOT, "data", "backtest.json")
UA   = {"User-Agent": "Mozilla/5.0 (compatible; Backtest/3.0)"}

WEIGHTS = {
    "secular":    0.30,
    "ema200":     0.25,
    "momentum3m": 0.20,
    "quality":    0.15,
    "entry":      0.10,
}

LEVERAGED      = {"Apalancado"}
MAX_PER_SECTOR = 1
MIN_SCORE      = 55

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

def ema_n(prices, n):
    if len(prices) < n: return None
    k = 2.0 / (n + 1)
    ema = sum(prices[:n]) / n
    for p in prices[n:]:
        ema = p * k + ema * (1 - k)
    return ema

def ret_n(prices, n):
    if len(prices) < n + 1: return None
    p0, p1 = prices[-(n+1)], prices[-1]
    return (p1 / p0 - 1) * 100 if p0 > 0 else None

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

def secular_return(prices):
    if len(prices) < 60: return None
    return round((prices[-1]/prices[0] - 1)*100, 1)

def consistency_12m(prices):
    if len(prices) < 270: return None
    monthly_rets = []
    for i in range(12):
        start = -(21*(i+1)+1)
        end   = -(21*i+1) if i > 0 else -1
        if abs(start) >= len(prices): continue
        p0 = prices[start]
        p1 = prices[end]
        if p0 > 0: monthly_rets.append(p1/p0 - 1)
    if len(monthly_rets) < 6: return None
    positive = sum(1 for r in monthly_rets if r > 0)
    return round(positive / len(monthly_rets) * 100, 0)

def distance_from_max_1y(prices):
    if len(prices) < 50: return None
    window = prices[-min(252, len(prices)):]
    peak = max(window)
    return round((prices[-1]/peak - 1)*100, 2) if peak > 0 else None

def compute_raw_factors(prices):
    if not prices or len(prices) < 60: return None
    secular  = secular_return(prices)
    quality  = consistency_12m(prices)
    dist_max = distance_from_max_1y(prices)
    entry_raw = min(100, max(0, -dist_max * 2)) if dist_max is not None else None
    mom3m    = ret_n(prices, 63)
    e200 = ema_n(prices, 200) or ema_n(prices, 100) or ema_n(prices, 60)
    dist_ema200 = ((prices[-1]/e200 - 1)*100) if e200 else None
    mom_penalty = 0.5 if (mom3m is not None and mom3m < -10) else 1.0
    return {
        "secular":     secular,
        "dist_ema200": dist_ema200,
        "mom3m":       mom3m,
        "quality":     quality,
        "entry_raw":   entry_raw,
        "mom_penalty": mom_penalty,
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
    for key in ["secular","dist_ema200","mom3m","quality","entry_raw"]:
        norm(key)
    for r in records:
        base = (
            WEIGHTS["secular"]    * r["norm"].get("secular",     0.5) +
            WEIGHTS["ema200"]     * r["norm"].get("dist_ema200", 0.5) +
            WEIGHTS["momentum3m"] * r["norm"].get("mom3m",       0.5) +
            WEIGHTS["quality"]    * r["norm"].get("quality",     0.5) +
            WEIGHTS["entry"]      * r["norm"].get("entry_raw",   0.5)
        ) * 100
        penalty = r["factors"].get("mom_penalty", 1.0)
        r["score"] = round(base * penalty, 1)

def build_top3_diversified(records):
    non_lev = [r for r in records if r.get("sector") not in LEVERAGED]
    sector_used = set()
    top3 = []
    for r in sorted(non_lev, key=lambda x: x["score"], reverse=True):
        if r["score"] < MIN_SCORE: break
        s = r.get("sector","")
        if s in sector_used: continue
        top3.append(r)
        sector_used.add(s)
        if len(top3) >= 3: break
    return top3

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
    raw = re.sub(r'//[^\n]*', '', raw)
    universe = json.loads(raw)["etfs"]
    print(f"Descargando historico de {len(universe)} ETFs (modelo v5)...")
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

    print(f"\nCalculando backtest para {len(eval_dates)} fechas (v5)...")
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

        top3   = build_top3_diversified(records)
        bottom5 = records[-5:]

        top3_with_rets = []
        for r in top3:
            edata = etf_data[r["id"]]
            ret_1m = future_return_at(edata["prices"], edata["dates"], eval_date, 21)
            ret_3m = future_return_at(edata["prices"], edata["dates"], eval_date, 63)
            ret_6m = future_return_at(edata["prices"], edata["dates"], eval_date, 126)
            acerto_3m = None if ret_3m is None else ret_3m > 0
            top3_with_rets.append({
                "id": r["id"], "name": r["name"], "symbol": r["symbol"],
                "sector": r["sector"], "score": r["score"],
                "price_signal": r["price_at_signal"],
                "ret_1m": ret_1m, "ret_3m": ret_3m, "ret_6m": ret_6m,
                "acerto_3m": acerto_3m,
                "penalizado": r["factors"].get("mom_penalty", 1.0) < 1.0,
            })
            status = "✓" if acerto_3m else ("✗" if acerto_3m is False else "?")
            pen    = " [PENALIZADO]" if r["factors"].get("mom_penalty",1)<1 else ""
            print(f"    {r['symbol']:10s} [{r['sector'][:12]:12s}] score={r['score']:5.1f} ret3M={str(ret_3m)+'%' if ret_3m else '?':8s} {status}{pen}")

        if not top3_with_rets:
            print(f"    Sin ETFs con score >= {MIN_SCORE} este mes")

        bot5_with_rets = []
        for r in bottom5:
            edata = etf_data[r["id"]]
            ret_3m = future_return_at(edata["prices"], edata["dates"], eval_date, 63)
            bot5_with_rets.append({"id":r["id"],"name":r["name"],"score":r["score"],"ret_3m":ret_3m})

        top_rets = [e["ret_3m"] for e in top3_with_rets if e["ret_3m"] is not None]
        bot_rets = [e["ret_3m"] for e in bot5_with_rets if e["ret_3m"] is not None]
        avg_top  = round(sum(top_rets)/len(top_rets), 2) if top_rets else None
        avg_bot  = round(sum(bot_rets)/len(bot_rets), 2) if bot_rets else None
        spread   = round(avg_top - avg_bot, 2) if avg_top is not None and avg_bot is not None else None
        aciertos = sum(1 for e in top3_with_rets if e["acerto_3m"] is True)
        total_con_dato = sum(1 for e in top3_with_rets if e["acerto_3m"] is not None)
        sectores = list(set(e["sector"] for e in top3_with_rets))

        snapshots.append({
            "date": eval_date.isoformat(),
            "n_etfs": len(records),
            "hay_señal": len(top3_with_rets) > 0,
            "top10": top3_with_rets,
            "bottom5": bot5_with_rets,
            "avg_top_3m": avg_top,
            "avg_bot_3m": avg_bot,
            "spread_3m":  spread,
            "aciertos":   aciertos,
            "total_con_dato": total_con_dato,
            "tasa_acierto": round(aciertos/total_con_dato*100, 0) if total_con_dato else None,
            "sectores_top3": sectores,
            "n_sectores": len(sectores),
        })

    spreads = [s["spread_3m"] for s in snapshots if s["spread_3m"] is not None]
    tasas   = [s["tasa_acierto"] for s in snapshots if s["tasa_acierto"] is not None]
    meses_sin_señal = sum(1 for s in snapshots if not s["hay_señal"])
    mean_spread = round(sum(spreads)/len(spreads), 2) if spreads else None
    mean_tasa   = round(sum(tasas)/len(tasas), 1) if tasas else None
    pos_spreads = sum(1 for s in spreads if s > 0)

    summary = {
        "n_fechas":           len(snapshots),
        "spread_medio_3m":    mean_spread,
        "tasa_acierto_media": mean_tasa,
        "meses_positivos":    pos_spreads,
        "meses_total":        len(spreads),
        "meses_sin_señal":    meses_sin_señal,
        "interpretacion": (
            f"En {pos_spreads} de {len(spreads)} meses el Top3 superó al Bottom5. "
            f"Tasa de acierto media: {mean_tasa}%. "
            f"Meses sin señal (score<55): {meses_sin_señal}. "
            + ("El modelo muestra poder predictivo." if (mean_tasa or 0) > 55
               else "El modelo no muestra ventaja clara sobre el azar.")
        )
    }

    out = {
        "updated":       datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "model_version": "5.0",
        "summary":       summary,
        "snapshots":     snapshots,
        "metodologia":   "Modelo v5: EMA200, penalizacion momentum x0.5 si cae >10% en 3M, umbral minimo 55, max 1 ETF por sector, sin apalancados.",
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print(f"\n{'='*55}")
    print(f"BACKTEST v5")
    print(f"  Fechas:            {len(snapshots)}")
    print(f"  Spread medio 3M:   {mean_spread}%")
    print(f"  Tasa acierto:      {mean_tasa}%")
    print(f"  Meses positivos:   {pos_spreads}/{len(spreads)}")
    print(f"  Meses sin señal:   {meses_sin_señal}")
    print(f"{'='*55}")

if __name__ == "__main__":
    main()
