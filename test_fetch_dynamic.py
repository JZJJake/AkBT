import time
from server.data.tdx_fetcher import tdx_fetcher

tdx_fetcher.connect()
bars = []
start = 0
count = 0
while True:
    b = tdx_fetcher.api.get_security_bars(9, 0, '002826', start, 800)
    print(f"Batch {count}, length: {len(b) if b else 0}, start: {start}")
    if not b: break
    bars = b + bars
    start += len(b)
    count += 1
    if len(b) < 800: break

print(f"Total bars fetched: {len(bars)}")
tdx_fetcher.disconnect()
