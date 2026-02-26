from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn
import pandas as pd
import json
import os
import datetime
from .data.provider import get_stock_data
from .engine import BacktestEngine

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

def resample_data(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """
    Resample daily data to specified period.
    period: 'weekly', 'monthly'
    """
    if df.empty: return df

    # Ensure index is DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    freq_map = {
        'weekly': 'W-FRI',
        'monthly': 'ME'
    }

    if period not in freq_map:
        return df # Return daily if unknown

    freq = freq_map[period]

    # Resample Logic
    resampled = df.resample(freq).agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    })

    # Drop empty periods (e.g. holidays causing empty weeks)
    resampled.dropna(subset=['Close'], inplace=True)

    # Set index name
    resampled.index.name = 'Date'

    return resampled

@app.get("/data/{code}")
def get_stock_data_api(code: str, period: str = Query('daily', regex='^(daily|weekly|monthly)$')):
    # 获取数据并返回 JSON (默认从 2020-01-01 开始)
    end_date = datetime.datetime.now().strftime('%Y-%m-%d')
    start_date = '2020-01-01'

    df = get_stock_data(code, start_date=start_date, end_date=end_date)
    if df.empty:
        return {"error": "No data found"}

    # Resample if needed
    if period != 'daily':
        df = resample_data(df, period)

    # Calculate Indicators for Frontend Display
    engine = BacktestEngine(df)
    df = engine.calculate_indicators(df)

    # Handle NaN
    df = df.fillna(0)

    # Ensure index name is Date
    if df.index.name != 'Date':
        df.index.name = 'Date'

    df_reset = df.reset_index()

    # Check if Date column exists after reset
    if 'Date' not in df_reset.columns:
         if 'index' in df_reset.columns:
             df_reset.rename(columns={'index': 'Date'}, inplace=True)

    # Convert timestamp to string
    if 'Date' in df_reset.columns:
        try:
            df_reset['Date'] = df_reset['Date'].dt.strftime('%Y-%m-%d')
        except Exception:
            df_reset['Date'] = df_reset['Date'].astype(str)

    records = df_reset.to_dict(orient='records')
    return {"code": code, "period": period, "data": records}

@app.post("/backtest")
async def run_backtest(req: BacktestRequest):
    end_date = req.end_date if req.end_date else datetime.datetime.now().strftime('%Y-%m-%d')
    start_date = req.start_date

    df = get_stock_data(req.code, start_date=start_date, end_date=end_date)
    if df.empty:
        return {"error": "No data for backtest"}

    engine = BacktestEngine(df)
    engine.cash = req.initial_cash

    async def progress(p):
        print(f"Progress: {p}%")

    result = await engine.run(progress_callback=progress)

    return result

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
