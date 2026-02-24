from PyQt5.QtCore import QThread, pyqtSignal, QObject
import json
import time
import requests
import asyncio
import websockets
import pandas as pd
import io
from typing import List, Union

class BacktestWorker(QThread):
    """
    后台工作线程，用于执行耗时的回测任务（网络请求与数据处理）。
    避免阻塞主 UI 线程。
    """
    # 定义信号 (PyQt5 使用 pyqtSignal)
    progress_updated = pyqtSignal(int)
    data_received = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, codes: Union[str, List[str]], start_date, end_date, period, mode='remote'):
        """
        初始化工作线程。

        参数:
            codes (str or List[str]): 股票代码列表
            start_date (str): 开始日期
            end_date (str): 结束日期
            period (str): 周期
            mode (str): 'remote' (连接服务器)
        """
        super().__init__()
        # Ensure codes is list
        if isinstance(codes, str):
            self.codes = [codes]
        else:
            self.codes = codes

        self.start_date = start_date
        self.end_date = end_date
        self.period = period
        self.mode = mode
        self.api_base = "http://127.0.0.1:8000"
        self.ws_base = "ws://127.0.0.1:8000"

    def run(self):
        """线程入口点"""
        try:
            self.run_remote_backtest()
        except Exception as e:
            self.error_occurred.emit(str(e))

    def run_remote_backtest(self):
        """连接真实的后端 API"""
        # 1. 提交任务 (HTTP POST)
        url = f"{self.api_base}/api/backtest/run"
        payload = {
            "codes": self.codes,
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

        asyncio.run(self.connect_websocket(ws_url))

    async def connect_websocket(self, url):
        try:
            async with websockets.connect(url) as websocket:
                async for message in websocket:
                    data = json.loads(message)

                    if "error" in data:
                        self.error_occurred.emit(data["error"])
                        break

                    if "progress" in data:
                        progress = data["progress"]
                        self.progress_updated.emit(progress)

                    if "result" in data:
                        result = data["result"]
                        self.data_received.emit(result)

        except Exception as e:
            self.error_occurred.emit(f"WebSocket error: {str(e)}")
