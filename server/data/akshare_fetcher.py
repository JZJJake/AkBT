import akshare as ak
import pandas as pd
import time
import random
import logging
import os
from typing import Optional
from server.data.mock import generate_mock_data

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_stock_daily(code: str) -> pd.DataFrame:
    """
    调用 AkShare 获取指定股票的全量历史日线数据 (前复权)。
    如果配置了 USE_MOCK_FALLBACK=True，当网络请求失败耗尽重试次数后，将返回 Mock 数据。

    参数:
        code (str): 股票代码 (6位数字)

    返回:
        pd.DataFrame: 包含 'Date', 'Open', 'High', 'Low', 'Close', 'Volume' 且索引为 DatetimeIndex
    """
    max_retries = 3
    use_mock_fallback = os.environ.get("USE_MOCK_FALLBACK", "False").lower() == "true"

    # 1. 尝试标准化代码格式
    if '.' in code:
        symbol = code.split('.')[0]
    else:
        symbol = code

    last_exception = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Fetching data for {symbol}, attempt {attempt}/{max_retries}...")

            # 2. 调用 AkShare 接口
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date="19900101",
                end_date="20991231",
                adjust="qfq"
            )

            if df is None or df.empty:
                logger.warning(f"No data returned for {symbol}")
                return pd.DataFrame()

            # 3. 清洗数据
            rename_map = {
                "日期": "Date",
                "开盘": "Open",
                "收盘": "Close",
                "最高": "High",
                "最低": "Low",
                "成交量": "Volume"
            }
            # 仅保留存在的列
            existing_cols = [c for c in rename_map.keys() if c in df.columns]
            if not existing_cols:
                logger.error(f"Unexpected columns from AkShare: {df.columns}")
                raise ValueError("Invalid data format from AkShare")

            df.rename(columns=rename_map, inplace=True)

            # 确保包含核心字段
            required_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
            for col in required_cols:
                if col not in df.columns:
                     logger.warning(f"Missing column {col} in data for {symbol}")
                     return pd.DataFrame()

            df = df[required_cols].copy()

            # 4. 转换类型
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            df.sort_index(inplace=True)

            # 确保数值类型
            cols_numeric = ["Open", "High", "Low", "Close", "Volume"]
            for col in cols_numeric:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            logger.info(f"Successfully fetched {len(df)} records for {symbol}")
            return df

        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            last_exception = e

            if attempt < max_retries:
                # 随机退避: 2 + random(0, 2) 秒
                sleep_time = 2 + random.uniform(0, 2)
                logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
            else:
                logger.error(f"Failed to fetch {symbol} after {max_retries} attempts.")

    # 重试耗尽后检查是否启用 Mock 降级
    if use_mock_fallback:
        logger.warning(f"Using Mock Data Fallback for {symbol} due to fetch failure.")
        # 生成 Mock 数据 (默认 2023-2024，这里稍微放宽一点)
        try:
            mock_df = generate_mock_data(ticker=symbol, start_date="2020-01-01", end_date="2024-12-31")
            return mock_df
        except Exception as mock_e:
            logger.error(f"Mock generation also failed: {mock_e}")
            raise last_exception if last_exception else mock_e
    else:
        # 未启用 Mock，抛出原始异常
        if last_exception:
            raise last_exception
        return pd.DataFrame()

if __name__ == "__main__":
    # 测试
    try:
        # 设置 Mock 开关以测试降级
        os.environ["USE_MOCK_FALLBACK"] = "True"
        df = fetch_stock_daily("000001")
        if not df.empty:
            print("Fetch Success (possibly Mock):")
            print(df.tail())
            print(df.info())
        else:
            print("Fetch returned empty DataFrame.")
    except Exception as e:
        print(f"Test failed with exception: {e}")
