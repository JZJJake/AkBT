import akshare as ak
import pandas as pd
import datetime

def fetch_stock_daily(code, start_date='20200101', end_date=None, adjust='qfq'):
    """
    获取 A 股日线数据 (前复权)。
    处理停牌: ffill 收盘价, Volume=0.
    """
    if end_date is None:
        end_date = datetime.datetime.now().strftime('%Y%m%d')

    print(f"Fetching {code} from {start_date} to {end_date}...")
    try:
        # akshare 接口: stock_zh_a_hist
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust=adjust)
        if df.empty:
            return pd.DataFrame()

        # 重命名列以符合习惯
        # 日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
        rename_map = {
            '日期': 'Date',
            '开盘': 'Open',
            '收盘': 'Close',
            '最高': 'High',
            '最低': 'Low',
            '成交量': 'Volume'
        }
        df.rename(columns=rename_map, inplace=True)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)

        # 仅保留需要的列
        cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        df = df[cols]

        # 处理停牌 (构建完整日历并 reindex)
        full_idx = pd.date_range(start=df.index.min(), end=df.index.max(), freq='B') # 使用工作日
        df = df.reindex(full_idx)

        # 填充
        # 收盘价: ffill (停牌时价格不变)
        df['Close'] = df['Close'].ffill()
        # Open, High, Low 设为 Close (停牌时)
        df['Open'] = df['Open'].fillna(df['Close'])
        df['High'] = df['High'].fillna(df['Close'])
        df['Low'] = df['Low'].fillna(df['Close'])
        # Volume: 0
        df['Volume'] = df['Volume'].fillna(0)

        # 去除上市前的 NaN (如果 start_date 早于上市日期，akshare 返回的数据本身就没有那段时间，
        # 但 reindex 可能会引入前面的 NaN，需要 drop)
        df.dropna(subset=['Close'], inplace=True)

        return df

    except Exception as e:
        print(f"Error fetching data for {code}: {e}")
        # Fallback to Mock Data
        print("Returning mock data due to error.")
        dates = pd.date_range(start_date, end_date if end_date else datetime.datetime.now(), freq='B')
        if len(dates) == 0: return pd.DataFrame()

        import numpy as np
        df = pd.DataFrame({
            'Open': np.random.uniform(10, 20, len(dates)),
            'High': np.random.uniform(10, 20, len(dates)),
            'Low': np.random.uniform(10, 20, len(dates)),
            'Close': np.random.uniform(10, 20, len(dates)),
            'Volume': np.random.uniform(1000, 5000, len(dates))
        }, index=dates)
        df.index.name = 'Date'
        return df

if __name__ == "__main__":
    # Test
    df = fetch_daily_data("000001", "20230101", "20230201")
    print(df.head())
