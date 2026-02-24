from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import asyncio
import uuid
# from server.data.mock import generate_mock_data # Removed mock data import
from server.data.provider import get_stock_data
from server.data.market import get_all_stock_codes
from server.engine import BacktestEngine
import json
import os
import concurrent.futures
import pandas as pd
import logging
from typing import List, Optional

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()

# 存储任务结果 (简易内存存储)
tasks = {}

# 进程池 (Global)
# Windows下需注意 spawn/fork，Linux下默认 fork。
executor = concurrent.futures.ProcessPoolExecutor(max_workers=4)

class BacktestRequest(BaseModel):
    codes: List[str] # 改为列表支持多股
    start_date: str
    end_date: str
    period: str

@app.get("/api/market/stocks")
async def get_stocks():
    """获取全市场股票列表"""
    return get_all_stock_codes()

@app.post("/api/backtest/run")
async def start_backtest_endpoint(req: BacktestRequest):
    """
    提交回测任务
    """
    task_id = str(uuid.uuid4())
    tasks[task_id] = req.model_dump()
    return {"task_id": task_id}

# 辅助函数：单个回测任务 (必须是顶层函数以便 pickle)
def run_single_backtest(code, start_date, end_date, initial_cash):
    # 子进程中独立获取数据 (只读)
    from server.data.provider import get_stock_data
    from server.engine import BacktestEngine
    import asyncio

    try:
        # DB 读取 (数据已由主进程准备好)
        df = get_stock_data(code, start_date, end_date)
        if df.empty:
            return None

        engine = BacktestEngine(df)
        engine.cash = initial_cash # 分配资金

        # 运行回测 (同步 run, 因为是在子进程中)
        # 临时将 engine.run 改为同步调用或者 run_until_complete
        # 注意: engine.run 本身定义为 async，但在子进程里我们需要同步执行直到完成
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(engine.run())
        loop.close()

        # 附加 code 到结果中
        if result:
            result['code'] = code
            # 将 trades 中的每条记录加上 code
            for t in result.get('trades', []):
                t['code'] = code

            return result

    except Exception as e:
        logger.error(f"Error in subprocess for {code}: {e}")
        return None

