@echo off
echo [Server] Starting Backtest API Server (Debug Mode)...
:: 若需连接 AkShare 获取真实A股数据，请将下方变量改为 False
set USE_MOCK_FALLBACK=True
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
pause
