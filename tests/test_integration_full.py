import asyncio
import websockets
import json
import requests
import time
import os
import signal
import subprocess
import sys

# 启动服务器
# 设置 USE_MOCK_FALLBACK=True 以便测试 AkShare 失败后的流程
# 验证数据库是否创建

async def run_test():
    # 删除旧的 db
    if os.path.exists("market_data.db"):
        os.remove("market_data.db")

    env = os.environ.copy()
    env["USE_MOCK_FALLBACK"] = "True"

    server_process = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.main:app", "--port", "8000"],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        # 等待服务器启动
        print("Waiting for server to start...")
        for _ in range(10):
            try:
                requests.get("http://127.0.0.1:8000/docs", timeout=1)
                break
            except requests.exceptions.ConnectionError:
                time.sleep(1)
        else:
            print("Server failed to start.")
            return

        print("Server started. Submitting task...")

        # 1. 提交任务
        url = "http://127.0.0.1:8000/api/backtest/run"
        payload = {
            "code": "000001",
            "start_date": "2023-01-01",
            "end_date": "2023-01-10",
            "period": "D"
        }

        resp = requests.post(url, json=payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        print(f"Task submitted. Task ID: {task_id}")

        # 2. 连接 WebSocket
        ws_url = f"ws://127.0.0.1:8000/ws/backtest/{task_id}"
        print(f"Connecting to WebSocket: {ws_url}")

        async with websockets.connect(ws_url) as websocket:
            while True:
                msg = await websocket.recv()
                data = json.loads(msg)

                if "error" in data:
                    print(f"Server Error: {data['error']}")
                    break

                if "progress" in data:
                    # print(f"Progress: {data['progress']}%")
                    if data["progress"] == 100:
                        if "result" in data:
                            res = data["result"]
                            print("Backtest Result Received!")
                            assert "bars" in res
                            assert len(res['bars']) > 0
                            print("Integration Test Passed!")
                        else:
                             print("Error: Progress 100 but no result found.")
                        break

        # 3. 验证数据库
        if os.path.exists("market_data.db"):
            print("DB file verified.")
            import sqlite3
            conn = sqlite3.connect("market_data.db")
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM stock_daily_qfq WHERE code='000001'")
            cnt = cursor.fetchone()[0]
            print(f"Records in DB for 000001: {cnt}")
            conn.close()
            assert cnt > 0, "DB should contain records"
        else:
            print("Error: DB file not found.")

    except Exception as e:
        print(f"Test Failed: {e}")
    finally:
        print("Stopping server...")
        server_process.terminate()
        server_process.wait()

        if os.path.exists("market_data.db"):
            os.remove("market_data.db")

if __name__ == "__main__":
    asyncio.run(run_test())
