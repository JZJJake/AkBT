from pytdx.hq import TdxHq_API
import pandas as pd
import datetime
import time
import logging

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TdxFetcher:
    def __init__(self):
        self.api = TdxHq_API(heartbeat=True)
        self.connected = False
        # Best IPs (Standard TDX IPs)
        self.hosts = [
            {'ip': '119.147.212.81', 'port': 7709},
            {'ip': '119.147.212.82', 'port': 7709},
            {'ip': '202.108.23.153', 'port': 7709},
            {'ip': '124.160.88.183', 'port': 7709},
            {'ip': '123.125.108.14', 'port': 7709}
        ]

    def connect(self):
        if self.connected:
            return True

        for host in self.hosts:
            try:
                if self.api.connect(host['ip'], host['port']):
                    logger.info(f"Connected to TDX server: {host['ip']}")
                    self.connected = True
                    return True
            except Exception as e:
                logger.warning(f"Failed to connect to {host['ip']}: {e}")
                continue

        logger.error("Failed to connect to any TDX server.")
        return False

    def disconnect(self):
        if self.connected:
            self.api.disconnect()
            self.connected = False

    def fetch_stock_list(self):
        """
        获取全市场股票列表 (仅A股)
        """
        if not self.connect(): return []

        stocks = []
        # TDX market codes: 0=SZ, 1=SH
        for market in [0, 1]:
            # Get count first (approx 3000 each to be safe)
            # Actually get_security_count is simpler but get_security_list fetches in batches of 1000
            start = 0
            while True:
                data = self.api.get_security_list(market, start)
                if not data: break

                for item in data:
                    code = item['code']
                    # Filter for A-shares:
                    # SH: 60xxxx, 688xxx
                    # SZ: 00xxxx, 30xxxx
                    if market == 1 and (code.startswith('60') or code.startswith('68')):
                        stocks.append(code)
                    elif market == 0 and (code.startswith('00') or code.startswith('30')):
                        stocks.append(code)

                start += len(data)
                if len(data) < 1000: break

        logger.info(f"Fetched {len(stocks)} A-share stocks via TDX.")
        return stocks

    def fetch_daily_bars(self, code):
        """
        获取日线数据 (未复权)
        """
        if not self.connect(): return pd.DataFrame()

        market = 1 if code.startswith(('6', '5')) else 0 # 5 for ETF/Fund? User focused on stocks
        if code.startswith(('0', '3')): market = 0
        if code.startswith(('6', '68')): market = 1

        # Fetch in batches (800 per request)
        data = []
        start = 0

        # Max history: 5 years roughly 1200 days. Let's fetch 3 batches (2400 days)
        for i in range(5):
            bars = self.api.get_security_bars(9, market, code, start, 800) # 9 = Daily
            if not bars: break
            data = bars + data # Prepend older data
            start += len(bars)
            if len(bars) < 800: break

        if not data: return pd.DataFrame()

        df = self.api.to_df(data)
        # Columns: open, close, high, low, vol, amount, datetime
        # Rename to match system
        col_map = {
            'datetime': 'Date', 'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close', 'vol': 'Volume', 'amount': 'Amount'
        }
        df.rename(columns=col_map, inplace=True)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)

        # Handle TDX Volume units (TDX vol is usually shares, check if needed /100)
        # Usually raw TDX vol is in 'lots' or shares.
        # Standard: volume is shares. AkShare stock_zh_a_hist is shares.
        # TDX usually returns volume in shares (not lots) for index, but let's verify.
        # Observation: TDX 'vol' is often in 'hand' (100 shares) or just shares depending on version.
        # pytdx documentation says: vol is成交量.

        return df

    def fetch_xdxr_info(self, code):
        """
        获取除权除息信息
        """
        if not self.connect(): return pd.DataFrame()

        market = 1 if code.startswith(('6', '68')) else 0
        xdxr = self.api.get_xdxr_info(market, code)
        if not xdxr: return pd.DataFrame()

        return self.api.to_df(xdxr)

    def to_qfq(self, code, df):
        """
        执行前复权 (QFQ)
        算法:
        复权因子 = (前复权价格 / 原始价格)
        Calculation based on XDXR info:
        Simpler approach: Calculate accumulative factor from latest back to past.
        """
        if df.empty: return df

        xdxr = self.fetch_xdxr_info(code)
        if xdxr.empty:
            return df # No split/div info, raw is same as qfq

        # Ensure dates
        xdxr['date'] = pd.to_datetime(xdxr[['year', 'month', 'day']])
        xdxr = xdxr.sort_values('date', ascending=False) # Recent first

        # Calculate Factor for each day
        # Initialize factor column
        df['factor'] = 1.0

        # Iterate XDXR to apply adjustments
        # fenhong: Cash dividend per 10 shares
        # songzhuangu: Bonus shares per 10 shares
        # peigu: Rights issue (ignore price change for simplicity or complex calc?)
        #   Standard QFQ: NewP = (OldP - Dividend + RightsIssue) / (1 + BonusRatio + RightsRatio)
        #   Factor = NewP / OldP

        # Standard Algorithm:
        # Start from latest date, factor = 1.
        # Go backwards. If hit XDXR date, update cumulative factor.

        # But applying to DataFrame efficiently:
        # 1. Map XDXR to dates
        # 2. Iterate dataframe?

        # Implementation adapted from quant libraries
        df.sort_index(ascending=True, inplace=True)

        # Prepare adjust table
        # We need to adjust 'Open', 'High', 'Low', 'Close'

        # Make a copy to avoid SettingWithCopy
        adj_df = df.copy()

        # Iterate rows is slow. Use vectorization if possible.
        # But xdxr events are sparse.

        for _, row in xdxr.iterrows():
            date = row['date']
            if date > adj_df.index.max(): continue # Future event

            # Events apply to data BEFORE the ex-date
            mask = adj_df.index < date
            if not mask.any(): continue

            # Calculate adjust factor for this specific event
            # Forward Adjust (Hou Fu Quan) is simpler multiplication.
            # Backward Adjust (Qian Fu Quan):
            # Price_adj = (Price_raw - Dividend) / (1 + ShareSplit)
            # But we are applying this to historical data.
            # So, for data BEFORE ex_date:
            # P_adj = (P_raw - DivPerShare) / (1 + SplitRatio)
            # Actually, standard QFQ means "Current price is real".

            # Extract info
            # fenhong is per 10 shares
            cash_div = row['fenhong'] / 10.0 if row['fenhong'] else 0.0
            # songzhuangu is per 10 shares
            share_split = row['songzhuangu'] / 10.0 if row['songzhuangu'] else 0.0

            # Apply to Open, High, Low, Close
            # Note: For strict QFQ, (P - Cash) / (1 + Ratio)
            # If P - Cash < 0? (Rare)

            # We apply this adjustment to all records BEFORE this date.
            # If multiple events, we apply sequentially (since we iterate from recent to old in XDXR?)
            # Wait, if we iterate Recent XDXR first:
            # Event 2024: Adjust 2023 and before.
            # Event 2023: Adjust 2022 and before.
            # Yes, cumulative application works.

            cols = ['Open', 'High', 'Low', 'Close']
            for col in cols:
                adj_df.loc[mask, col] = (adj_df.loc[mask, col] - cash_div) / (1 + share_split)

        return adj_df

# Global Instance
tdx_fetcher = TdxFetcher()

def fetch_stock_daily_tdx(code, start_date=None, end_date=None):
    """
    Unified interface for provider.py
    """
    try:
        df = tdx_fetcher.fetch_daily_bars(code)
        if df.empty: return df

        # Apply QFQ
        df = tdx_fetcher.to_qfq(code, df)

        # Filter Date Range (Optional, DB manager handles it, but good to trim)
        if start_date:
            df = df[df.index >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df.index <= pd.to_datetime(end_date)]

        return df
    except Exception as e:
        logger.error(f"TDX Error for {code}: {e}")
        return pd.DataFrame()

def fetch_all_stock_codes_tdx():
    return tdx_fetcher.fetch_stock_list()
