from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import pandas as pd
import json
import os
import datetime
from .data.provider import get_stock_data, trigger_sync, get_sync_progress, provider
from .engine import BacktestEngine
# from .data.akshare_fetcher import fetch_all_stock_codes # Deprecated

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="server/static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse('server/static/index.html')

class BacktestRequest(BaseModel):
    code: str
    start_date: str
    end_date: Optional[str] = None
    initial_cash: float = 100000.0

class ScreenerRequest(BaseModel):
    codes: Optional[List[str]] = None
    target_date: Optional[str] = None

def resample_data(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if df.empty: return df
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    freq_map = {'weekly': 'W-FRI', 'monthly': 'ME'}
    if period not in freq_map: return df

    resampled = df.resample(freq_map[period]).agg({
        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
    })
    resampled.dropna(subset=['Close'], inplace=True)
    resampled.index.name = 'Date'
    return resampled

@app.get("/data/{code}")
def get_stock_data_api(code: str, period: str = Query('daily', regex='^(daily|weekly|monthly)$')):
    end_date = datetime.datetime.now().strftime('%Y-%m-%d')
    start_date = '2020-01-01'

    df = get_stock_data(code, start_date=start_date, end_date=end_date)
    if df.empty: return {"error": "No data found"}

    if period != 'daily': df = resample_data(df, period)

    engine = BacktestEngine(df)
    df = engine.calculate_indicators(df)
    df = df.fillna(0)

    if df.index.name != 'Date': df.index.name = 'Date'
    df_reset = df.reset_index()
    if 'Date' not in df_reset.columns:
         if 'index' in df_reset.columns: df_reset.rename(columns={'index': 'Date'}, inplace=True)
    if 'Date' in df_reset.columns:
        try: df_reset['Date'] = df_reset['Date'].dt.strftime('%Y-%m-%d')
        except: df_reset['Date'] = df_reset['Date'].astype(str)

    records = df_reset.to_dict(orient='records')
    return {"code": code, "period": period, "data": records}

@app.post("/backtest")
async def run_backtest(req: BacktestRequest):
    end_date = req.end_date if req.end_date else datetime.datetime.now().strftime('%Y-%m-%d')
    df = get_stock_data(req.code, start_date=req.start_date, end_date=end_date)
    if df.empty: return {"error": "No data for backtest"}
    engine = BacktestEngine(df)
    engine.cash = req.initial_cash
    result = await engine.run()
    return result

@app.post("/sync_data")
async def api_sync_data():
    """Trigger background data sync"""
    await trigger_sync()
    return {"status": "started"}

@app.get("/sync_status")
def api_sync_status():
    return get_sync_progress()

@app.post("/screener")
async def run_screener(req: ScreenerRequest):
    """
    Screener based on LOCAL DB using Funnel approach.
    """
    # 1. Determine Scope
    if req.codes:
        stock_list = req.codes
    else:
        # Use ALL stocks in DB (assuming sync is done/partial)
        # Or fetch all codes if DB is empty? No, rely on what's available.
        # But user wants "Full Market".
        # Check if DB has data.
        conn = provider.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT code FROM stock_daily_qfq")
        rows = cursor.fetchall()
        stock_list = [r[0] for r in rows]
        conn.close()

        if not stock_list:
            # If DB empty, fallback to default list to avoid empty result
            stock_list = ["000001", "600519", "300059"]

    target_date = req.target_date
    results = []

    # Logic: Monthly -> Weekly -> Daily (Funnel)
    # To do this efficiently, we iterate stocks and check.

    # Pre-fetch range: Need enough history for Monthly MACD
    end_date = datetime.datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.datetime.now() - datetime.timedelta(days=730)).strftime('%Y-%m-%d') # 2 years

    for code in stock_list:
        try:
            # We ONLY query DB here. Screener should be fast.
            df = provider.db_manager.get_stock_data(code, start_date, end_date)
            if df.empty or len(df) < 50: continue

            engine = BacktestEngine(df)

            # Use engine's check_signal logic
            # Refactoring engine to expose check is good, but for now we can rely on `run`
            # `run` computes indicators and signals.
            # Optimization: If we can make `run` skip loop if Monthly fail?
            # Current `run` is full loop.

            # Let's perform a lightweight check here or use `run` (robust).
            res = await engine.run()
            # Parse JSON back to DataFrame is slow.
            # `res['bars']` is a JSON string.
            # Optimization: Just check the last few days of `engine.daily_processed`?
            # Accessing `engine.daily_processed` directly is better if available.
            # But `run` returns a dict.

            bars = pd.read_json(res['bars'], orient='index')
            if not bars.empty and 'buy_signal' in bars.columns:
                # Check LAST row for signal? Or ANY signal in recent range?
                # Screener usually checks "Is it a buy NOW?".
                # So check the last available trading day.
                last_row = bars.iloc[-1]

                # Verify date is recent (within 5 days) to avoid old data signals
                last_date = pd.to_datetime(last_row.name)
                if (datetime.datetime.now() - last_date).days < 10:
                    if last_row['buy_signal']:
                        results.append({
                            "code": code,
                            "date": str(last_row.name).split(' ')[0],
                            "price": last_row['Close']
                        })
        except Exception:
            continue

    return {"count": len(results), "results": results}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
