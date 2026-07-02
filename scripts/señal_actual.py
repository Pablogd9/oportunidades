#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
señal_actual.py — Señal del sistema con scores completos y desempate.

Modelo B1 validado:
  Score principal: momentum 12M skip-1 vol-normalizado percentil propio 5A
  Desempate: factor entrada (distancia al max 52W, invertida, percentil propio)
  Top1: 100% del capital | Sin XBI
"""

import json, math, os, datetime

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE       = os.path.join(ROOT, "data", "cache")
OUT         = os.path.join(ROOT, "data", "señal_actual.json")
TODAY       = datetime.date.today()
WINDOW_YEARS= 5

UNIVERSE = [
    ("SMH","Semiconductores"),("IBB","Biotecnologia"),("ITA","Defensa"),
    ("IGV","Software"),("VHT","Salud"),("PHO","Agua"),
    ("IHI","Salud2"),("ICLN","EnergiaLimpia"),("GRID","Infraestructura"),
    ("COPX","Cobre"),("LIT","Litio"),("INDA","India"),("ROBO","Robotica"),
    ("CIBR","Ciberseguridad"),("PAVE","Infraestructura2"),
]

def load(symbol):
    path=os.path.join(ROOT,"data","cache",f"{symbol.replace('.','-')}.json")
    if os.path.exists(path):
        with open(path) as f: d=json.load(f)
        if d.get("dates") and d.get("prices"): return d["prices"],d["dates"]
    return None,None

def ret_range(p,s,e):
    if abs(s)>=len(p) or abs(e)>=len(p): return None
    p0=p[s]; p1=p[e]
    return (p1/p0-1)*100 if p0>0 else None

def vol_std(p,n=252):
    n=min(n,len(p)-1)
    if n<5: return 20.0
    r=[p[i]/p[i-1]-1 for i in range(len(p)-n,len(p))]
    m=sum(r)/len(r)
    return max(5.0,math.sqrt(sum((x-m)**2 for x in r)/(len(r)-1))*math.sqrt(252)*100)

def pct_hist(v,s):
    if v is None or not s: return 50.0
    return round(sum(1 for x in s if x<=v)/len(s)*100,1)

def momentum_score(prices):
    if not prices or len(prices)<273: return None
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    if n<273: return None
    m=ret_range(pw,-273,-21)
    if m is None: return None
    mn=m/(vol/20.0)
    hist=[]
    for i in range(273,min(n,756)):
        pc=pw[:n-i]
        if len(pc)>=273:
            r=ret_range(pc,-273,-21)
            if r is not None:
                hist.append(r/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return pct_hist(mn,hist)

def entrada_score(prices):
    if not prices or len(prices)<252: return None, None
    wd=WINDOW_YEARS*252
    pw=prices[-wd:] if len(prices)>wd else prices
    n=len(pw); vol=vol_std(pw,min(252,n-1))
    if n<252: return None, None
    max_52w=max(pw[-252:])
    if max_52w<=0: return None, None
    dd=(pw[-1]/max_52w-1)*100
    dd_pct=(1-(pw[-1]/max_52w))*100
    dd_n=dd/(vol/20.0)
    hist=[]
    for i in range(252,min(n,756)):
        pc=pw[:n-i]
        if len(pc)>=252:
            mx=max(pc[-252:])
            if mx>0:
                hist.append(((pc[-1]/mx-1)*100)/(vol_std(pc,min(252,len(pc)-1))/20.0))
    return round(100-pct_hist(dd_n,hist),1), round(dd_pct,1)

def main():
    print("="*70)
    print(f"SEÑAL ACTUAL — {TODAY}")
    print("Modelo B1: momentum 12M skip-1 | Desempate: factor entrada")
    print("="*70)

    resultados=[]
    for sym,sec in UNIVERSE:
        p,d=load(sym)
        if not p or len(p)<273: continue
        ms=momentum_score(p)
        if ms is None: continue
        es,dd=entrada_score(p)
        if es is None: es=50.0; dd=0.0
        resultados.append({
            "sym":sym,"sector":sec,
            "score_momentum":ms,
            "score_entrada":es,
            "distancia_max_pct":dd,
        })

    if not resultados: print("ERROR sin datos"); return

    resultados.sort(key=lambda x:(-x["score_momentum"],-x["score_entrada"]))

    max_mom=resultados[0]["score_momentum"]
    empatados=[r for r in resultados if r["score_momentum"]==max_mom]

    print(f"\n{'Pos':4s} {'ETF':8s} {'Sector':20s} {'Mom':>6} {'Entrada':>8} {'Dist max':>9} {'Nota'}")
    print(f"  {'-'*68}")

    for i,r in enumerate(resultados,1):
        nota=""
        if i==1:
            nota=" ← INVERTIR"
            if len(empatados)>1: nota=" ← INVERTIR (desempate entrada)"
        elif i==2: nota=" ← Top2"
        elif r["score_momentum"]==max_mom: nota=" (empatado)"
        print(f"  {i:3d} {r['sym']:8s} {r['sector']:20s} "
              f"{r['score_momentum']:>6.1f} {r['score_entrada']:>8.1f} "
              f"{r['distancia_max_pct']:>8.1f}%{nota}")

    top1=resultados[0]
    print(f"\n{'='*70}")
    print(f"DECISION: {top1['sym']} ({top1['sector']})")
    print(f"  Score momentum:   {top1['score_momentum']:.1f}/100")
    print(f"  Score entrada:    {top1['score_entrada']:.1f}/100")
    print(f"  Distancia maximo: -{top1['distancia_max_pct']:.1f}% desde max 52W")

    if len(empatados)>1:
        print(f"\n  {len(empatados)} ETFs empatados en momentum={max_mom}")
        print(f"  Ranking por entrada entre empatados:")
        for e in sorted(empatados,key=lambda x:-x["score_entrada"]):
            elegido=" ← elegido" if e["sym"]==top1["sym"] else ""
            print(f"    {e['sym']:8s} entrada={e['score_entrada']:.1f} dist={e['distancia_max_pct']:.1f}%{elegido}")

    print(f"\n  ACCION: €500 en {top1['sym']} este mes")
    print(f"{'='*70}")

    out={"fecha":TODAY.isoformat(),"top1":top1,"ranking":resultados,
         "n_empatados":len(empatados)}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    with open(OUT,"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2)

if __name__=="__main__":
    main()
