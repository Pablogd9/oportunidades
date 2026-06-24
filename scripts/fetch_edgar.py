#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_edgar.py — Holdings reales de ETFs via SEC EDGAR N-PORT.
"""

import json, os, urllib.request, datetime, time

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLD_DIR = os.path.join(ROOT, "data", "cache", "holdings")
UA       = {"User-Agent": "pablo@example.com QuantScanner/1.0"}

ETF_CIK_MAP = {
    "ITA":  "0001100663",
    "COPX": "0001432353",
    "ROBO": "0001318814",
    "INDA": "0001100663",
    "PHO":  "0000049077",
    "ICLN": "0001100663",
    "IGV":  "0001100663",
    "LIT":  "0001432353",
}

ETF_HOLDINGS_FALLBACK = {
    "ITA":  ["RTX","LMT","NOC","GD","BA","HII","TDG","HEI","TXT","LDOS",
              "SAIC","CACI","BAH","MOOG","AXON","KTOS","AVAV","SPR","DRS","L3H"],
    "COPX": ["FCX","SCCO","BHP","RIO","GLEN","TECK","FM","HBM","CMMC","ERO",
              "IVN","ANTO","TGB","NGEX","MTAL","CS","FQVLF","CU","LUNR","GEX"],
    "ROBO": ["ISRG","ABB","FANUC","KEYB","BRKS","NOVT","NDSN","TRMB","ROP",
              "AZTA","ONTO","LRCX","GTLS","ITRI","XYL","FLOW","BRKR","MKSI","IRBT"],
    "INDA": ["INFY","WIPRO","HDB","IBN","WIT","RELIANCE","BHARTIARTL","TCS",
              "HINDUNILVR","ICICIBC","SBIN","LT","KOTAKBANK","BAJFINANCE","ASIANPAINT",
              "ULTRACEMCO","TITAN","NESTLEIND","HDFCB","AXBK"],
    "PHO":  ["XYL","AWK","PRIM","MSEX","SJW","AWR","CWT","NI","GHM",
              "ITRI","WATTS","GWW","ARTNA","WTR","YORW","MUELLER","ARIS","LAYNE","GWCO","REXNORD"],
    "ICLN": ["NEE","ENPH","FSLR","BEP","SEDG","CWEN","PLUG","HASI","AY",
              "ARRY","MAXN","RUN","AMRC","NOVA","NEP","BEPC","SPWR","VWDRY","ORSTED","RWE"],
    "IGV":  ["MSFT","CRM","ORCL","ADBE","NOW","SNOW","PLTR","WDAY","TEAM","INTU",
              "ADSK","ANSS","CDNS","PTC","TTWO","EA","RBLX","U","DDOG","ZS"],
    "LIT":  ["ALB","SQM","LTHM","LAC","SGML","PLL","LIVENT","ALTM","EVGO","CHPT",
              "BYDDF","CATL","PANASONIC","LG","SAMSUNG","TESLA","BYD","ENVX","FREY","FREYR"],
}

def _get(url, timeout=20):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_holdings_edgar(symbol, cik):
    try:
        url=f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
        data=_get(url)
        filings=data.get("filings",{}).get("recent",{})
        forms=filings.get("form",[]); dates=filings.get("filingDate",[])
        nport_idx=next((i for i,f in enumerate(forms) if f in ("N-PORT","N-PORT/A")),None)
        if nport_idx is None: return None,"No N-PORT encontrado"
        filing_date=dates[nport_idx]
        facts=_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json")
        investments=facts.get("facts",{}).get("nport-p",{})
        if not investments: return None,"Sin datos XBRL N-PORT"
        holdings_raw={}
        if "InvstOrSecs" in investments:
            for item in investments["InvstOrSecs"].get("units",{}).get("USD",[]):
                ticker=item.get("ticker") or item.get("name","")
                val=item.get("val",0)
                if ticker and val>0: holdings_raw[ticker]=holdings_raw.get(ticker,0)+val
        if not holdings_raw: return None,"Sin holdings en XBRL"
        total=sum(holdings_raw.values())
        holdings=[{"ticker":t,"weight_pct":round(v/total*100,2) if total>0 else 0,"value_usd":round(v)}
                  for t,v in sorted(holdings_raw.items(),key=lambda x:-x[1])[:30]]
        return holdings,filing_date
    except Exception as e: return None,str(e)

def fetch_holdings_simple(symbol):
    try:
        d=_get(f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=topHoldings")
        raw=d["quoteSummary"]["result"][0]["topHoldings"]["holdings"]
        holdings=[{"ticker":h.get("symbol",""),"weight_pct":round(h.get("holdingPercent",0)*100,2),"value_usd":None}
                  for h in raw[:20] if h.get("symbol")]
        return holdings if holdings else None
    except: return None

def save_holdings(symbol,holdings,source,report_date=None):
    os.makedirs(HOLD_DIR,exist_ok=True)
    path=os.path.join(HOLD_DIR,f"{symbol.replace('.','-')}_holdings.json")
    with open(path,"w",encoding="utf-8") as f:
        json.dump({"symbol":symbol,"source":source,
                   "report_date":report_date or datetime.date.today().isoformat(),
                   "updated":datetime.datetime.utcnow().isoformat(timespec="seconds")+"Z",
                   "count":len(holdings),"tickers":[h["ticker"] for h in holdings],
                   "holdings":holdings},f,ensure_ascii=False,indent=2)

def load_holdings(symbol):
    path=os.path.join(HOLD_DIR,f"{symbol.replace('.','-')}_holdings.json")
    if os.path.exists(path):
        with open(path,encoding="utf-8") as f: return json.load(f)
    return None

def needs_update(symbol):
    cached=load_holdings(symbol)
    if not cached: return True
    try:
        dt=datetime.datetime.fromisoformat(cached.get("updated","").replace("Z",""))
        return (datetime.datetime.utcnow()-dt).days>90
    except: return True

def get_holdings(symbol):
    if not needs_update(symbol):
        cached=load_holdings(symbol)
        if cached and cached.get("tickers"): return cached["tickers"]
    print(f"  {symbol}...",end=" ",flush=True)
    cik=ETF_CIK_MAP.get(symbol)
    if cik:
        h,info=fetch_holdings_edgar(symbol,cik)
        if h:
            save_holdings(symbol,h,"SEC EDGAR N-PORT",info)
            print(f"EDGAR ({len(h)} holdings, {info})")
            return [x["ticker"] for x in h]
        print(f"EDGAR falló ({info}), Yahoo...",end=" ",flush=True)
    h=fetch_holdings_simple(symbol)
    if h:
        save_holdings(symbol,h,"Yahoo Finance")
        print(f"Yahoo ({len(h)} holdings)")
        return [x["ticker"] for x in h]
    fb=ETF_HOLDINGS_FALLBACK.get(symbol,[])
    if fb:
        save_holdings(symbol,[{"ticker":t,"weight_pct":round(100/len(fb),1),"value_usd":None} for t in fb],"fallback")
        print(f"fallback ({len(fb)} holdings)")
        return fb
    print("sin datos"); return []

def main():
    print("Actualizando holdings via SEC EDGAR...")
    os.makedirs(HOLD_DIR,exist_ok=True)
    updated=0; failed=0
    for symbol in ETF_HOLDINGS_FALLBACK:
        tickers=get_holdings(symbol)
        if tickers: updated+=1
        else: failed+=1
        time.sleep(0.5)
    print(f"\nActualizados: {updated} | Fallidos: {failed}\nRESUMEN:")
    for symbol in ETF_HOLDINGS_FALLBACK:
        cached=load_holdings(symbol)
        if cached: print(f"  {symbol:8s} {cached['count']:3d} holdings | {cached['source']:25s} | {cached.get('report_date','?')}")
        else: print(f"  {symbol:8s} sin datos")

if __name__=="__main__":
    main()
