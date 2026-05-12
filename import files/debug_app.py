"""
Step-by-step debug: run with  python debug_app.py  to see where it fails.
"""
import sys
print("Step 1: sys ok", flush=True)

import os
print("Step 2: os ok", flush=True)

import pandas as pd
print("Step 3: pandas ok", flush=True)

from datetime import datetime
print("Step 4: datetime ok", flush=True)

import numpy as np
print("Step 5: numpy ok", flush=True)

import streamlit as st
print("Step 6: streamlit ok", flush=True)

import yfinance as yf
print("Step 7: yfinance ok", flush=True)

from utils import get_fx_rate, get_price_local, get_prices_batch, get_prices_via_chart_api, _yahoo_session
print("Step 8: utils ok", flush=True)

print("All imports OK. If you see this, run: streamlit run app.py", flush=True)
