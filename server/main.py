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
from .screener_manager import screener_manager
import asyncio

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

    name = provider.db_manager.get_stock_name(code)
    records = df_reset.to_dict(orient='records')
    return {"code": code, "name": name, "period": period, "data": records}

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
async def run_screener():
    """
    Trigger the background screener task.
    """
    asyncio.create_task(screener_manager.run_task())
    return {"status": "started", "message": "Screener started in background."}

@app.get("/screener_status")
def get_screener_status():
    """
    Get progress of the screener.
    """
    return {
        "status": screener_manager.status,
        "progress": screener_manager.progress,
        "current_stock": screener_manager.current_stock,
        "processed": screener_manager.processed_count,
        "total": screener_manager.total_stocks,
        "message": screener_manager.message,
        "results": screener_manager.found_stocks
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
