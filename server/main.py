from fastapi import FastAPI, BackgroundTasks
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

@app.get("/data/{code}")
def get_stock_data_api(code: str):
    # 获取数据并返回 JSON (默认从 2020-01-01 开始)
    # 使用 get_stock_data 时，如果 end_date 为 None，provider.py 会尝试获取到最新。
    # 但 provider.py 需要 end_date 字符串比较，所以必须传入。
    end_date = datetime.datetime.now().strftime('%Y-%m-%d')
    start_date = '2020-01-01'

    df = get_stock_data(code, start_date=start_date, end_date=end_date)
    if df.empty:
        return {"error": "No data found"}

    # Calculate Indicators for Frontend Display
    # Use BacktestEngine's logic for consistency
    engine = BacktestEngine(df)
    df = engine.calculate_indicators(df)

    # Handle NaN
    df = df.fillna(0)

    # 转为 JSON (date ISO format)
    # Reset index to include Date column
    # Ensure index name is Date
    if df.index.name != 'Date':
        df.index.name = 'Date'

    df_reset = df.reset_index()

    # Check if Date column exists after reset
    if 'Date' not in df_reset.columns:
         # Fallback: maybe index was unnamed, so it became 'index'
         if 'index' in df_reset.columns:
             df_reset.rename(columns={'index': 'Date'}, inplace=True)

    # Convert timestamp to string
    if 'Date' in df_reset.columns:
        try:
            df_reset['Date'] = df_reset['Date'].dt.strftime('%Y-%m-%d')
        except Exception:
            # Maybe already string?
            df_reset['Date'] = df_reset['Date'].astype(str)

    records = df_reset.to_dict(orient='records')
    return {"code": code, "data": records}

@app.post("/backtest")
async def run_backtest(req: BacktestRequest):
    # 1. Fetch Data
    # provider needs end_date string
    end_date = req.end_date if req.end_date else datetime.datetime.now().strftime('%Y-%m-%d')
    start_date = req.start_date

    df = get_stock_data(req.code, start_date=start_date, end_date=end_date)
    if df.empty:
        return {"error": "No data for backtest"}

    # 2. Initialize Engine
    engine = BacktestEngine(df)
    engine.cash = req.initial_cash

    # 3. Run
    # Progress callback (just print for now, or websocket later)
    async def progress(p):
        print(f"Progress: {p}%")

    result = await engine.run(progress_callback=progress)

    return result

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
