#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor.py — Monitor de cartera y watchlist. RECOPILA datos; NO decide.
Se sube UNA vez y no se vuelve a tocar: toda la configuracion vive en
  data/cartera.json  -> posiciones y bandas
  data/fichas.json   -> empresas (nivel 1 y watchlist), valoracion, KPIs
Salida: MONITOR.md (dashboard) + data/monitor.json (legible desde chat)

Unica regla automatica: el MOTOR del mes (core < minimo -> core;
si no, mayor hueco vs objetivo). La eleccion de EMPRESA dentro del
bloque se decide en conversacion, con los datos y las noticias.
"""
import json, os, ssl, datetime, statistics as st, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, *p)
TODAY = datetime.date.today()

def jload(path, default):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def fetch(sym, rng="1y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
        d = json.load(r)
    res = d["chart"]["result"][0]
    return [c for c in res["indicators"]["quote"][0]["close"] if c], res["meta"].get("currency", "?")

def tec(cl):
    px = cl[-1]; mx = max(cl[-252:]) if len(cl) >= 252 else max(cl)
    rets = [cl[i]/cl[i-1]-1 for i in range(max(1, len(cl)-90), len(cl))]
    return {"px": round(px, 2), "d52": round((px/mx-1)*100, 1),
            "r12": round((px/cl[0]-1)*100, 1) if len(cl) > 200 else None,
            "r3m": round((px/cl[-63]-1)*100, 1) if len(cl) >= 63 else None,
            "vol90": round(st.pstdev(rets)*(252**.5)*100, 1) if len(rets) > 10 else None}

def analiza(nom, f, fx):
    """Devuelve fila con tecnicos + valoracion relativa + flags factuales."""
    try: cl, cur = fetch(f["yahoo"])
    except Exception as e: return {"nombre": nom, "error": str(e), "bloque": f.get("bloque", "?")}
    t = tec(cl); per = desc = None
    if f.get("eps_fwd"):
        per = t["px"]/f["eps_fwd"]
        if cur == "GBp": per /= 100
        per = round(per, 1)
        if f.get("per_med5a"): desc = round((per/f["per_med5a"]-1)*100, 1)
    flags = []
    if desc is not None:
        flags.append("BAJO su mediana" if desc < 0 else "SOBRE su mediana")
        if desc < -40: flags.append("descuento extremo: REVISAR NOTICIAS")
    if t["r3m"] is not None and t["r3m"] < -25: flags.append("cayo >25% en 3m: REVISAR NOTICIAS")
    if t["d52"] > -5: flags.append("en maximos: escalonar entrada")
    for k in f.get("kpis", []):
        v, u, s = k.get("valor"), k.get("umbral"), k.get("sentido", "min")
        if v is not None and u is not None and ((s == "min" and v < u) or (s == "max" and v > u)):
            flags.append(f"TESIS ROTA: {k['nombre']} = {v} (umbral {s} {u})")
    if f.get("conflicto_fuentes"): flags.append("DATOS EN CONFLICTO: verificar antes de comprar")
    return {"nombre": nom, "bloque": f.get("bloque", "?"), "divisa": cur, **t,
            "per": per, "desc": desc, "med5a": f.get("per_med5a"), "kpis": f.get("kpis", []),
            "margenes": f.get("margenes", {}), "balance": f.get("balance", {}),
            "retribucion": f.get("retribucion"), "motor": f.get("motor"),
            "flags": flags, "nota": f.get("nota")}

def main():
    cart = jload(D("data", "cartera.json"), {})
    fich = jload(D("data", "fichas.json"), {})
    bandas = {k: tuple(v) for k, v in cart.get("bandas", {}).items()}
    aport = cart.get("aportacion_mensual", 600)
    nta = cart.get("nta_merlin", 15.99)

    fx = {}
    for p in ["EURUSD=X", "EURGBP=X", "EURHKD=X", "EURCHF=X"]:
        try: fx[p] = fetch(p, "5d")[0][-1]
        except Exception: fx[p] = None
    r = {"USD": fx.get("EURUSD=X") or 1.08, "GBP": fx.get("EURGBP=X") or .86,
         "HKD": fx.get("EURHKD=X") or 8.5, "CHF": fx.get("EURCHF=X") or .94}
    def eur(px, cur):
        if cur == "GBp": return (px/100)/r["GBP"]
        return px/r[cur] if cur in r else px

    # --- cartera ---
    pos, avisos = [], []
    for p in cart.get("positions", []):
        v = None
        if p.get("units") and p.get("yahoo"):
            try:
                cl, cur = fetch(p["yahoo"]); v = p["units"]*eur(cl[-1], cur)
            except Exception as e: avisos.append(f"{p['name']}: {e}")
        if v is None: v = p.get("manual_value_eur", 0.0)
        pos.append({"n": p["name"], "g": p.get("grupo", p["name"]), "v": round(v, 2)})
    total = sum(p["v"] for p in pos) or 1.0
    pesos = {}
    for p in pos: pesos[p["g"]] = pesos.get(p["g"], 0) + p["v"]/total

    # --- motor del mes (unica regla automatica) ---
    core = cart.get("core_grupo", "IWDA")
    w = pesos.get(core, 0); mn_core = bandas.get(core, (.28, .33, .38))[0]
    if w < mn_core:
        motor = (core, f"Core {core} al {w:.1%}, por debajo del minimo {mn_core:.0%}. "
                       f"{aport} EUR integros a {core}.")
    else:
        h = sorted(((g, bandas[g][1]-pesos.get(g, 0)) for g in bandas
                    if g not in cart.get("grupos_congelados", [])), key=lambda x: -x[1])
        motor = (h[0][0], f"Mayor hueco vs objetivo: {h[0][0]} {h[0][1]:+.1%}. "
                          "Empresa concreta: decidir en conversacion con los datos de abajo.")

    n1 = [analiza(n, f, fx) for n, f in fich.get("nivel1", {}).items()]
    wl = [analiza(n, f, fx) for n, f in fich.get("watchlist", {}).items()]
    ok1 = sorted([x for x in n1 if "error" not in x],
                 key=lambda x: (x["desc"] is None, x["desc"] if x["desc"] is not None else 1e9))
    okw = sorted([x for x in wl if "error" not in x],
                 key=lambda x: (x["desc"] is None, x["desc"] if x["desc"] is not None else 1e9))
    fmt = lambda v, s="%+.1f%%": (s % v) if v is not None else "—"

    L = [f"# Monitor — {TODAY}", "", f"## Motor del mes: **{motor[0]}**", motor[1], "",
         "## Cartera vs bandas", "", "| Grupo | Peso | Banda | Estado |", "|---|---|---|---|"]
    for g, (a, o, b) in bandas.items():
        pw = pesos.get(g, 0)
        est = ("CONGELADO (diluir)" if g in cart.get("grupos_congelados", [])
               else "bajo (recibe)" if pw < a else "ALTO (no aportar)" if pw > b else "en banda")
        L.append(f"| {g} | {pw:.1%} | {a:.0%}-{b:.0%} (obj {o:.0%}) | {est} |")
    L += ["", f"**Total: {total:,.0f} EUR**", ""]

    def tabla(rows, titulo):
        out = [f"## {titulo}", "",
               "| Empresa | Bloque | Precio | PER fwd | Med.5a | Desc. | Dist.max | Ret.3m | Ret.12m | Vol90 | Flags |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        for x in rows:
            out.append(f"| {x['nombre']} | {x['bloque']} | {x['px']} {x['divisa']} | {x['per'] or '—'} "
                       f"| {x['med5a'] or '—'} | {fmt(x['desc'])} | {fmt(x['d52'])} | {fmt(x['r3m'])} "
                       f"| {fmt(x['r12'])} | {fmt(x['vol90'],'%.1f%%')} | {'; '.join(x['flags']) or '—'} |")
        return out
    L += tabla(ok1, "Nivel 1 — vigilancia activa (ordenadas por descuento vs SU mediana)")
    L += ["", "*Descuento negativo = cotiza por debajo de su mediana de 5 anos.*", ""]
    L += tabla(okw, "Watchlist — candidatas 5a y 6a plaza")
    L += [""]
    for x in n1 + wl:
        if "error" in x: L.append(f"- ERROR {x['nombre']}: {x['error']}")

    L += ["", "## Fichas de negocio", ""]
    for x in ok1 + okw:
        if not (x["kpis"] or x["margenes"] or x["balance"]): continue
        L.append(f"### {x['nombre']} — {x.get('motor') or ''}")
        for k in x["kpis"]:
            L.append(f"- {k['nombre']}: **{k.get('valor')}** "
                     f"(rompe si {k.get('sentido','min')} {k.get('umbral')}) [{k.get('fecha','?')}]")
        if x["margenes"]: L.append("- Margenes: " + ", ".join(f"{a} {b}" for a, b in x["margenes"].items()))
        if x["balance"]: L.append("- Balance: " + ", ".join(f"{a} {b}" for a, b in x["balance"].items()))
        if x.get("retribucion"): L.append(f"- Retribucion: {x['retribucion']}")
        if x["nota"]: L.append(f"- Nota: {x['nota']}")
        L.append("")

    L += ["## Merlin — veto de NAV", ""]
    try:
        cl, _ = fetch("MRL.MC"); mpx = cl[-1]; dsc = (1-mpx/nta)*100
        L.append(f"- {mpx:.2f} EUR vs NTA {nta} -> descuento {dsc:+.1f}% "
                 f"({'comprable (>10%)' if dsc > 10 else 'NO comprable'})")
    except Exception: L.append("- MRL.MC no disponible")
    if avisos: L += ["", "## Avisos", ""] + [f"- {a}" for a in avisos]
    L += ["", "## Mantenimiento", "",
          "- TRIMESTRAL: eps_fwd, KPIs, margenes y balance en `data/fichas.json`",
          "- ANUAL: per_med5a | SEMESTRAL: nta_merlin en `data/cartera.json`",
          "- Tras cada compra: actualizar `data/cartera.json`",
          "- Fuente unica acordada: stockanalysis.com",
          "", f"*Generado {TODAY}. El sistema recopila; la decision se toma en conversacion.*"]

    with open(D("MONITOR.md"), "w", encoding="utf-8") as f: f.write("\n".join(L))
    os.makedirs(D("data"), exist_ok=True)
    with open(D("data", "monitor.json"), "w", encoding="utf-8") as f:
        json.dump({"fecha": TODAY.isoformat(), "total": round(total, 2),
                   "pesos": {k: round(v, 4) for k, v in pesos.items()},
                   "motor": motor[0], "motivo": motor[1],
                   "nivel1": ok1, "watchlist": okw, "avisos": avisos}, f, ensure_ascii=False, indent=2)
    print(f"OK | total {total:,.0f} EUR | motor: {motor[0]} | n1={len(ok1)} wl={len(okw)}")

if __name__ == "__main__": main()
