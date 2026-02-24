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

    def get_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票数据 (优先查询数据库，过期或缺失则调用 AkShare 更新)。

        参数:
            code (str): 股票代码
            start_date (str): 回测开始日期
            end_date (str): 回测结束日期

        返回:
            pd.DataFrame
        """
        # 1. 检查数据库中该股票的最新日期
        latest_date_str = self.db_manager.get_latest_date(code)

        need_update = False
        today = datetime.now().date()

        if not latest_date_str:
            # 数据库无数据
            logger.info(f"No data for {code} in DB. Will fetch full history.")
            need_update = True
        else:
            # 数据库有数据，检查是否过期
            # 如果本地最新日期 落后于 昨天 (today - 1 day)
            # 即昨天及之前的数据应该已经收盘并可获取
            latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
            req_end = datetime.strptime(end_date, "%Y-%m-%d").date()

            # 判断逻辑:
            # 1. 本地最新日期 < 昨天 (数据旧)
            if latest_date < (today - timedelta(days=1)):
                 logger.info(f"Data for {code} is stale (latest: {latest_date}). Will fetch update.")
                 need_update = True

            # 2. 请求的结束日期 > 本地最新日期 (范围不够)
            elif req_end > latest_date:
                 logger.info(f"Requested range {end_date} exceeds DB latest date {latest_date}. Will fetch update.")
                 need_update = True

        if need_update:
            # 调用 AkShare 拉取全量数据
            try:
                # fetch_stock_daily 内部包含重试逻辑
                new_df = fetch_stock_daily(code)
                if not new_df.empty:
                    # 全量覆盖保存
                    self.db_manager.save_stock_data(code, new_df)
                else:
                    logger.warning(f"AkShare returned empty data for {code}. Using existing DB data if available.")
            except Exception as e:
                logger.error(f"Failed to update data for {code}: {e}")
                # 发生异常时，尝试使用数据库中的旧数据降级运行 (即便可能不准确/复权不对)

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
