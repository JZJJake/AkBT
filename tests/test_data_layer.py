import os
import shutil
import logging
import pandas as pd
from server.data.provider import DataProvider
from server.data.db_manager import DatabaseManager

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_data_layer():
    # 使用测试数据库
    test_db = "test_market_data.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    provider = DataProvider(db_path=test_db)

    # 启用 Mock Fallback 以测试完整流程
    os.environ["USE_MOCK_FALLBACK"] = "True"

    code = "000001"
    start_date = "2023-01-01"
    end_date = "2023-01-10"

    try:
        print("--- Test 1: Fetch and Save (Initial) ---")
        # 第一次获取: 数据库为空 -> 触发 AkShare (Mock Fallback) -> 保存 -> 查询
        df = provider.get_data(code, start_date, end_date)

        assert not df.empty, "DataFrame should not be empty"
        assert isinstance(df.index, pd.DatetimeIndex), "Index should be DatetimeIndex"
        print(f"Fetched {len(df)} records.")
        print(df.head())

        # 验证数据库中是否有数据
        db_mgr = DatabaseManager(test_db)
        latest_date = db_mgr.get_latest_date(code)
        assert latest_date is not None, "Latest date should exist in DB"
        print(f"Latest Date in DB: {latest_date}")

        print("\n--- Test 2: Fetch Cached (No Update Needed) ---")
        # 第二次获取: 请求范围在 DB 范围内 (2023-01-01 ~ 2023-01-05) -> 直接读库
        # 为了测试“不更新”，我们将 DB 的 latest_date 修改为“昨天”或更早
        # 但这里的 Mock 数据生成到了 2024-12-31 (akshare_fetcher fallback)
        # 所以 latest_date 应该是 2024-12-31，远大于 today (assuming today is 2026/2025?)
        # 无论如何，如果 latest_date > end_date，且 latest_date >= yesterday，则不更新。

        # 让我们再次请求同样范围
        df_cached = provider.get_data(code, start_date, end_date)
        assert len(df_cached) == len(df), "Cached result should match initial fetch"

        print("\n--- Test 3: Force Update (Delete & Insert) ---")
        # 模拟数据更新: 再次调用 AkShare (Mock Fallback) 并保存
        # 验证是否删除了旧数据 (没有重复键错误)
        # 我们手动调用 db_manager.save_stock_data 来测试 save 逻辑

        # 创建一个新的 Mock DF，稍微不同一点
        new_df = df.copy()
        new_df['Close'] = new_df['Close'] + 100 # 修改数据以便区分

        db_mgr.save_stock_data(code, new_df)

        # 查询验证
        df_updated = db_mgr.get_stock_data(code, start_date, end_date)
        assert df_updated.iloc[0]['Close'] > 100, "Data should be updated"
        print("Update verified.")

    except Exception as e:
        print(f"Test Failed: {e}")
        raise e
    finally:
        # 清理
        if os.path.exists(test_db):
            os.remove(test_db)
        print("\nTest Complete.")

if __name__ == "__main__":
    test_data_layer()
