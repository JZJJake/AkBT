import pandas as pd
import numpy as np
import pandas_ta as ta

def generate_mock_data(ticker="000001", start_date="2023-01-01", n_days=500):
    """
    生成模拟A股历史行情数据 (OHLCV) 及技术指标 (MACD, KDJ)。
    剔除周末 (使用 pd.bdate_range 近似模拟交易日历)。

    参数:
        ticker (str): 股票代码
        start_date (str): 开始日期
        n_days (int): 生成天数

    返回:
        pd.DataFrame: 包含 Open, High, Low, Close, Volume, MACD相关, KDJ相关列
    """
    # 生成交易日历 (仅剔除周末，未剔除法定节假日)
    dates = pd.bdate_range(start=start_date, periods=n_days)

    # 随机漫步生成价格序列
    np.random.seed(42) # 固定随机种子以便复现

    start_price = 100.0
    # 日收益率: 正态分布, 均值0, 标准差2%
    returns = np.random.normal(0, 0.02, n_days)
    price_path = start_price * (1 + returns).cumprod()

    data = []
    for i, close_p in enumerate(price_path):
        # 构造 OHLC 数据
        # 开盘价 = 昨日收盘价 * (1 + 随机扰动)
        prev_close = price_path[i-1] if i > 0 else start_price
        open_p = prev_close * (1 + np.random.normal(0, 0.005))

        # 最高价和最低价
        high_p = max(open_p, close_p) * (1 + abs(np.random.normal(0, 0.01)))
        low_p = min(open_p, close_p) * (1 - abs(np.random.normal(0, 0.01)))

        # 成交量: 与价格波动幅度正相关 + 随机噪声
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

    # 计算技术指标 (使用 pandas_ta)

    # MACD (12, 26, 9)
    # 返回列名: MACD_12_26_9 (DIF), MACDh_12_26_9 (Histogram), MACDs_12_26_9 (DEA)
    macd = df.ta.macd(fast=12, slow=26, signal=9)
    df = pd.concat([df, macd], axis=1)

    # 重命名 MACD 列以便后续调用
    df.rename(columns={
        "MACD_12_26_9": "MACD_DIF",
        "MACDh_12_26_9": "MACD_HIST",
        "MACDs_12_26_9": "MACD_DEA"
    }, inplace=True)

    # KDJ (9, 3, 3)
    # pandas_ta.kdj 返回 K_9_3, D_9_3, J_9_3
    kdj = df.ta.kdj(length=9, signal=3)
    df = pd.concat([df, kdj], axis=1)

    # 重命名 KDJ 列
    df.rename(columns={
        "K_9_3": "K",
        "D_9_3": "D",
        "J_9_3": "J"
    }, inplace=True)

    # 填充因指标计算产生的 NaN (首部数据)
    # 为防止绘图报错，这里填充为0，实际回测中应根据策略需求处理 (如 Drop)
    df[['MACD_DIF', 'MACD_HIST', 'MACD_DEA', 'K', 'D', 'J']] = df[['MACD_DIF', 'MACD_HIST', 'MACD_DEA', 'K', 'D', 'J']].fillna(0)

    return df

if __name__ == "__main__":
    # 测试代码
    df = generate_mock_data()
    print(df.tail())
    print(df.columns)
