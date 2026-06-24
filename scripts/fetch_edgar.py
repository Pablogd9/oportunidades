#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_cache.py — Descarga y mantiene el cache de datos historicos.

Primera ejecucion: descarga historico maximo (rng=max) de todos los ETFs.
Ejecuciones posteriores: solo descarga los dias nuevos.
"""

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
    {"id":"XBI",  "symbol":"XBI",     "name":"SPDR S&P Biotech ETF",              "sector":"Biotecnologia",   "use":"backtest+scan", "inception":"2006-02-06", "aum_bn":6.4},
    {"id":"IHI",  "symbol":"IHI",     "name":"iShares US Medical Devices ETF",     "sector":"Salud",           "use":"backtest+scan", "inception":"2006-05-01", "aum_bn":4.1},
    {"id":"ICLN",
