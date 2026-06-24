#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro.py v2 — Datos macro ampliados.

Variables FRED:
  FEDFUNDS     — tipo de interes fed funds
  DGS10        — bono tesoro 10 anos
  DGS2         — bono tesoro 2 anos
  BAMLH0A0HYM2 — spread credito high yield (NUEVO)
  UMCSENT      — confianza consumidor Michigan (NUEVO)

Variables Yahoo:
  VIX, DXY, INR=X, UX=F, IWDA.AS
"""

import json, os, urllib.request, datetime, math

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT   = os.path.join(ROOT, "data", "macro.json")
UA    = {"User-Agent": "Mozilla/5.0 (compatible; MacroFetcher/2.0)"}
FRED  = os.environ.get("FRED_API_KEY", "")

def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fred(series, limit=12):
    if not FRED: return None
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series}&api_key={FRED}&file_type=json&sort_order=desc&limit={limit}"
    try:
        d = _get(url)
        obs = [o for o in d.get("observations",[]) if o.get("value") != "."]
        if not obs: return None
        return float(obs[0]["value"]), [float(o["value"]) for o in obs]
    except: return None

def yahoo_prices(symbol, rng="1y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d"
    try:
        d = _get(url); res = d["chart"]["result"][0]
        ts  = res.get("timestamp") or []
        cls = (res.get("indicators") or {}).get("quote",[{}])[0].get("close") or []
        pairs = {}
        for t,c in zip(ts,cls):
            if c is None: continue
            pairs[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")] = float(c)
        series = sorted(pairs.items())
        return [p for _,p in series], [d for d,_ in series]
    except: return None, None

def trend(values, n=3):
    if not values or len(values) < n: return "neutral"
    recent = values[:n]
    if all(recent[i] >= recent[i+1] for i in range(n-1)): return "up"
    if all(recent[i] <= recent[i+1] for i in range(n-1)): return "down"
    return "neutral"

def main():
    print("Descargando datos macro v2...")
    macro = {"updated": datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z",
             "fred_available": bool(FRED)}

    # ── TIPOS DE INTERES ──────────────────────────────────────────────
    fed   = fred("FEDFUNDS", 6)
    dgs10 = fred("DGS10", 6)
    dgs2  = fred("DGS2", 6)
    fed_val   = fed[0]   if fed   else None
    dgs10_val = dgs10[0] if dgs10 else None
    dgs2_val  = dgs2[0]  if dgs2  else None
    ycs = round(dgs10_val - dgs2_val, 2) if dgs10_val and dgs2_val else None
    yci = ycs < 0 if ycs is not None else False
    if fed_val is not None:
        if fed_val > 4.5:   rs = 25; interp = f"Tipos muy altos ({fed_val:.2f}%) — freno al crecimiento"
        elif fed_val > 3.0: rs = 45; interp = f"Tipos elevados ({fed_val:.2f}%) — presión moderada"
        elif fed_val > 1.5: rs = 65; interp = f"Tipos moderados ({fed_val:.2f}%) — entorno neutro"
        else:               rs = 80; interp = f"Tipos bajos ({fed_val:.2f}%) — favorable al crecimiento"
    else:
        rs = 50; interp = "Sin datos de tipos"
    macro["interest_rates"] = {
        "fed_funds": fed_val, "dgs10": dgs10_val, "dgs2": dgs2_val,
        "yield_curve_spread": ycs, "yield_curve_inverted": yci,
        "score": rs, "interpretation": interp,
        "yield_curve_note": ("⚠️ Curva invertida — señal histórica de recesión 12-18M" if yci
                             else "Curva normal" if ycs is not None else "Sin datos curva")
    }
    print(f"  Tipos: Fed={fed_val}% | 10Y={dgs10_val}% | 2Y={dgs2_val}% | Curva={ycs}% {'⚠️ INVERTIDA' if yci else ''}")

    # ── SPREAD CREDITO HIGH YIELD (NUEVO) ─────────────────────────────
    hy = fred("BAMLH0A0HYM2", 12)
    if hy:
        hy_val = hy[0]; hy_hist = hy[1]
        hy_trend = trend(hy_hist, 3)
        if hy_val > 7:    hy_score = 20; hy_interp = f"Spread HY muy alto ({hy_val:.1f}%) — pánico crediticio"
        elif hy_val > 5:  hy_score = 35; hy_interp = f"Spread HY elevado ({hy_val:.1f}%) — estrés crediticio"
        elif hy_val > 4:  hy_score = 50; hy_interp = f"Spread HY moderado ({hy_val:.1f}%) — cautela en crédito"
        elif hy_val > 3:  hy_score = 65; hy_interp = f"Spread HY normal ({hy_val:.1f}%) — condiciones sanas"
        else:             hy_score = 80; hy_interp = f"Spread HY comprimido ({hy_val:.1f}%) — condiciones favorables"
        if hy_trend == "up":    hy_score = max(0,   hy_score-10); hy_interp += " — tendencia a empeorar"
        elif hy_trend == "down": hy_score = min(100, hy_score+10); hy_interp += " — tendencia a mejorar"
        macro["credit_spread"] = {"value": hy_val, "trend": hy_trend,
                                   "score": hy_score, "interpretation": hy_interp}
        print(f"  HY Spread: {hy_val:.2f}% ({hy_trend}) — score {hy_score}")
    else:
        macro["credit_spread"] = {"value": None, "score": 50, "interpretation": "Sin datos"}
        print("  HY Spread: sin datos FRED")

    # ── CONFIANZA CONSUMIDOR MICHIGAN (NUEVO) ─────────────────────────
    umcs = fred("UMCSENT", 6)
    if umcs:
        um_val = umcs[0]; um_hist = umcs[1]
        um_trend = trend(um_hist, 3)
        if um_val > 90:   um_score = 80; um_interp = f"Confianza consumidor alta ({um_val:.0f}) — demanda fuerte"
        elif um_val > 80: um_score = 65; um_interp = f"Confianza consumidor moderada ({um_val:.0f})"
        elif um_val > 70: um_score = 50; um_interp = f"Confianza consumidor neutral ({um_val:.0f})"
        elif um_val > 60: um_score = 35; um_interp = f"Confianza consumidor débil ({um_val:.0f})"
        else:             um_score = 20; um_interp = f"Confianza consumidor muy baja ({um_val:.0f}) — recesión probable"
        macro["consumer_confidence"] = {"value": um_val, "trend": um_trend,
                                         "score": um_score, "interpretation": um_interp}
        print(f"  Confianza consumidor: {um_val:.0f} ({um_trend}) — score {um_score}")
    else:
        macro["consumer_confidence"] = {"value": None, "score": 50, "interpretation": "Sin datos"}
        print("  Confianza consumidor: sin datos FRED")

    # ── VIX ───────────────────────────────────────────────────────────
    vix_p, _ = yahoo_prices("^VIX", "6mo")
    if vix_p and len(vix_p) >= 5:
        vix_val = vix_p[-1]; vix_5d = vix_p[-5]
        vix_trend = "down" if vix_val < vix_5d*0.95 else "up" if vix_val > vix_5d*1.05 else "neutral"
        if vix_val > 35:   vs = 15; vi = f"VIX {vix_val:.1f} — pánico extremo (oportunidad histórica)"
        elif vix_val > 25: vs = 30; vi = f"VIX {vix_val:.1f} — miedo elevado (bear market)"
        elif vix_val > 20: vs = 50; vi = f"VIX {vix_val:.1f} — volatilidad moderada"
        elif vix_val > 15: vs = 70; vi = f"VIX {vix_val:.1f} — mercado tranquilo"
        else:              vs = 85; vi = f"VIX {vix_val:.1f} — complacencia (cautela)"
        macro["vix"] = {"value": round(vix_val,1), "trend": vix_trend, "score": vs, "interpretation": vi}
        print(f"  VIX: {vix_val:.1f} ({vix_trend})")
    else:
        macro["vix"] = {"value": None, "score": 50, "interpretation": "Sin datos"}

    # ── DXY ───────────────────────────────────────────────────────────
    dxy_p, _ = yahoo_prices("DX-Y.NYB", "1y")
    if dxy_p and len(dxy_p) >= 126:
        dxy_now = dxy_p[-1]; dxy_ret = (dxy_now/dxy_p[-126]-1)*100
        if dxy_ret > 5:    ds = 25; di = f"Dólar fuerte (+{dxy_ret:.1f}% 6M) — presión a emergentes"
        elif dxy_ret > 2:  ds = 40; di = f"Dólar algo fuerte (+{dxy_ret:.1f}% 6M)"
        elif dxy_ret > -2: ds = 60; di = f"Dólar estable ({dxy_ret:.1f}% 6M)"
        elif dxy_ret > -5: ds = 75; di = f"Dólar algo débil ({dxy_ret:.1f}% 6M)"
        else:              ds = 85; di = f"Dólar débil ({dxy_ret:.1f}% 6M) — favorable a commodities"
        macro["dxy"] = {"value": round(dxy_now,2), "ret_6m": round(dxy_ret,1),
                        "score": ds, "score_inverse": 100-ds, "interpretation": di}
        print(f"  DXY: {dxy_now:.1f} ({dxy_ret:+.1f}% 6M)")
    else:
        macro["dxy"] = {"value": None, "score": 50, "score_inverse": 50, "interpretation": "Sin datos"}

    # ── RUPIA INDIA ───────────────────────────────────────────────────
    inr_p, _ = yahoo_prices("INR=X", "6mo")
    if inr_p and len(inr_p) >= 63:
        inr_ret = (inr_p[-1]/inr_p[-63]-1)*100
        inr_trend = "down" if inr_ret > 2 else "up" if inr_ret < -2 else "stable"
        macro["inr"] = {"value": round(inr_p[-1],2), "ret_3m": round(inr_ret,1), "trend": inr_trend,
                        "interpretation": f"Rupia {'depreciándose' if inr_trend=='down' else 'apreciándose' if inr_trend=='up' else 'estable'} ({inr_ret:+.1f}% 3M)"}
        print(f"  INR: {inr_p[-1]:.2f} ({inr_trend})")
    else:
        macro["inr"] = {"value": None, "trend": "stable"}

    # ── URANIO SPOT ───────────────────────────────────────────────────
    ux_p, _ = yahoo_prices("UX=F", "1y")
    if ux_p and len(ux_p) >= 126:
        ux_now = ux_p[-1]; ux_ret = (ux_now/ux_p[-126]-1)*100
        if ux_ret > 30:    uxs = 90; uxi = f"Uranio spot muy fuerte (+{ux_ret:.0f}% 6M)"
        elif ux_ret > 10:  uxs = 75; uxi = f"Uranio spot fuerte (+{ux_ret:.0f}% 6M)"
        elif ux_ret > -5:  uxs = 55; uxi = f"Uranio spot estable ({ux_ret:.0f}% 6M)"
        elif ux_ret > -20: uxs = 35; uxi = f"Uranio spot débil ({ux_ret:.0f}% 6M)"
        else:              uxs = 20; uxi = f"Uranio spot muy débil ({ux_ret:.0f}% 6M)"
        macro["uranium_spot"] = {"value": round(ux_now,1), "ret_6m": round(ux_ret,1),
                                  "score": uxs, "interpretation": uxi}
        print(f"  Uranio: ${ux_now:.1f} ({ux_ret:+.1f}% 6M)")
    else:
        macro["uranium_spot"] = {"value": None, "score": 50, "interpretation": "Sin datos"}

    # ── IWDA ─────────────────────────────────────────────────────────
    iw_p, _ = yahoo_prices("IWDA.AS", "1y")
    if iw_p and len(iw_p) >= 126:
        iw_ret6 = round((iw_p[-1]/iw_p[-126]-1)*100, 2)
        iw_ret1 = round((iw_p[-1]/iw_p[-21]-1)*100, 2) if len(iw_p) >= 21 else None
        e200 = sum(iw_p[-200:])/200 if len(iw_p) >= 200 else None
        macro["iwda"] = {"price": round(iw_p[-1],2), "ret_6m": iw_ret6, "ret_1m": iw_ret1,
                         "ema200": round(e200,2) if e200 else None,
                         "above_ema200": iw_p[-1] > e200 if e200 else None}
        print(f"  IWDA: {iw_p[-1]:.2f} ({iw_ret6:+.1f}% 6M)")
    else:
        macro["iwda"] = {"price": None, "ret_6m": None}

    # ── BITCOIN HALVING ───────────────────────────────────────────────
    halving_date = datetime.date(2024, 4, 19)
    months_since = (datetime.date.today() - halving_date).days / 30.44
    if months_since <= 6:    hs = 85; hd = f"Halving hace {months_since:.0f}M — euforia temprana"
    elif months_since <= 12: hs = 75; hd = f"Halving hace {months_since:.0f}M — bull market típico"
    elif months_since <= 18: hs = 65; hd = f"Halving hace {months_since:.0f}M — fase madura"
    elif months_since <= 30: hs = 50; hd = f"Halving hace {months_since:.0f}M — ciclo medio"
    else:                    hs = 40; hd = f"Halving hace {months_since:.0f}M — fin de ciclo"
    macro["bitcoin_halving"] = {"halving_date": halving_date.isoformat(),
                                 "months_since": round(months_since,1),
                                 "halving_score": hs, "description": hd}
    print(f"  Bitcoin halving: {months_since:.0f}M — score {hs}")

    # ── COMPOSITE SCORE ───────────────────────────────────────────────
    scores = [v for k in ["interest_rates","credit_spread","vix","consumer_confidence"]
              if (v := macro.get(k,{}).get("score"))]
    if scores:
        composite = round(sum(scores)/len(scores), 1)
        if composite > 70:   ci = "Entorno macro favorable"
        elif composite > 50: ci = "Entorno macro neutro"
        elif composite > 30: ci = "Entorno macro deteriorado"
        else:                ci = "Entorno macro muy negativo — cautela máxima"
        macro["composite_score"] = {"score": composite, "interpretation": ci}
        print(f"  Composite: {composite} — {ci}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(macro, f, ensure_ascii=False, indent=2)
    print(f"\nmacro.json guardado — {len(macro)} variables")

if __name__ == "__main__":
    main()
