#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, os, datetime, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE    = os.path.join(ROOT, "data", "cache")
MANIFEST = os.path.join(CACHE, "_manifest.json")
UA       = {"User-Agent": "Mozilla/5.0 (compatible; CacheBuilder/1.0)"}

UNIVERSE = [
    {"id":"SMH",  "symbol":"SMH",     "name":"VanEck Semiconductor ETF",           "sector":"Semiconductores", "use":"backtest+scan", "inception":"2000-05-05", "aum_bn":72.0},
    {"id":"IBB",  "symbol":"IBB",     "name":"iShares Nasdaq Biotechnology ETF",   "sector":"Biotecnologia",   "use":"backtest+scan", "inception":"2001-02-05", "aum_bn":7.8},
    {"id":"ITA",  "symbol":"ITA",     "name":"iShares US Aerospace & Defense",     "sector":"Defensa",         "use":"backtest+scan", "inception":"2001-05-01", "aum_bn":6.1},
    {"id":"IGV",  "symbol":"IGV",     "name":"iShares Expanded Tech-Software ETF", "sector":"Software y Cloud","use":"backtest+scan", "inception":"2001-07-10", "aum_bn":9.2},
    {"id":"VHT",  "symbol":"VHT",     "name":"Vanguard Health Care ETF",           "sector":"Salud",           "use":"backtest+scan", "inception":"2004-01-26", "aum_bn":18.2},
    {"id":"PHO",  "symbol":"PHO",     "name":"Invesco Water Resources ETF",        "sector":"Agua",            "use":"backtest+scan", "inception":"2005-12-06", "aum_bn":2.1},
    {"id":"XBI",  "symbol":"XBI",     "name":"SPDR S&P Biotech ETF",               "sector":"Biotecnologia",   "use":"backtest+scan", "inception":"2006-02-06", "aum_bn":6.4},
    {"id":"IHI",  "symbol":"IHI",     "name":"iShares US Medical Devices ETF",     "sector":"Salud",           "use":"backtest+scan", "inception":"2006-05-01", "aum_bn":4.1},
    {"id":"ICLN", "symbol":"ICLN",    "name":"iShares Global Clean Energy ETF",    "sector":"Energia Limpia",  "use":"backtest+scan", "inception":"2008-06-24", "aum_bn":2.8},
    {"id":"GRID", "symbol":"GRID",    "name":"First Trust NASDAQ Smart Grid",      "sector":"Infraestructura", "use":"backtest+scan", "inception":"2009-11-19", "aum_bn":0.6},
    {"id":"COPX", "symbol":"COPX",    "name":"Global X Copper Miners ETF",         "sector":"Cobre y Metales", "use":"backtest+scan", "inception":"2010-04-19", "aum_bn":2.3},
    {"id":"LIT",  "symbol":"LIT",     "name":"Global X Lithium & Battery Tech ETF","sector":"Litio y Baterias","use":"backtest+scan", "inception":"2010-07-22", "aum_bn":1.4},
    {"id":"INDA", "symbol":"INDA",    "name":"iShares MSCI India ETF",             "sector":"India",           "use":"backtest+scan", "inception":"2012-02-02", "aum_bn":8.9},
    {"id":"ROBO", "symbol":"ROBO",    "name":"Robo Global Robotics & Automation",  "sector":"Robotica e IA",   "use":"backtest+scan", "inception":"2013-10-22", "aum_bn":1.8},
    {"id":"CIBR", "symbol":"CIBR",    "name":"First Trust Nasdaq Cybersecurity",   "sector":"Ciberseguridad",  "use":"backtest+scan", "inception":"2015-07-07", "aum_bn":6.2},
    {"id":"PAVE", "symbol":"PAVE",    "name":"Global X US Infrastructure Dev",     "sector":"Infraestructura", "use":"backtest+scan", "inception":"2016-10-11", "aum_bn":7.3},
    {"id":"NLR",  "symbol":"NLR",     "name":"VanEck Uranium+Nuclear Energy ETF",  "sector":"Uranio y Nuclear","use":"proxy",         "inception":"2007-08-13", "aum_bn":0.9},
    {"id":"XAR",  "symbol":"XAR",     "name":"SPDR S&P Aerospace & Defense ETF",   "sector":"Defensa",         "use":"proxy",         "inception":"2011-09-28", "aum_bn":2.1},
    {"id":"HACK", "symbol":"HACK",    "name":"ETFMG Prime Cyber Security ETF",     "sector":"Ciberseguridad",  "use":"proxy",         "inception":"2014-11-12", "aum_bn":1.5},
    {"id":"CGW",  "symbol":"CGW",     "name":"Invesco S&P Global Water ETF",       "sector":"Agua",            "use":"proxy",         "inception":"2005-05-13", "aum_bn":0.8},
    {"id":"SEMI", "symbol":"SEMI.AS", "name":"iShares MSCI Global Semiconductors", "sector":"Semiconductores", "use":"scan_only",     "inception":"2010-10-01", "aum_bn":8.2},
    {"id":"WTAI", "symbol":"WTAI",    "name":"WisdomTree AI ETF",                  "sector":"IA y Robotica",   "use":"scan_only",     "inception":"2023-01-10", "aum_bn":1.2},
    {"id":"NATO", "symbol":"NATO",    "name":"VanEck Defense ETF",                 "sector":"Defensa",         "use":"scan_only",     "inception":"2023-08-08", "aum_bn":1.8},
    {"id":"GNOM", "symbol":"GNOM",    "name":"Global X Genomics & Biotech ETF",    "sector":"Genomica",        "use":"scan_only",     "inception":"2019-04-05", "aum_bn":0.5},
    {"id":"EMXC", "symbol":"EMXC",    "name":"iShares MSCI EM ex China ETF",       "sector":"Emergentes",      "use":"scan_only",     "inception":"2017-07-13", "aum_bn":9.2},
    {"id":"FLIN", "symbol":"FLIN",    "name":"Franklin FTSE India ETF",            "sector":"India",           "use":"scan_only",     "inception":"2017-02-06", "aum_bn":0.9},
    {"id":"BUG",  "symbol":"BUG",     "name":"Global X Cybersecurity ETF",         "sector":"Ciberseguridad",  "use":"scan_only",     "inception":"2019-11-04", "aum_bn":0.8},
    {"id":"QCLN", "symbol":"QCLN",    "name":"First Trust NASDAQ Clean Edge ETF",  "sector":"Energia Limpia",  "use":"scan_only",     "inception":"2007-02-20", "aum_bn":1.1},
    {"id":"URNM", "symbol":"URNM",    "name":"Sprott Uranium Miners ETF",          "sector":"Uranio y Nuclear","use":"scan_only",     "inception":"2019-12-03", "aum_bn":1.2},
    {"id":"IWDA", "symbol":"IWDA.AS", "name":"iShares Core MSCI World UCITS ETF",  "sector":"Benchmark",       "use":"benchmark",     "inception":"2009-09-25", "aum_bn":120.0},
    {"id":"SPY",  "symbol":"SPY",     "name":"SPDR S&P 500 ETF Trust",             "sector":"Benchmark",       "use":"benchmark",     "inception":"1993-01-22", "aum_bn":580.0},
]

