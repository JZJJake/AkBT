import requests
import time
import os
import signal
import subprocess
import sys
import unittest
import pandas as pd
import sqlite3

class TestIntegrationSimple(unittest.TestCase):
    def setUp(self):
        # Clean DB
        if os.path.exists("market_data.db"):
            os.remove("market_data.db")

        # Start Server
        self.server_process = subprocess.Popen(
            [sys.executable, "-m", "server.main"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(3) # Wait for startup

    def tearDown(self):
        self.server_process.terminate()
        self.server_process.wait()
        if os.path.exists("market_data.db"):
            os.remove("market_data.db")

    def test_api_and_db(self):
        base_url = "http://127.0.0.1:8000"

        # 1. Fetch Data
        print("Testing GET /data/000001...")
        resp = requests.get(f"{base_url}/data/000001")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("data", data)
        self.assertGreater(len(data["data"]), 0)

        # 2. Verify DB Persistence
        print("Verifying DB Persistence...")
        self.assertTrue(os.path.exists("market_data.db"), "DB file should be created")
        conn = sqlite3.connect("market_data.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stock_daily_qfq WHERE code='000001'")
        cnt = cursor.fetchone()[0]
        conn.close()
        self.assertGreater(cnt, 0, "DB should contain records for 000001")

        # 3. Run Backtest
        print("Testing POST /backtest...")
        payload = {
            "code": "000001",
            "start_date": "2023-01-01",
            "end_date": "2023-02-01",
            "initial_cash": 100000
        }
        resp = requests.post(f"{base_url}/backtest", json=payload)
        self.assertEqual(resp.status_code, 200)
        result = resp.json()
        self.assertIn("equity_curve", result)
        self.assertIn("trades", result)
        print("Backtest result received.")

if __name__ == "__main__":
    unittest.main()
