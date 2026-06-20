#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de datos macro externos.
Descarga VIX, DXY, uranio spot, rupia, IWDA, tipos (FRED o TLT proxy)
y ciclo halving Bitcoin. Guarda en data/macro.json.
"""

import json, math, os, urllib.request, datetime, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(ROOT, "data", "macro.json")
UA   = {"User-Agent": "Mozilla/5.0 (compatible; MacroFetcher/1.0)"}
FRED_KEY = os.environ.get("FRED_API_KEY", "")
BITCOIN_HALVING_DATE = datetime.date(2024, 4, 19)

def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_yahoo_series(symbol, rng="6mo"):
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
        print(f"  Warning {symbol}: {e}")
        return None, None

def fetch_fred_series(series_id):
    if not FRED_KEY: return None, None
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_KEY}&file_type=json&limit=90&sort_order=desc"
    try:
        d = _get(url)
        obs = d.get("observations", [])
        pairs = {}
        for o in obs:
            if o["value"] == ".": continue
            pairs[o["date"]] = float(o["value"])
        series = sorted(pairs.items())
        return [v for _, v in series], [d for d, _ in series]
    except Exception as e:
        print(f"  Warning FRED {series_id}: {e}")
        return None, None

def calc_trend(prices, n=63):
    if not prices or len(prices) < n: n = len(prices) if prices else 0
    if n < 2: return "neutral"
    change = (prices[-1] / prices[-n] - 1) * 100
    if change > 2:  return "up"
    if change < -2: return "down"
    return "neutral"

def calc_percentile(value, series):
    if not series or value is None: return 50
    below = sum(1 for v in series if v <= value)
    return round(below / len(series) * 100, 0)

def bitcoin_halving_phase():
    today = datetime.date.today()
    days_since = (today - BITCOIN_HALVING_DATE).days
    months_since = days_since / 30.44
    if months_since <= 18:
        phase = "post_halving_bullish"
        score = min(100, 100 - months_since * 2)
        desc  = f"Fase post-halving ({months_since:.0f}M) — históricamente alcista"
    elif months_since <= 30:
        phase = "mid_cycle"; score = 60
        desc  = f"Ciclo medio ({months_since:.0f}M) — momentum moderado"
    elif months_since <= 42:
        phase = "pre_halving_late"; score = 40
        desc  = f"Pre-halving tardío ({months_since:.0f}M) — acumulación"
    else:
        phase = "pre_halving_early"; score = 50
        desc  = f"Inicio ciclo ({months_since:.0f}M) — neutral"
    return {
        "phase": phase,
        "days_since_halving": days_since,
        "months_since_halving": round(months_since, 1),
        "halving_score": round(score, 0),
        "description": desc,
        "next_halving_approx": "2028-04",
    }

def main():
    print("Descargando datos macro externos...")
    macro = {
        "updated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "fred_available": bool(FRED_KEY),
    }

    print("  VIX...", end=" ")
    vix_prices, _ = fetch_yahoo_series("^VIX", "6mo")
    if vix_prices:
        vix_now = vix_prices[-1]
        vix_trend = calc_trend(vix_prices, 21)
        vix_pct = calc_percentile(vix_now, vix_prices)
        vix_score = round(100 - vix_pct, 0)
        oportunidad = vix_now > 30 and vix_trend == "down"
        macro["vix"] = {
            "value": round(vix_now, 2), "trend": vix_trend,
            "pct_6m": vix_pct, "score": vix_score,
            "oportunidad_entrada": oportunidad,
            "interpretation": (
                "Pánico extremo — oportunidad histórica de entrada" if oportunidad
                else "Bajo — mercado complaciente" if vix_now < 15
                else "Normal — entorno neutral" if vix_now < 25
                else "Elevado — cautela" if vix_now < 35
                else "Muy alto — mercado en pánico"
            )
        }
        print(f"VIX={vix_now:.1f} ({vix_trend})")
    else:
        macro["vix"] = {"value": None, "score": 50}
        print("sin datos")
    time.sleep(0.5)

    print("  DXY...", end=" ")
    dxy_prices, _ = fetch_yahoo_series("DX-Y.NYB", "6mo")
    if dxy_prices:
        dxy_now = dxy_prices[-1]
        dxy_trend = calc_trend(dxy_prices, 63)
        dxy_pct = calc_percentile(dxy_now, dxy_prices)
        macro["dxy"] = {
            "value": round(dxy_now, 2), "trend": dxy_trend,
            "pct_6m": dxy_pct, "score_inverse": round(100 - dxy_pct, 0),
            "interpretation": (
                "Dólar débil — favorable para India, Bitcoin, materias primas" if dxy_trend == "down"
                else "Dólar fuerte — presión sobre emergentes y cripto" if dxy_trend == "up"
                else "Dólar estable — impacto neutro"
            )
        }
        print(f"DXY={dxy_now:.1f} ({dxy_trend})")
    else:
        macro["dxy"] = {"value": None, "score_inverse": 50}
        print("sin datos")
    time.sleep(0.5)

    print("  INR/USD...", end=" ")
    inr_prices, _ = fetch_yahoo_series("INR=X", "6mo")
    if inr_prices:
        inr_now = inr_prices[-1]
        inr_trend = calc_trend(inr_prices, 63)
        macro["inr"] = {
            "value": round(inr_now, 4), "trend": inr_trend,
            "pct_6m": calc_percentile(inr_now, inr_prices),
            "interpretation": (
                "Rupia estable/apreciándose — favorable para India ETFs"
                if inr_trend in ["up", "neutral"]
                else "Rupia depreciándose — presión sobre retornos India"
            )
        }
        print(f"INR={inr_now:.2f} ({inr_trend})")
    else:
        macro["inr"] = {"value": None}
        print("sin datos")
    time.sleep(0.5)

    print("  Uranio spot...", end=" ")
    ux_prices, _ = fetch_yahoo_series("UX=F", "6mo")
    if ux_prices:
        ux_now = ux_prices[-1]
        ux_trend = calc_trend(ux_prices, 63)
        ux_pct = calc_percentile(ux_now, ux_prices)
        macro["uranium_spot"] = {
            "value": round(ux_now, 2), "trend": ux_trend,
            "pct_6m": ux_pct, "score": round(ux_pct, 0),
            "interpretation": (
                "Precio spot alto y subiendo — muy favorable para mineras" if ux_trend == "up" and ux_pct > 60
                else "Precio spot bajando — presión sobre mineras" if ux_trend == "down"
                else "Precio spot estable"
            )
        }
        print(f"UX={ux_now:.1f} ({ux_trend})")
    else:
        macro["uranium_spot"] = {"value": None, "score": 50}
        print("sin datos")
    time.sleep(0.5)

    print("  IWDA benchmark...", end=" ")
    iwda_prices, iwda_dates = fetch_yahoo_series("IWDA.AS", "2y")
    if iwda_prices:
        def rn(p, n): return round((p[-1]/p[-(n+1)]-1)*100,2) if len(p)>n else None
        macro["iwda"] = {
            "price": round(iwda_prices[-1], 4),
            "ret_1m": rn(iwda_prices,21), "ret_3m": rn(iwda_prices,63),
            "ret_6m": rn(iwda_prices,126), "ret_1y": rn(iwda_prices,252),
            "prices_6m": [round(p,4) for p in iwda_prices[-126:]],
            "dates_6m": iwda_dates[-126:] if iwda_dates else [],
        }
        print(f"IWDA={iwda_prices[-1]:.2f}")
    else:
        macro["iwda"] = {"price": None}
        print("sin datos")
    time.sleep(0.5)

    if FRED_KEY:
        print("  FRED tipos...", end=" ")
        ff_prices, _ = fetch_fred_series("FEDFUNDS")
        t10_prices, _ = fetch_fred_series("DGS10")
        t2_prices, _  = fetch_fred_series("DGS2")
        rates_now   = ff_prices[-1] if ff_prices else None
        rates_trend = calc_trend(ff_prices, 3) if ff_prices else "neutral"
        curve = round(t10_prices[-1]-t2_prices[-1],2) if t10_prices and t2_prices else None
        rates_pct = calc_percentile(rates_now, ff_prices) if ff_prices and rates_now else 50
        rates_score = round(100 - rates_pct, 0)
        macro["interest_rates"] = {
            "fed_funds": round(rates_now,2) if rates_now else None,
            "trend": rates_trend, "pct_2y": rates_pct, "score": rates_score,
            "yield_curve": curve,
            "curve_status": ("Invertida" if curve and curve<0 else "Normal" if curve and curve>0.5 else "Plana"),
            "interpretation": (
                "Tipos bajos y bajando — muy favorable para crecimiento" if rates_score>70 and rates_trend=="down"
                else "Tipos bajos — favorable" if rates_score>70
                else "Tipos altos y subiendo — presión sobre crecimiento" if rates_score<30 and rates_trend=="up"
                else "Tipos altos — cautela para sectores de crecimiento" if rates_score<30
                else "Tipos moderados — impacto neutro"
            )
        }
        print(f"FF={rates_now:.2f}% ({rates_trend})")
    else:
        print("  FRED: sin API key — usando TLT proxy")
        tlt_prices, _ = fetch_yahoo_series("TLT", "6mo")
        if tlt_prices:
            tlt_trend = calc_trend(tlt_prices, 63)
            macro["interest_rates"] = {
                "fed_funds": None, "proxy": "TLT",
                "trend": "down" if tlt_trend=="up" else ("up" if tlt_trend=="down" else "neutral"),
                "score": 70 if tlt_trend=="up" else (30 if tlt_trend=="down" else 50),
                "interpretation": (
                    "TLT subiendo → tipos bajando — favorable para crecimiento" if tlt_trend=="up"
                    else "TLT bajando → tipos subiendo — presión sobre crecimiento" if tlt_trend=="down"
                    else "Tipos estables — impacto neutro"
                )
            }
        else:
            macro["interest_rates"] = {"fed_funds": None, "trend": "neutral", "score": 50}
    time.sleep(0.5)

    print("  Bitcoin halving...", end=" ")
    halving = bitcoin_halving_phase()
    macro["bitcoin_halving"] = halving
    print(f"{halving['phase']} ({halving['months_since_halving']}M)")

    vix_val = macro.get("vix", {}).get("value")
    if vix_val:
        pcr = "extreme_fear" if vix_val>35 else "fear" if vix_val>25 else "complacency" if vix_val<15 else "neutral"
        macro["market_sentiment"] = {
            "signal": pcr, "source": "VIX proxy",
            "contrarian_buy": pcr=="extreme_fear",
            "interpretation": (
                "Miedo extremo — señal contrarian de compra" if pcr=="extreme_fear"
                else "Miedo — vigilar oportunidades" if pcr=="fear"
                else "Complacencia — entradas más arriesgadas" if pcr=="complacency"
                else "Neutral"
            )
        }
    else:
        macro["market_sentiment"] = {"signal": "neutral", "contrarian_buy": False}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(macro, fh, ensure_ascii=False, indent=2)

    print(f"\nOK — macro.json guardado")
    print(f"  VIX: {macro.get('vix',{}).get('value','?')}")
    print(f"  DXY: {macro.get('dxy',{}).get('value','?')} ({macro.get('dxy',{}).get('trend','?')})")
    print(f"  Tipos: {macro.get('interest_rates',{}).get('interpretation','?')}")
    print(f"  Halving BTC: {macro.get('bitcoin_halving',{}).get('description','?')}")

if __name__ == "__main__":
    main()
