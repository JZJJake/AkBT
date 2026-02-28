import requests
import time
import subprocess
import sys

proc = subprocess.Popen([sys.executable, "-m", "server.main"])
time.sleep(3)
resp = requests.post("http://127.0.0.1:8000/sync_data")
print("Sync start:", resp.json())
time.sleep(5)
resp = requests.get("http://127.0.0.1:8000/data/000001")
print(resp.json())
proc.terminate()
proc.wait()