@app.websocket("/ws/backtest/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """
    WebSocket 端点：执行回测并推送进度和结果
    """
    await websocket.accept()

    try:
        req = tasks.get(task_id, {})
        if not req:
             req = {"codes": ["000001"], "start_date": "2023-01-01", "end_date": "2024-01-01", "period": "D"}

        codes = req.get('codes', [])
        if not codes:
            codes = ["000001"]

        # 支持 "ALL" 关键字 (全市场回测)
        if "ALL" in codes:
            all_stocks = get_all_stock_codes()
            codes = [s['code'] for s in all_stocks]
            # 限制一下全市场数量以免沙箱崩溃? 比如前 10 只用于测试
            if len(codes) > 50:
                 codes = codes[:50] # Limit for demo/sandbox safety

        start_date = req.get('start_date', '2023-01-01')
        end_date = req.get('end_date', '2024-01-01')

        total_stocks = len(codes)

        # --- 阶段 1: 数据准备 (串行/并发 I/O) ---
        await websocket.send_json({"progress": 0, "message": f"Preparing data for {total_stocks} stocks..."})

        valid_codes = []
        for i, code in enumerate(codes):
            try:
                # 主进程负责写操作 (DataProvider 会检查并拉取数据存入 SQLite)
                # get_stock_data(code, start_date, end_date)
                # 优化: 我们可以只检查 update，不把整个 df 读出来 (get_data reads all)
                # 但 DataProvider 目前设计是 get_data 触发 update。
                # 简单起见，调用 get_stock_data 并丢弃返回值，只利用副作用 (update DB)
                df = get_stock_data(code, start_date, end_date)
                if not df.empty:
                    valid_codes.append(code)

                # Report progress periodically
                if i % 5 == 0 or i == total_stocks - 1:
                     pct = int((i / total_stocks) * 30) # 0% -> 30%
                     await websocket.send_json({"progress": pct})
                     await asyncio.sleep(0.01) # Yield
            except Exception as e:
                logger.error(f"Data prep failed for {code}: {e}")

        if not valid_codes:
            await websocket.send_json({"error": "No valid data found for any stock"})
            await websocket.close()
            return

        # --- 阶段 2: 并发回测 (CPU 密集) ---
        await websocket.send_json({"progress": 30, "message": "Running backtest logic..."})

        initial_cash_per_stock = 1_000_000.0 / len(valid_codes)

        loop = asyncio.get_running_loop()
        futures = []

        for code in valid_codes:
            f = loop.run_in_executor(executor, run_single_backtest, code, start_date, end_date, initial_cash_per_stock)
            futures.append(f)

        results = []
        completed = 0
        total_futures = len(futures)

        if total_futures == 0:
             await websocket.send_json({"error": "No tasks created"})
             await websocket.close()
             return

        # 等待结果并更新进度
        # asyncio.as_completed yields futures as they complete
        for f in asyncio.as_completed(futures):
            try:
                res = await f
                if res:
                    results.append(res)
            except Exception as e:
                logger.error(f"Backtest task failed: {e}")

            completed += 1
            # Progress 30% -> 90%
            pct = 30 + int((completed / total_futures) * 60)
            await websocket.send_json({"progress": pct})

        # --- 阶段 3: 结果聚合 ---
        await websocket.send_json({"progress": 95, "message": "Aggregating results..."})

        all_trades = []
        equity_series_list = []

        # 收集数据
        # 统一时间轴: 找出所有结果中日期的并集
        all_dates = set()

        for res in results:
            if 'trades' in res:
                all_trades.extend(res['trades'])

            if 'equity_curve' in res and res['equity_curve']:
                # List of dict [{'date': '...', 'value': ...}]
                df_ec = pd.DataFrame(res['equity_curve'])
                df_ec['date'] = pd.to_datetime(df_ec['date'])
                df_ec.set_index('date', inplace=True)
                # Series name = code
                s = df_ec['value']
                s.name = res.get('code', 'UNKNOWN')
                equity_series_list.append(s)

        # 聚合资金曲线
        equity_curve_final = []
        if equity_series_list:
            # Join all series on date index
            # outer join ensures all dates are present
            df_equity_all = pd.concat(equity_series_list, axis=1)
            df_equity_all.sort_index(inplace=True)

            # Forward fill: handle suspensions (stock value remains same as last close)
            # Before ffill, fill initial NaNs with initial_cash (before entry)
            # Or assume if NaN at start, value is initial_cash.
            df_equity_all.fillna(method='ffill', inplace=True)
            df_equity_all.fillna(initial_cash_per_stock, inplace=True)
            # If still NaN (e.g. stock listed late), it should be initial cash (cash held)
            # Wait, if stock not listed, we hold cash.

            total_equity = df_equity_all.sum(axis=1)

            equity_curve_final = [{"date": d.strftime('%Y-%m-%d'), "value": v} for d, v in total_equity.items()]

        # Bars 数据
        final_bars = None
        if len(valid_codes) == 1 and results:
             final_bars = results[0].get('bars')
        else:
             # 多股模式下可以返回空，或者第一只的 bars
             # 需求: "完全不返回 bars 数据... C 端主图区域应直接清空"
             final_bars = None

        final_result = {
            "bars": final_bars,
            "trades": all_trades,
            "equity_curve": equity_curve_final
        }

        await websocket.send_json({"progress": 100, "result": final_result})

        if task_id in tasks:
            del tasks[task_id]

        await websocket.close()

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {task_id}")
    except Exception as e:
        logger.error(f"Error in websocket handler: {e}")
        try:
            await websocket.send_json({"error": str(e)})
            await websocket.close()
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    if "USE_MOCK_FALLBACK" not in os.environ:
         os.environ["USE_MOCK_FALLBACK"] = "True"
    uvicorn.run(app, host="127.0.0.1", port=8000)
