from PySide6.QtCore import QThread, Signal, QObject
import json
import time
import requests
import asyncio
import websockets
import pandas as pd
import io

class BacktestWorker(QThread):
    """
    后台工作线程，用于执行耗时的回测任务（网络请求与数据处理）。
    避免阻塞主 UI 线程。
    """
    # 定义信号
    # progress_updated: 发送当前进度百分比 (int)
    progress_updated = Signal(int)
    # data_received: 发送回测结果 (dict: {bars: df_json, trades: list, equity: list})
    data_received = Signal(dict)
    # error_occurred: 发送错误信息 (str)
    error_occurred = Signal(str)

    def __init__(self, code, start_date, end_date, period, mode='remote'):
        """
        初始化工作线程。

        参数:
            code (str): 股票代码
            start_date (str): 开始日期
            end_date (str): 结束日期
            period (str): 周期
            mode (str): 'remote' (连接服务器)
        """
        super().__init__()
        self.code = code
        self.start_date = start_date
        self.end_date = end_date
        self.period = period
        self.mode = mode
        self.api_base = "http://127.0.0.1:8000"
        self.ws_base = "ws://127.0.0.1:8000"

    def run(self):
        """线程入口点"""
        try:
            # 默认且唯一的模式是 remote
            self.run_remote_backtest()
        except Exception as e:
            self.error_occurred.emit(str(e))

    def run_remote_backtest(self):
        """连接真实的后端 API"""
        # 1. 提交任务 (HTTP POST)
        url = f"{self.api_base}/api/backtest/run"
        payload = {
            "code": self.code,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "period": self.period
        }

        try:
            resp = requests.post(url, json=payload, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            task_id = data.get("task_id")
            if not task_id:
                raise ValueError("Server did not return task_id")
        except Exception as e:
            self.error_occurred.emit(f"Failed to submit task: {str(e)}")
            return

        # 2. 连接 WebSocket (WS)
        ws_url = f"{self.ws_base}/ws/backtest/{task_id}"

        # 由于 QThread.run 是同步的，我们需要运行 asyncio loop 来使用 websockets 库
        # 或者使用阻塞式的 websocket client (如 `websocket-client` 库)，
        # 但为了避免引入新依赖，我们可以用 asyncio.run()

        asyncio.run(self.connect_websocket(ws_url))

    async def connect_websocket(self, url):
        try:
            async with websockets.connect(url) as websocket:
                async for message in websocket:
                    data = json.loads(message)

                    # 处理错误
                    if "error" in data:
                        self.error_occurred.emit(data["error"])
                        break

                    # 处理进度
                    if "progress" in data:
                        progress = data["progress"]
                        self.progress_updated.emit(progress)

                    # 处理结果
                    if "result" in data:
                        result = data["result"]
                        self.data_received.emit(result)

        except Exception as e:
            self.error_occurred.emit(f"WebSocket error: {str(e)}")
