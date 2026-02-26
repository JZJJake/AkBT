import pandas as pd
from datetime import datetime, timedelta
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from server.data.db_manager import DatabaseManager
# Replace AkShare with TDX
from server.data.tdx_fetcher import fetch_stock_daily_tdx, fetch_all_stock_codes_tdx

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataProvider:
    """
    数据提供层服务。
    封装了数据库查询与外部接口调用 (TDX)。
    """
    def __init__(self, db_path="market_data.db"):
        self.db_manager = DatabaseManager(db_path)
        self._last_update_check = {}
        self.UPDATE_COOLDOWN = timedelta(hours=4)
        # Background task state
        self._sync_status = {"status": "idle", "progress": 0, "total": 0, "message": ""}

    def get_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票数据 (优先查询数据库，过期或缺失则调用 TDX 更新)。
        """
        now = datetime.now()
        last_check = self._last_update_check.get(code)

        need_db_check = True
        if last_check and (now - last_check) < self.UPDATE_COOLDOWN:
            logger.debug(f"Skipping update check for {code} (Cached)")
            need_db_check = False

        need_update = False

        if need_db_check:
            latest_date_str = self.db_manager.get_latest_date(code)
            today_date = now.date()

            if not latest_date_str:
                logger.info(f"No data for {code} in DB. Will fetch full history.")
                need_update = True
            else:
                latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
                req_end = datetime.strptime(end_date, "%Y-%m-%d").date()

                # Check stale (yesterday)
                if latest_date < (today_date - timedelta(days=1)):
                     # Optimization: Check if today is trading day? Assume yes for simplicity.
                     logger.info(f"Data for {code} is stale (latest: {latest_date}). Will fetch update.")
                     need_update = True
                elif req_end > latest_date:
                     logger.info(f"Requested range {end_date} exceeds DB latest date {latest_date}. Will fetch update.")
                     need_update = True

        if need_update:
            try:
                logger.info(f"Fetching online data for {code} (TDX)...")
                # TDX Fetcher returns all history usually, or we can filter inside but upsert handles it
                new_df = fetch_stock_daily_tdx(code)
                if not new_df.empty:
                    self.db_manager.save_stock_data(code, new_df)
                    self._last_update_check[code] = now
                else:
                    logger.warning(f"TDX returned empty data for {code}.")
                    self._last_update_check[code] = now
            except Exception as e:
                logger.error(f"Failed to update data for {code}: {e}")

        return self.db_manager.get_stock_data(code, start_date, end_date)

    async def _fetch_and_update_single(self, code, loop):
        """Helper for async fetch"""
        try:
            # Run blocking TDX fetch in executor
            await loop.run_in_executor(None, self.get_data, code, "2020-01-01", datetime.now().strftime('%Y-%m-%d'))
            return True
        except Exception as e:
            logger.error(f"Error syncing {code}: {e}")
            return False

    async def sync_all_stocks_task(self):
        """
        后台任务：同步全市场数据 (使用 TDX 高速接口)
        """
        if self._sync_status["status"] == "running":
            return

        self._sync_status = {"status": "running", "progress": 0, "total": 0, "message": "Fetching stock list (TDX)..."}

        try:
            # 1. Get List via TDX
            loop = asyncio.get_event_loop()
            codes = await loop.run_in_executor(None, fetch_all_stock_codes_tdx)

            if not codes:
                raise Exception("Failed to fetch stock list from TDX.")

            self._sync_status["total"] = len(codes)

            # 2. Iterate
            # TDX is fast, but we still use concurrency.
            # Connection pooling might be needed? TdxFetcher manages single connection.
            # Multithreading on single TdxHq_API instance might be thread-unsafe or blocked.
            # Best practice: Use a semaphore to limit concurrency, and maybe create new instances if needed?
            # Or just sequential is fast enough?
            # Sequential TDX: ~20ms per stock -> 5000 stocks = 100s. Very fast.
            # Let's try concurrency=10 with the shared instance (pytdx is blocking socket).
            # Actually, standard pytdx client is synchronous.
            # We can use ThreadPoolExecutor to run multiple clients?
            # For simplicity and stability, let's keep concurrency low (e.g. 4) or sequential if it's fast enough.
            # 5000 * 0.05s = 250s = 4 min. Acceptable.

            sem = asyncio.Semaphore(4)

            async def bound_fetch(code):
                async with sem:
                    await self._fetch_and_update_single(code, loop)

            batch_size = 50
            processed = 0

            for i in range(0, len(codes), batch_size):
                batch = codes[i:i+batch_size]
                self._sync_status["message"] = f"Processing batch {i}-{i+len(batch)} / {len(codes)}"

                tasks = [bound_fetch(code) for code in batch]
                await asyncio.gather(*tasks)

                processed += len(batch)
                self._sync_status["progress"] = int((processed / len(codes)) * 100)

                # No sleep needed for TDX usually

            self._sync_status["status"] = "completed"
            self._sync_status["message"] = f"Sync completed. Processed {processed} stocks."

        except Exception as e:
            self._sync_status["status"] = "error"
            self._sync_status["message"] = str(e)
            logger.error(f"Sync task failed: {e}")

    def get_sync_status(self):
        return self._sync_status

# 全局单例
provider = DataProvider()

def get_stock_data(code, start_date, end_date):
    return provider.get_data(code, start_date, end_date)

async def trigger_sync():
    asyncio.create_task(provider.sync_all_stocks_task())
    return {"status": "started"}

def get_sync_progress():
    return provider.get_sync_status()