MAX_WORKERS = 6

def _get(url, timeout=30):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_full_history(symbol):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=max&interval=1d"
    try:
        d=_get(url); res=d["chart"]["result"][0]
        ts=res.get("timestamp") or []
        cls=(res.get("indicators") or {}).get("quote",[{}])[0].get("close") or []
        pairs={}
        for t,c in zip(ts,cls):
            if c is None: continue
            pairs[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")]=round(float(c),6)
        series=sorted(pairs.items())
        return {"dates":[d for d,_ in series],"prices":[p for _,p in series],
                "count":len(series),"first":series[0][0] if series else None,
                "last":series[-1][0] if series else None}
    except Exception as e:
        return {"error":str(e),"dates":[],"prices":[],"count":0}

def fetch_recent_history(symbol):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=1d"
    try:
        d=_get(url); res=d["chart"]["result"][0]
        ts=res.get("timestamp") or []
        cls=(res.get("indicators") or {}).get("quote",[{}])[0].get("close") or []
        pairs={}
        for t,c in zip(ts,cls):
            if c is None: continue
            pairs[datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")]=round(float(c),6)
        series=sorted(pairs.items())
        return {"dates":[d for d,_ in series],"prices":[p for _,p in series]}
    except Exception as e:
        return {"error":str(e),"dates":[],"prices":[]}

def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST,encoding="utf-8") as f: return json.load(f)
    return {"updated":None,"etfs":{}}

def save_manifest(manifest):
    manifest["updated"]=datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z"
    with open(MANIFEST,"w",encoding="utf-8") as f: json.dump(manifest,f,ensure_ascii=False,indent=2)

def load_cache(symbol):
    path=os.path.join(CACHE,f"{symbol.replace('.','-')}.json")
    if os.path.exists(path):
        with open(path,encoding="utf-8") as f: return json.load(f)
    return None

def save_cache(symbol,data):
    path=os.path.join(CACHE,f"{symbol.replace('.','-')}.json")
    with open(path,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,separators=(",",":"))

def merge_with_cache(cached,new_data):
    if not new_data.get("dates"): return cached,0
    existing=set(cached["dates"]); added=0
    for date,price in zip(new_data["dates"],new_data["prices"]):
        if date not in existing and date>cached["last"]:
            cached["dates"].append(date); cached["prices"].append(price); added+=1
    if added>0:
        pairs=sorted(zip(cached["dates"],cached["prices"]))
        cached["dates"]=[d for d,_ in pairs]; cached["prices"]=[p for _,p in pairs]
        cached["count"]=len(cached["dates"]); cached["last"]=cached["dates"][-1]
    return cached,added

def needs_update(manifest,symbol):
    info=manifest["etfs"].get(symbol,{})
    last=info.get("last_updated")
    if not last: return True
    days=(datetime.datetime.utcnow()-datetime.datetime.fromisoformat(last.replace("Z",""))).days
    return days>=1

def process_etf(etf,manifest,force_full=False):
    symbol=etf["symbol"]
    result={"symbol":symbol,"id":etf["id"],"status":None,"days":0,"added":0}
    cached=load_cache(symbol)
    if cached and cached.get("count",0)>0 and not force_full:
        if not needs_update(manifest,symbol):
            result["status"]="skip"; result["days"]=cached["count"]; return result
        new_data=fetch_recent_history(symbol)
        if new_data.get("error"):
            result["status"]=f"error: {new_data['error']}"; return result
        cached,added=merge_with_cache(cached,new_data)
        cached["last_updated"]=datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z"
        save_cache(symbol,cached)
        result["status"]="updated"; result["days"]=cached["count"]; result["added"]=added
    else:
        data=fetch_full_history(symbol)
        if data.get("error") or data["count"]==0:
            result["status"]=f"error: {data.get('error','sin datos')}"; return result
        data.update({"symbol":symbol,"id":etf["id"],"name":etf["name"],"sector":etf["sector"],
                     "use":etf["use"],"inception":etf.get("inception"),"aum_bn":etf.get("aum_bn"),
                     "last_updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z"})
        save_cache(symbol,data)
        result["status"]="downloaded"; result["days"]=data["count"]
    return result

def validate_cache():
    print("\nValidando cache...")
    issues=[]
    for etf in UNIVERSE:
        symbol=etf["symbol"]; cached=load_cache(symbol)
        if not cached: issues.append(f"  {symbol}: no encontrado"); continue
        if cached.get("count",0)<20: issues.append(f"  {symbol}: solo {cached.get('count',0)} dias"); continue
        print(f"  {symbol:10s} {cached['count']:5d} dias | {cached.get('first')} -> {cached.get('last')}")
    if issues: [print(i) for i in issues]
    else: print("Cache validado correctamente")

def print_summary():
    print("\n"+"="*60+"\nRESUMEN DEL CACHE\n"+"="*60)
    for group_name,group in [("BACKTEST",[e for e in UNIVERSE if "backtest" in e["use"]]),
                              ("PROXY",[e for e in UNIVERSE if e["use"]=="proxy"]),
                              ("SOLO ESCANER",[e for e in UNIVERSE if e["use"]=="scan_only"]),
                              ("BENCHMARK",[e for e in UNIVERSE if e["use"]=="benchmark"])]:
        print(f"\n[{group_name}]")
        for etf in group:
            cached=load_cache(etf["symbol"])
            if cached and cached.get("count",0)>0:
                try: years=round((datetime.date.fromisoformat(cached["last"])-datetime.date.fromisoformat(cached["first"])).days/365.25,1)
                except: years=0
                print(f"  {etf['symbol']:10s} {cached['count']:>6} dias | {cached.get('first')} -> {cached.get('last')} | {years:.1f}A")
            else: print(f"  {etf['symbol']:10s} sin datos")
    print("\n"+"="*60+"\nPODER ESTADISTICO (rolling window 5 anos)\n"+"-"*60)
    total=0
    for etf in [e for e in UNIVERSE if "backtest" in e["use"]]:
        cached=load_cache(etf["symbol"])
        if cached and cached.get("count",0)>0:
            try:
                years=(datetime.date.fromisoformat(cached["last"])-datetime.date.fromisoformat(cached["first"])).days/365.25
                if years>5: s=int((years-5)*12); total+=s; print(f"  {etf['symbol']:10s} {years:.1f}A -> ~{s} senales")
            except: pass
    print(f"\n  TOTAL senales estimadas: ~{total}")
    if total>200: print("  EXCELENTE")
    elif total>120: print("  BUENO")
    else: print("  INSUFICIENTE")
    print("="*60)

def main():
    import sys
    force_full="--force" in sys.argv
    os.makedirs(CACHE,exist_ok=True)
    manifest=load_manifest()
    print(f"Actualizando cache — {len(UNIVERSE)} simbolos\n")
    t_start=datetime.datetime.utcnow(); results=[]; errors=[]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures={ex.submit(process_etf,etf,manifest,force_full):etf for etf in UNIVERSE}
        for future in as_completed(futures):
            etf=futures[future]
            try:
                r=future.result(); results.append(r)
                s,sym,days,added=r["status"],r["symbol"],r["days"],r.get("added",0)
                if s=="downloaded": print(f"  {sym:12s} {days:5d} dias (historico completo)")
                elif s=="updated":  print(f"  {sym:12s} {days:5d} dias (+{added} nuevos)")
                elif s=="skip":     print(f"  {sym:12s} {days:5d} dias (sin cambios)")
                elif s and s.startswith("error"): print(f"  {sym:12s} ERROR: {s}"); errors.append(sym)
                manifest["etfs"][sym]={"last_updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z","days":days,"status":s}
            except Exception as e:
                print(f"  {etf['symbol']:12s} EXCEPCION: {e}"); errors.append(etf["symbol"])
    save_manifest(manifest)
    elapsed=round((datetime.datetime.utcnow()-t_start).seconds,0)
    dl=sum(1 for r in results if r["status"]=="downloaded")
    print(f"\nCompletado en {elapsed}s | Descargados:{dl} | Errores:{len(errors)}")
    if errors: print(f"Errores: {', '.join(errors)}")
    validate_cache()
    print_summary()

if __name__=="__main__":
    main()
