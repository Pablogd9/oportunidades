#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor del escaner de oportunidades - version 9.

Mejoras vs v8:
  - Universo actualizado: ARKG->IBB, BOTZ->WTAI, IGF->GRID, XLV->VHT, +ITA, +NLR
  - BITO y WGMI retirados (futuros con decay, volatilidad extrema)
  - EUDF.DE en universo secundario (solo 324 dias de historico)
  - Filtro de liquidez: ETFs con AUM bajo penalizados
  - Filtro de historico minimo: <3 anos -> universo secundario
  - Bonus de confirmacion: +5pts si mismo sector fue Top1 el mes anterior
"""

import json, math, os, urllib.request, datetime

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNI   = os.path.join(ROOT, "universe.json")
MACRO = os.path.join(ROOT, "data", "macro.json")
OUT   = os.path.join(ROOT, "data", "output.json")
UA    = {"User-Agent": "Mozilla/5.0 (compatible; QuantScanner/9.0)"}
WARN  = []

CARTERA = [
    {"id":"SEMI","symbol":"SEMI.AS","name":"iShares MSCI Global Semiconductors","sector":"Semiconductores"},
    {"id":"BTC", "symbol":"BTC-EUR", "name":"Bitcoin",                           "sector":"Bitcoin y Cripto"},
]

W_FINAL = {"tech": 0.85, "macro": 0.15}
W_TECH  = {
    "rel_strength": 0.25,
    "ema200":       0.25,
    "mom6m":        0.20,
    "entry":        0.20,
    "consistency":  0.10,
}

MIN_HISTORY_DAYS = 756
MIN_AUM_BN       = 0.5

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_history(symbol, rng="5y"):
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

def fetch_history_weekly(symbol, rng="5y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1wk"
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
        WARN.append(f"{symbol}_weekly: {e}")
        return None, None

def fetch_fundamentals(symbol):
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=summaryDetail,defaultKeyStatistics,financialData"
    try:
        d  = _get(url)
        r  = d["quoteSummary"]["result"][0]
        sd = r.get("summaryDetail", {})
        ks = r.get("defaultKeyStatistics", {})
        fd = r.get("financialData", {})
        pe_trailing = (sd.get("trailingPE") or {}).get("raw")
        pe_forward  = (sd.get("forwardPE")  or {}).get("raw") or (ks.get("forwardPE") or {}).get("raw")
        beta        = (ks.get("beta") or {}).get("raw") or (sd.get("beta") or {}).get("raw")
        dy          = (sd.get("dividendYield") or {}).get("raw")
        eps_trailing= (ks.get("trailingEps") or {}).get("raw")
        eps_forward = (ks.get("forwardEps")  or {}).get("raw")
        growth_est  = (fd.get("earningsGrowth") or {}).get("raw") or (fd.get("revenueGrowth") or {}).get("raw")
        return {
            "pe":          round(pe_trailing,1) if pe_trailing else None,
            "pe_forward":  round(pe_forward,1)  if pe_forward  else None,
            "beta":        round(beta,2)         if beta        else None,
            "dy":          round(dy*100,2)       if dy          else None,
            "eps_trailing":round(eps_trailing,2) if eps_trailing else None,
            "eps_forward": round(eps_forward,2)  if eps_forward  else None,
            "growth_est":  round(growth_est*100,1) if growth_est else None,
        }
    except:
        return {"pe":None,"pe_forward":None,"beta":None,"dy":None,
                "eps_trailing":None,"eps_forward":None,"growth_est":None}

def ema_n(prices, n):
    if len(prices) < n: return None
    k = 2.0/(n+1); ema = sum(prices[:n])/n
    for p in prices[n:]: ema = p*k + ema*(1-k)
    return ema

def ret_n(prices, n):
    if len(prices) < n+1: return None
    p0, p1 = prices[-(n+1)], prices[-1]
    return (p1/p0-1)*100 if p0 > 0 else None

def vol_annual(prices, n=60):
    if len(prices) < n+1: return None
    rets = [prices[i]/prices[i-1]-1 for i in range(max(1,len(prices)-n), len(prices))]
    if len(rets) < 5: return None
    mean = sum(rets)/len(rets)
    sd   = math.sqrt(sum((r-mean)**2 for r in rets)/(len(rets)-1))
    return sd * math.sqrt(252) * 100

def vol_std(prices, n=252):
    return vol_annual(prices, min(n, len(prices)-1)) or 20.0

def drawdown_from_max(prices, n=252):
    if len(prices) < 2: return None
    window = prices[-min(n,len(prices)):]
    peak   = max(window)
    return round((prices[-1]/peak-1)*100,2) if peak > 0 else None

def drawdown_from_alltime_max(prices):
    if len(prices) < 2: return None
    peak = max(prices)
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

def compute_overvaluation(prices, fund):
    signals = []; signal_count = 0; bonus = False
    pe_now = fund.get("pe"); growth_est = fund.get("growth_est")
    per_expansion = None
    if pe_now and len(prices) >= 252:
        price_12m_ago = prices[-253] if len(prices) > 252 else prices[0]
        price_now = prices[-1]
        if price_12m_ago > 0 and price_now > 0:
            price_ratio = price_now / price_12m_ago
            per_12m_ago_implied = pe_now / price_ratio
            per_expansion = pe_now / per_12m_ago_implied
            if per_expansion > 1.5:
                signals.append(f"PER se expandió x{per_expansion:.1f} — beneficios no acompañan al precio")
                signal_count += 1
            elif per_expansion > 1.3:
                signals.append(f"Expansión de múltiplos moderada (x{per_expansion:.1f})")
                signal_count += 0.5
            elif per_expansion < 0.8 and pe_now:
                bonus = True
    peg = None
    if pe_now and growth_est and growth_est > 0:
        peg = round(pe_now / growth_est, 2)
        if peg > 3:
            signals.append(f"PEG muy alto ({peg:.1f}) — precio caro vs crecimiento")
            signal_count += 1
        elif peg > 2:
            signals.append(f"PEG elevado ({peg:.1f}) — cautela")
            signal_count += 0.5
        elif peg < 1:
            bonus = True
    dist_alltime = drawdown_from_alltime_max(prices)
    if dist_alltime is not None:
        if dist_alltime > -2:
            signals.append(f"En maximos historicos absolutos ({dist_alltime:.1f}%) — nunca visto")
            signal_count += 1
        elif dist_alltime > -5:
            signals.append(f"Muy cerca de maximos historicos ({dist_alltime:.1f}%)")
            signal_count += 0.5
    mom3m_now = ret_n(prices, 63)
    mom3m_history = []
    n = len(prices)
    for i in range(1, min(504, n-63)):
        r = ret_n(prices[:n-i], 63)
        if r is not None: mom3m_history.append(r)
    if mom3m_now is not None and mom3m_history:
        avg_mom3m = sum(mom3m_history) / len(mom3m_history)
        if avg_mom3m > 0 and mom3m_now > avg_mom3m * 3:
            signals.append(f"Momentum 3M ({mom3m_now:.1f}%) es {mom3m_now/avg_mom3m:.1f}x la media — euforia posible")
            signal_count += 1
        elif avg_mom3m > 0 and mom3m_now > avg_mom3m * 2:
            signals.append(f"Momentum 3M acelerado ({mom3m_now:.1f}% vs media {avg_mom3m:.1f}%)")
            signal_count += 0.5
    if signal_count >= 2.5:
        penalty = 0.5;  level = "🔴 Burbuja probable"
    elif signal_count >= 1.5:
        penalty = 0.7;  level = "🟠 Sobrevaloración significativa"
    elif signal_count >= 0.5:
        penalty = 0.85; level = "🟡 Ligera sobrevaloración"
    elif bonus:
        penalty = 1.10; level = "🟢 Precio justificado — beneficios acompañan"
    else:
        penalty = 1.0;  level = "⚪ Valoración neutral"
    return {
        "overval_score": round(min(100, signal_count/3*100), 0),
        "signals": signals, "penalty": penalty, "level": level,
        "per_expansion": round(per_expansion,2) if per_expansion else None,
        "peg": peg, "dist_alltime": dist_alltime, "bonus": bonus,
    }

def compute_technical_score(prices, iwda_prices):
    if not prices or len(prices) < 60: return None, {}
    n = len(prices); vol = vol_std(prices, min(252, n-1)); details = {}
    rs_now = None; rs_hist = []
    if iwda_prices and len(iwda_prices) >= 126:
        r_e = ret_n(prices, min(126,n-1)); r_i = ret_n(iwda_prices, min(126,len(iwda_prices)-1))
        if r_e is not None and r_i is not None: rs_now = (r_e - r_i) / (vol / 20.0)
        for i in range(126, min(n, 756)):
            p_e = prices[:n-i+126] if n-i+126>126 else prices[:126]
            p_i = iwda_prices[:len(iwda_prices)-i+126] if len(iwda_prices)-i+126>126 else iwda_prices[:126]
            re=ret_n(p_e,126); ri=ret_n(p_i,126)
            if re is not None and ri is not None:
                rs_hist.append((re-ri)/(vol_std(p_e,min(252,len(p_e)-1))/20.0))
    pct_rel = percentile_in_own_history(rs_now, rs_hist)
    details["rel_strength"] = {"value":round(rs_now,2) if rs_now else None,"percentile":pct_rel,
        "interpretation":("Lidera al mercado global" if rs_now and rs_now>1 else "Va por detrás del mercado" if rs_now and rs_now<-1 else "En línea con el mercado")}
    e200 = ema_n(prices, min(200,n))
    dist_ema200_now = ((prices[-1]/e200-1)*100) if e200 else None
    dist_ema_norm = (dist_ema200_now/(vol/20.0)) if dist_ema200_now else None
    ema200_hist = []
    for i in range(1, min(504, n-200)):
        pc=prices[:n-i]; e=ema_n(pc,min(200,len(pc)))
        if e: ema200_hist.append(((pc[-1]/e-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pct_ema = percentile_in_own_history(dist_ema_norm, ema200_hist)
    details["ema200"] = {"value":round(dist_ema200_now,2) if dist_ema200_now else None,
        "ema200_abs":round(e200,4) if e200 else None,"percentile":pct_ema,
        "above":dist_ema200_now>0 if dist_ema200_now is not None else None,
        "interpretation":(f"Muy por encima de EMA200 (+{dist_ema200_now:.1f}%)" if dist_ema200_now and dist_ema200_now>15
            else f"Por encima de EMA200 (+{dist_ema200_now:.1f}%)" if dist_ema200_now and dist_ema200_now>0
            else f"Por debajo de EMA200 ({dist_ema200_now:.1f}%)" if dist_ema200_now else "Sin datos EMA200")}
    mom6m_now = ret_n(prices, min(126,n-1))
    mom6m_norm = (mom6m_now/(vol/20.0)) if mom6m_now is not None else None
    mom6m_hist = []
    for i in range(1, min(756,n-126)):
        pc=prices[:n-i]; r=ret_n(pc,min(126,len(pc)-1))
        if r is not None: mom6m_hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    pct_mom6 = percentile_in_own_history(mom6m_norm, mom6m_hist)
    details["mom6m"] = {"value":round(mom6m_now,2) if mom6m_now else None,"percentile":pct_mom6,
        "interpretation":(f"Momentum 6M excepcional (+{mom6m_now:.1f}%)" if mom6m_now and mom6m_now>30
            else f"Momentum 6M fuerte (+{mom6m_now:.1f}%)" if mom6m_now and mom6m_now>10
            else f"Momentum 6M positivo (+{mom6m_now:.1f}%)" if mom6m_now and mom6m_now>0
            else f"Momentum 6M negativo ({mom6m_now:.1f}%)" if mom6m_now else "Sin datos")}
    dist_max_52w = drawdown_from_max(prices, 252); dist_max_5y = drawdown_from_alltime_max(prices)
    entry_combined = (dist_max_52w*0.60+dist_max_5y*0.40 if dist_max_52w is not None and dist_max_5y is not None
                      else dist_max_52w)
    dd_hist = []
    for i in range(1, min(756,n-252)):
        pc=prices[:n-i]; d=drawdown_from_max(pc,min(252,len(pc)))
        if d is not None: dd_hist.append(-d)
    pct_entry = percentile_in_own_history(-entry_combined if entry_combined is not None else None, dd_hist)
    details["entry"] = {"dist_from_max_52w":dist_max_52w,"dist_from_max_5y":dist_max_5y,"percentile":pct_entry,
        "interpretation":(f"Excelente entrada: {dist_max_5y:.0f}% bajo maximos historicos" if dist_max_5y and dist_max_5y<-25
            else f"Buena entrada: {dist_max_52w:.0f}% bajo maximos 52s" if dist_max_52w and dist_max_52w<-10
            else f"En maximos historicos — entrada muy exigente" if dist_max_5y and dist_max_5y>-3
            else f"Cerca de maximos ({dist_max_52w:.0f}%)" if dist_max_52w else "Sin datos")}
    consist_now = consistency_6m(prices); co_hist = []
    for i in range(1, min(756,n-130)):
        pc=prices[:n-i]; c=consistency_6m(pc)
        if c is not None: co_hist.append(c)
    pct_consist = percentile_in_own_history(consist_now, co_hist)
    details["consistency"] = {"value":consist_now,"percentile":pct_consist,
        "interpretation":(f"Muy consistente ({consist_now:.0f}% meses positivos)" if consist_now and consist_now>=80
            else f"Consistente ({consist_now:.0f}% meses positivos)" if consist_now and consist_now>=60
            else f"Inconsistente ({consist_now:.0f}% meses positivos)" if consist_now else "Sin datos")}
    score_tech = (W_TECH["rel_strength"]*pct_rel+W_TECH["ema200"]*pct_ema+
                  W_TECH["mom6m"]*pct_mom6+W_TECH["entry"]*pct_entry+W_TECH["consistency"]*pct_consist)
    mom3m = ret_n(prices, min(63,n-1)); penalty = 1.0
    if mom3m is not None and mom3m < -10:
        penalty = 0.6
        details["penalty"] = {"applied":True,"reason":f"Caída fuerte 3M ({mom3m:.1f}%) — score ×0.6","mom3m":round(mom3m,2)}
    else:
        details["penalty"] = {"applied":False,"mom3m":round(mom3m,2) if mom3m else None}
    details["extra"] = {
        "r1m":round(ret_n(prices,21),2) if ret_n(prices,21) else None,
        "r3m":round(mom3m,2) if mom3m else None,
        "r6m":round(mom6m_now,2) if mom6m_now else None,
        "r12m":round(ret_n(prices,252),2) if ret_n(prices,252) else None,
        "vol":round(vol_annual(prices),1) if vol_annual(prices) else None,
        "drawdown":dist_max_52w,"ann_ret":ann_ret(prices),"dist_max_5y":dist_max_5y,
    }
    return round(score_tech*penalty, 1), details

def compute_macro_score(macro_profile, macro):
    if not macro: return 50, {}
    rates=macro.get("interest_rates",{}); dxy=macro.get("dxy",{})
    inr=macro.get("inr",{}); ux=macro.get("uranium_spot",{}); halving=macro.get("bitcoin_halving",{})
    rates_score=rates.get("score",50); dxy_inv=dxy.get("score_inverse",50)
    ux_score=ux.get("score",50); halv_score=halving.get("halving_score",50); details={}
    if macro_profile=="growth_rates_sensitive":
        score=rates_score; details={"tipos":{"weight":"100%","score":rates_score,"desc":rates.get("interpretation","")}}
    elif macro_profile=="defensive_government":
        score=65; details={"base":{"weight":"100%","score":65,"desc":"Gasto gubernamental estructural"}}
    elif macro_profile=="em_dollar_sensitive":
        score=dxy_inv*0.60+rates_score*0.40
        if inr.get("trend")=="down": score*=0.85; details["rupia"]={"desc":"Rupia depreciándose — penalización"}
        details.update({"dolar":{"weight":"60%","score":dxy_inv,"desc":dxy.get("interpretation","")},
                         "tipos":{"weight":"40%","score":rates_score,"desc":rates.get("interpretation","")}})
    elif macro_profile=="defensive_growth":
        score=rates_score*0.40+70*0.60
        details={"tipos":{"weight":"40%","score":rates_score,"desc":rates.get("interpretation","")},
                 "base":{"weight":"60%","score":70,"desc":"Demanda estructural no cíclica"}}
    elif macro_profile=="rates_debt_sensitive":
        score=rates_score; details={"tipos":{"weight":"100%","score":rates_score,"desc":rates.get("interpretation","")}}
    elif macro_profile=="defensive_demographics":
        score=65; details={"base":{"weight":"100%","score":65,"desc":"Envejecimiento poblacional inevitable"}}
    elif macro_profile=="crypto_halving":
        score=rates_score*0.30+dxy_inv*0.30+halv_score*0.40
        details={"tipos":{"weight":"30%","score":rates_score,"desc":rates.get("interpretation","")},
                 "dolar":{"weight":"30%","score":dxy_inv,"desc":dxy.get("interpretation","")},
                 "halving":{"weight":"40%","score":halv_score,"desc":halving.get("description","")}}
    elif macro_profile=="uranium_spot":
        score=ux_score*0.70+rates_score*0.30
        details={"uranio_spot":{"weight":"70%","score":ux_score,"desc":ux.get("interpretation","")},
                 "tipos":{"weight":"30%","score":rates_score,"desc":rates.get("interpretation","")}}
    else:
        score=50
    return round(min(100,max(0,score)),1), details

def compute_final_score(score_tech, score_macro, overval_penalty):
    return round((score_tech*W_FINAL["tech"]+score_macro*W_FINAL["macro"])*overval_penalty, 1)

def ema200_signal_daily(prices):
    if len(prices)<200: return "neutral"
    e200=ema_n(prices,200)
    if e200 is None: return "neutral"
    dd=drawdown_from_max(prices); months_below=0
    for i in range(6):
        idx=-(21*(i+1))
        if abs(idx)>len(prices): break
        wp=prices[:len(prices)+idx+21]
        if len(wp)<200: break
        e=ema_n(wp,200)
        if e and wp[-1]<e: months_below+=1
        else: break
    if prices[-1]>e200: return "green"
    elif months_below>=3 and dd is not None and dd<-15: return "red"
    else: return "yellow"

def ema200_signal_weekly(prices_weekly):
    n=len(prices_weekly); ema_period=min(200,n-1) if n>50 else None
    if ema_period is None: return "neutral"
    e200w=ema_n(prices_weekly,ema_period)
    if e200w is None: return "neutral"
    dd=drawdown_from_max(prices_weekly); weeks_below=0
    for i in range(13):
        idx=-(i+1)
        if abs(idx)>len(prices_weekly): break
        wp=prices_weekly[:len(prices_weekly)+idx]
        if len(wp)<ema_period: break
        e=ema_n(wp,ema_period)
        if e and wp[-1]<e: weeks_below+=1
        else: break
    if prices_weekly[-1]>e200w: return "green"
    elif weeks_below>=13 and dd is not None and dd<-15: return "red"
    else: return "yellow"

def build_portfolio_signals(cartera):
    signals=[]
    for asset in cartera:
        is_crypto=asset["sector"]=="Bitcoin y Cripto"
        if is_crypto:
            prices_w,dates_w=fetch_history_weekly(asset["symbol"],"5y")
            prices_d,dates_d=fetch_history(asset["symbol"],"5y")
            if not prices_w or len(prices_w)<50:
                signals.append({**asset,"signal":"neutral","signal_text":"Sin datos","dist_ema200":None,"r3m":None,"r12m":None,"drawdown":None,"sparkline":[],"spark_dates":[]})
                continue
            signal=ema200_signal_weekly(prices_w)
            e200=ema_n(prices_w,min(200,len(prices_w)-1))
            dist_e=round((prices_w[-1]/e200-1)*100,1) if e200 else None
            prices_for_metrics=prices_d or prices_w; dates_for_spark=dates_d or dates_w
        else:
            prices_d,dates_d=fetch_history(asset["symbol"],"5y")
            if not prices_d or len(prices_d)<60:
                signals.append({**asset,"signal":"neutral","signal_text":"Sin datos","dist_ema200":None,"r3m":None,"r12m":None,"drawdown":None,"sparkline":[],"spark_dates":[]})
                continue
            signal=ema200_signal_daily(prices_d)
            e200=ema_n(prices_d,200); dist_e=round((prices_d[-1]/e200-1)*100,1) if e200 else None
            prices_for_metrics=prices_d; dates_for_spark=dates_d
        r3m=ret_n(prices_for_metrics,63); r12m=ret_n(prices_for_metrics,252); dd=drawdown_from_max(prices_for_metrics)
        text=("Tesis intacta — EMA200 alcista. Sigue aportando." if signal=="green"
              else f"Atención — por debajo de EMA200 {'semanal' if is_crypto else 'diaria'}. Vigilar." if signal=="yellow"
              else f"Señal de salida — EMA200 {'semanal' if is_crypto else 'diaria'} rota. Considera rotar.")
        signals.append({**asset,"signal":signal,"signal_text":text,"dist_ema200":dist_e,
            "ema_type":"weekly" if is_crypto else "daily",
            "r3m":round(r3m,2) if r3m else None,"r12m":round(r12m,2) if r12m else None,"drawdown":dd,
            "sparkline":[round(p,4) for p in prices_for_metrics[-60:]],
            "spark_dates":dates_for_spark[-60:] if dates_for_spark else []})
    return signals

def build_reasons(etf_data, macro_details, overval):
    ups,dns=[],[]
    td=etf_data.get("tech_details",{})
    rs=td.get("rel_strength",{})
    if rs.get("value") is not None:
        pct=rs.get("percentile",50)
        if pct>70: ups.append(f"{rs['interpretation']} — percentil {pct:.0f}")
        elif pct<30: dns.append(f"{rs['interpretation']} — percentil {pct:.0f}")
    em=td.get("ema200",{})
    if em.get("value") is not None:
        pct=em.get("percentile",50); val=em["value"]
        if pct>70 and val>0: ups.append(f"{em['interpretation']} — pct {pct:.0f}")
        elif val>0: ups.append(f"{em['interpretation']}")
        elif pct<30: dns.append(f"{em['interpretation']} — momento débil")
    m6=td.get("mom6m",{})
    if m6.get("value") is not None:
        pct=m6.get("percentile",50)
        if pct>75: ups.append(f"{m6['interpretation']} — percentil {pct:.0f}")
        elif pct<25: dns.append(f"{m6['interpretation']} — percentil {pct:.0f}")
    en=td.get("entry",{})
    if en.get("dist_from_max_5y") is not None:
        pct=en.get("percentile",50)
        if pct>65: ups.append(f"{en['interpretation']}")
        elif pct<35: dns.append(f"{en['interpretation']}")
    co=td.get("consistency",{})
    if co.get("value") is not None:
        if co["percentile"]>70: ups.append(f"{co['interpretation']}")
        elif co["percentile"]<30: dns.append(f"{co['interpretation']}")
    pen=td.get("penalty",{})
    if pen.get("applied"): dns.append(pen.get("reason",""))
    if overval:
        for sig in overval.get("signals",[])[:2]: dns.append(f"Valoración: {sig}")
        if overval.get("bonus"): ups.append(f"Valoración: {overval.get('level','')} — precio justificado")
        elif overval.get("penalty",1)<1: dns.append(f"Valoración: {overval.get('level','')}")
    for key,md in macro_details.items():
        if isinstance(md,dict) and md.get("desc"):
            score=md.get("score",50)
            if score>70: ups.append(f"Macro: {md['desc']}")
            elif score<30: dns.append(f"Macro: {md['desc']}")
    return ups[:4],dns[:4]

def best_etf_per_sector(records):
    sectors={}
    for r in records:
        s=r["sector"]
        if s not in sectors or r["score_final"]>sectors[s]["score_final"]: sectors[s]=r
    return list(sectors.values())

def build_recommendation(sector_ranking, month_str, portfolio_signals, prev_top1_sector=None):
    if not sector_ranking:
        return {"mes":month_str,"accion_principal":"Sin datos","distribucion":[],"nota":""}
    top1=dict(sector_ranking[0]); top2=sector_ranking[1] if len(sector_ranking)>1 else None
    if prev_top1_sector and top1["sector"]==prev_top1_sector:
        top1["score_final"]=round(top1["score_final"]+5,1); top1["confirmacion"]=True
    else:
        top1["confirmacion"]=False
    ya_tiene=any(s["symbol"]==top1["symbol"] for s in portfolio_signals)
    accion=(f"Añade más a lo que ya tienes: {top1['name']} ({top1['symbol']}) — sigue siendo el #1"
            if ya_tiene else f"Aporta este mes en: {top1['name']} ({top1['symbol']})")
    score1=top1["score_final"]
    if score1>=70:   dist1,dist2,calidad=350,150,"🟢 Señal fuerte"
    elif score1>=55: dist1,dist2,calidad=300,200,"🟡 Señal moderada"
    else:            dist1,dist2,calidad=250,250,"🟠 Señal débil — diversifica más"
    top2_score=top2["score_final"] if top2 else 0
    distribucion=[{"rank":1,"name":top1["name"],"symbol":top1["symbol"],"sector":top1["sector"],
                   "score":score1,"euros":dist1,"pct":round(dist1/500*100),
                   "overval_level":top1.get("overval_level","⚪"),"confirmada":top1.get("confirmacion",False)}]
    if top2:
        distribucion.append({"rank":2,"name":top2["name"],"symbol":top2["symbol"],"sector":top2["sector"],
                             "score":top2_score,"euros":dist2,"pct":round(dist2/500*100),
                             "overval_level":top2.get("overval_level","⚪")})
    return {"mes":month_str,"calidad":calidad,"score_top1":score1,"accion_principal":accion,
            "distribucion":distribucion,"por_que":top1.get("reasons_up",[])[:2],
            "top2_nota":f"Top2 con señal fuerte ({top2_score:.0f})" if top2_score>=70 and score1>=70 else None,
            "confirmacion_nota":"✓ Señal confirmada — mismo sector que el mes anterior" if top1.get("confirmacion") else None,
            "nota":"Revisa el nivel de valoración. 🔴 o 🟠 indica riesgo de sobrevaloración."}

def main():
    with open(UNI,encoding="utf-8") as f: uni_data=json.load(f)
    universe_all=uni_data["etfs"]
    universe_primary=[e for e in universe_all if e.get("universe","primary")=="primary"]
    universe_secondary=[e for e in universe_all if e.get("universe","primary")=="secondary"]
    print(f"Universo principal: {len(universe_primary)} ETFs")
    print(f"Universo secundario: {len(universe_secondary)} ETFs")
    macro={}
    if os.path.exists(MACRO):
        with open(MACRO,encoding="utf-8") as f: macro=json.load(f)
    print("Descargando IWDA benchmark (5 anos)...")
    iwda_prices,_=fetch_history("IWDA.AS","5y")
    print(f"\nAnalizando universo principal (modelo v9)...")
    records=[]
    for etf in universe_primary:
        sym=etf["symbol"]; aum=etf.get("aum_bn",1.0)
        print(f"  {sym}...",end=" ",flush=True)
        prices,dates=fetch_history(sym,"5y")
        if not prices or len(prices)<60: print("sin datos"); continue
        if len(prices)<MIN_HISTORY_DAYS:
            print(f"historico insuficiente ({len(prices)}d)"); WARN.append(f"{sym}: historico insuficiente"); continue
        score_tech,tech_details=compute_technical_score(prices,iwda_prices)
        if score_tech is None: print("insuficiente"); continue
        score_macro,macro_details=compute_macro_score(etf.get("macro_profile",""),macro)
        fund=fetch_fundamentals(sym); overval=compute_overvaluation(prices,fund)
        aum_penalty=1.0
        if aum<MIN_AUM_BN: aum_penalty=0.95; WARN.append(f"{sym}: AUM bajo ({aum}B)")
        score_final=compute_final_score(score_tech,score_macro,overval["penalty"]*aum_penalty)
        extra=tech_details.get("extra",{})
        rec={
            "id":etf["id"],"name":etf["name"],"symbol":sym,"sector":etf["sector"],
            "conviction":etf.get("conviction",4),"macro_profile":etf.get("macro_profile",""),
            "aum_bn":aum,"universe":"primary","last":round(prices[-1],4),
            "score_tech":score_tech,"score_macro":score_macro,"score_final":score_final,
            "pct_rel_strength":tech_details.get("rel_strength",{}).get("percentile"),
            "pct_ema200":tech_details.get("ema200",{}).get("percentile"),
            "pct_mom6m":tech_details.get("mom6m",{}).get("percentile"),
            "pct_entry":tech_details.get("entry",{}).get("percentile"),
            "pct_consistency":tech_details.get("consistency",{}).get("percentile"),
            "rel_strength":tech_details.get("rel_strength",{}).get("value"),
            "dist_ema200":tech_details.get("ema200",{}).get("value"),
            "ema200_abs":tech_details.get("ema200",{}).get("ema200_abs"),
            "dist_from_max":tech_details.get("entry",{}).get("dist_from_max_52w"),
            "dist_from_max_5y":tech_details.get("entry",{}).get("dist_from_max_5y"),
            "consistency_pct":tech_details.get("consistency",{}).get("value"),
            "mom_penalty":not tech_details.get("penalty",{}).get("applied",False),
            "r1m":extra.get("r1m"),"r3m":extra.get("r3m"),"r6m":extra.get("r6m"),"r12m":extra.get("r12m"),
            "vol":extra.get("vol"),"drawdown":extra.get("drawdown"),"ann_ret":extra.get("ann_ret"),
            "pe":fund.get("pe"),"pe_forward":fund.get("pe_forward"),"beta":fund.get("beta"),
            "dy":fund.get("dy"),"growth_est":fund.get("growth_est"),
            "overval_score":overval["overval_score"],"overval_level":overval["level"],
            "overval_penalty":overval["penalty"],"overval_signals":overval["signals"],
            "per_expansion":overval.get("per_expansion"),"peg":overval.get("peg"),
            "dist_from_max_5y_overval":overval.get("dist_alltime"),
            "sparkline":[round(p,4) for p in prices[-60:]],"spark_dates":dates[-60:] if dates else [],
            "tech_details":tech_details,"macro_details":macro_details,
        }
        ups,dns=build_reasons(rec,macro_details,overval)
        rec["reasons_up"]=ups; rec["reasons_down"]=dns
        del rec["tech_details"]; del rec["macro_details"]
        records.append(rec)
        overval_str=f" {overval['level']}" if overval["penalty"]!=1.0 else ""
        print(f"tech={score_tech:.0f} macro={score_macro:.0f} final={score_final:.0f} n={len(prices)}d{overval_str}")
    if not records: print("ERROR: sin datos"); return
    records.sort(key=lambda x:x["score_final"],reverse=True)
    sector_ranking=best_etf_per_sector(records)
    sector_ranking.sort(key=lambda x:x["score_final"],reverse=True)
    print("\nAnalizando cartera actual...")
    portfolio_signals=build_portfolio_signals(CARTERA)
    for s in portfolio_signals:
        icon="✅" if s["signal"]=="green" else ("⚠️" if s["signal"]=="yellow" else "🔴")
        ema_t="(semanal)" if s.get("ema_type")=="weekly" else "(diaria)"
        print(f"  {icon} {s['symbol']} {ema_t}: {s['signal_text']}")
    month_str=datetime.date.today().strftime("%B %Y")
    recommendation=build_recommendation(sector_ranking,month_str,portfolio_signals)
    macro_context={"tipos":macro.get("interest_rates",{}).get("interpretation","Sin datos"),
        "vix":macro.get("vix",{}).get("interpretation","Sin datos"),
        "dolar":macro.get("dxy",{}).get("interpretation","Sin datos"),
        "halving":macro.get("bitcoin_halving",{}).get("description","Sin datos"),
        "fred":macro.get("fred_available",False),"updated":macro.get("updated","")}
    out={"updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z",
        "total_analyzed":len(records),"model_version":"9.0",
        "factor_weights":{"tech":W_FINAL["tech"],"macro":W_FINAL["macro"],"tech_factors":W_TECH},
        "recommendation":recommendation,"portfolio_signals":portfolio_signals,
        "sector_ranking":sector_ranking,"all":records,"macro_context":macro_context,"warnings":WARN}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as fh: json.dump(out,fh,ensure_ascii=False,indent=2)
    print(f"\n{'='*65}")
    print(f"RECOMENDACIÓN {month_str} — {recommendation['calidad']}")
    print(f"  {recommendation['accion_principal']}")
    if recommendation.get("confirmacion_nota"): print(f"  {recommendation['confirmacion_nota']}")
    for d in recommendation.get("distribucion",[]):
        conf=" ✓confirmada" if d.get("confirmada") else ""
        print(f"  #{d['rank']} {d['symbol']:10s} score={d['score']:5.1f} → €{d['euros']} ({d['pct']}%) {d.get('overval_level','')}{conf}")
    print(f"\nRANKING SECTORES (v9):")
    for i,r in enumerate(sector_ranking[:5]):
        print(f"  #{i+1} {r['sector']:20s} {r['symbol']:10s} score={r['score_final']:5.1f} {r.get('overval_level','')}")
    print(f"{'='*65}")
    print(f"v9: universo actualizado, filtro historico/liquidez, confirmacion mensual")
    print(f"Primario: {len(records)} ETFs | Secundario: {len(universe_secondary)} | Avisos: {len(WARN)}")

if __name__ == "__main__":
    main()
