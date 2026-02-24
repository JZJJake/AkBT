import pandas as pd
import numpy as np
import pandas_ta as ta

def generate_mock_data(ticker="000001", start_date="2023-01-01", end_date="2024-01-01"):
    """
    生成模拟A股历史行情数据 (OHLCV)。
    仅生成基础 OHLCV，不在此处计算指标 (指标由回测引擎计算)。

    参数:
        ticker (str): 股票代码
        start_date (str): 开始日期
        end_date (str): 结束日期

    返回:
        pd.DataFrame: 包含 Open, High, Low, Close, Volume
    """
    # 生成交易日历 (剔除周末)
    dates = pd.bdate_range(start=start_date, end=end_date)
    n_days = len(dates)

    # 随机漫步生成价格序列
    np.random.seed(42) # 固定随机种子

    start_price = 100.0
    # 日收益率: 正态分布, 均值0, 标准差2%
    returns = np.random.normal(0, 0.02, n_days)
    price_path = start_price * (1 + returns).cumprod()

    data = []
    for i, close_p in enumerate(price_path):
        prev_close = price_path[i-1] if i > 0 else start_price
        open_p = prev_close * (1 + np.random.normal(0, 0.005))

        high_p = max(open_p, close_p) * (1 + abs(np.random.normal(0, 0.01)))
        low_p = min(open_p, close_p) * (1 - abs(np.random.normal(0, 0.01)))

        # 成交量
        vol_base = 100000
        vol_noise = np.random.randint(0, 50000)
        vol_spike = 1 + abs(returns[i]) * 10
        volume = int((vol_base + vol_noise) * vol_spike)

        data.append({
            "Date": dates[i],
            "Open": open_p,
            "High": high_p,
            "Low": low_p,
            "Close": close_p,
            "Volume": volume
        })

    df = pd.DataFrame(data)
    df.set_index("Date", inplace=True)

    return df
