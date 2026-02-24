from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import asyncio
import uuid
from server.data.mock import generate_mock_data
from server.engine import BacktestEngine
import json

app = FastAPI()

# 存储任务结果 (简易内存存储)
tasks = {}

class BacktestRequest(BaseModel):
    code: str
    start_date: str
    end_date: str
    period: str

@app.post("/api/backtest/run")
async def start_backtest_endpoint(req: BacktestRequest):
    """
    提交回测任务
    """
    task_id = str(uuid.uuid4())
    # 暂存请求参数
    tasks[task_id] = req.model_dump() # req.dict() is deprecated in v2
    return {"task_id": task_id}

@app.websocket("/ws/backtest/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """
    WebSocket 端点：执行回测并推送进度和结果
    """
    await websocket.accept()

    try:
        req = tasks.get(task_id, {})
        # 如果找不到任务，使用默认参数 (方便测试)
        if not req:
             req = {"code": "000001", "start_date": "2023-01-01", "end_date": "2024-01-01", "period": "D"}

        # 1. 生成数据 (Mock)
        await websocket.send_json({"progress": 5, "message": "Generating data..."})

        # 生成数据
        code = req.get('code', '000001')
        start_date = req.get('start_date', '2023-01-01')
        end_date = req.get('end_date', '2024-01-01')

        # 同步生成 Mock 数据
        df = generate_mock_data(ticker=code, start_date=start_date, end_date=end_date)

        if df.empty:
            await websocket.send_json({"error": "No data found"})
            await websocket.close()
            return

        # 2. 初始化引擎
        engine = BacktestEngine(df)

        # 3. 定义进度回调
        async def progress_callback(val):
            # 推送进度
            await websocket.send_json({"progress": val})
            await asyncio.sleep(0.01)

        # 4. 执行回测
        await websocket.send_json({"progress": 10, "message": "Running backtest..."})

        # run 是 async 函数
        result = await engine.run(progress_callback=progress_callback)

        # 5. 推送最终结果
        # result 包含 {bars, trades, equity_curve}
        await websocket.send_json({"progress": 100, "result": result})

        # 清理任务
        if task_id in tasks:
            del tasks[task_id]

        await websocket.close()

    except WebSocketDisconnect:
        print(f"Client disconnected: {task_id}")
    except Exception as e:
        print(f"Error in task {task_id}: {e}")
        try:
            await websocket.send_json({"error": str(e)})
            await websocket.close()
        except:
            pass
