import pandas as pd
from datetime import datetime, timedelta
import logging
from server.data.db_manager import DatabaseManager
from server.data.akshare_fetcher import fetch_stock_daily

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataProvider:
    """
    数据提供层服务。
    封装了数据库查询与 AkShare 外部接口调用。
    """
    def __init__(self, db_path="market_data.db"):
        self.db_manager = DatabaseManager(db_path)
        # Memory Cache for Update Check: {code: timestamp}
        self._last_update_check = {}
        # Update Cooldown (e.g. 4 hours)
        self.UPDATE_COOLDOWN = timedelta(hours=4)

    def get_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票数据 (优先查询数据库，过期或缺失则调用 AkShare 更新)。

        优化：引入内存缓存，避免短时间内重复检查更新。
        """
        # 0. Check Memory Cache (Cooldown)
        now = datetime.now()
        last_check = self._last_update_check.get(code)

        need_db_check = True
        if last_check and (now - last_check) < self.UPDATE_COOLDOWN:
            # Recently updated, skip DB date check and fetch
            logger.debug(f"Skipping update check for {code} (Cached)")
            need_db_check = False

        need_update = False

        if need_db_check:
            # 1. 检查数据库中该股票的最新日期
            latest_date_str = self.db_manager.get_latest_date(code)
            today_date = now.date()

            if not latest_date_str:
                # 数据库无数据
                logger.info(f"No data for {code} in DB. Will fetch full history.")
                need_update = True
            else:
                # 数据库有数据，检查是否过期
                latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
                req_end = datetime.strptime(end_date, "%Y-%m-%d").date()

                # 判断逻辑:
                # 1. 本地最新日期 < 昨天 (数据旧) 且 请求范围覆盖了今天
                #    注意：如果是盘中，AkShare 也许能拿到今天的，但我们通常只关心收盘。
                #    保守策略：只要本地日期比昨天旧，就尝试更新一次。
                if latest_date < (today_date - timedelta(days=1)):
                     logger.info(f"Data for {code} is stale (latest: {latest_date}). Will fetch update.")
                     need_update = True

                # 2. 请求的结束日期 > 本地最新日期 (范围不够)
                elif req_end > latest_date:
                     logger.info(f"Requested range {end_date} exceeds DB latest date {latest_date}. Will fetch update.")
                     need_update = True

        if need_update:
            # 调用 AkShare 拉取全量数据
            try:
                logger.info(f"Fetching online data for {code}...")
                # fetch_stock_daily 内部包含重试逻辑
                new_df = fetch_stock_daily(code)
                if not new_df.empty:
                    # 全量覆盖保存
                    self.db_manager.save_stock_data(code, new_df)
                    # Update cache
                    self._last_update_check[code] = now
                else:
                    logger.warning(f"AkShare returned empty data for {code}. Using existing DB data if available.")
                    # Mark checked even if empty to prevent spamming
                    self._last_update_check[code] = now
            except Exception as e:
                logger.error(f"Failed to update data for {code}: {e}")
                # 发生异常时，尝试使用数据库中的旧数据降级运行

        # 2. 从数据库查询所需时间段的数据
        df = self.db_manager.get_stock_data(code, start_date, end_date)

        if df.empty:
            logger.warning(f"No data available for {code} in range {start_date} - {end_date}")

        return df

# 全局单例
provider = DataProvider()

def get_stock_data(code, start_date, end_date):
    """
    对外暴露的快捷函数
    """
    return provider.get_data(code, start_date, end_date)
