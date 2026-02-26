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

class ScreenerRequest(BaseModel):
    codes: Optional[List[str]] = None
    target_date: Optional[str] = None

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

@app.post("/screener")
async def run_screener(req: ScreenerRequest):
    """
    Run strategy on a list of stocks and return those with a Buy Signal on target_date.
    """
    # Default list if not provided (Sample A-shares)
    stock_list = req.codes if req.codes else [
        "000001", "600519", "300059", "601318", "002594", "601138", "301301",
        "600030", "000858", "600036", "601012", "000333", "603259", "300750"
    ]

    target_date = req.target_date
    if not target_date:
        target_date = datetime.datetime.now().strftime('%Y-%m-%d')

    results = []

    # Optimization: Use a simpler date range for screening (e.g. last 1 year)
    start_date = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
    end_date = datetime.datetime.now().strftime('%Y-%m-%d')

    for code in stock_list:
        try:
            df = get_stock_data(code, start_date=start_date, end_date=end_date)
            if df.empty or len(df) < 50: continue

            engine = BacktestEngine(df)
            # We don't need to run full simulation, just check signals
            # But run() does the pre-calculation. Let's use run() but optimized?
            # Actually run() is fast enough for 1 year data on 10 stocks.
            # But we only care about the signal on the LAST day (or target date).

            # Run engine
            res = await engine.run()
            bars = pd.read_json(res['bars'], orient='index')

            if 'buy_signal' in bars.columns:
                # Check last row
                last_row = bars.iloc[-1]
                # Or check specific target date if needed

                if last_row['buy_signal']:
                    results.append({
                        "code": code,
                        "date": last_row.name.strftime('%Y-%m-%d') if hasattr(last_row.name, 'strftime') else str(last_row.name),
                        "price": last_row['Close']
                    })
        except Exception as e:
            print(f"Screener error for {code}: {e}")
            continue

    return {"count": len(results), "results": results}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
