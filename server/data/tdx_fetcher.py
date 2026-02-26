from pytdx.hq import TdxHq_API
import pandas as pd
import datetime
import time
import logging
import threading

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TdxFetcher:
    def __init__(self):
        self.api = TdxHq_API(heartbeat=True)
        self.connected = False
        self.lock = threading.Lock()

        # Comprehensive list of TDX servers
        self.hosts = [
            ("上证云北京联通一", "123.125.108.14", 7709),
            ("深圳电信主站Z1", "14.17.75.71", 7709),
            ("招商证券深圳行情", "119.147.212.81", 7709),
            ("上证云成都电信一", "218.6.170.47", 7709),
            ("上海电信主站Z1", "180.153.18.170", 7709),
            ("上海电信主站Z2", "180.153.18.171", 7709),
            ("北京联通主站Z1", "202.108.253.130", 7709),
            ("杭州电信主站J1", "60.191.117.167", 7709),
            ("杭州电信主站J2", "115.238.56.198", 7709),
            ("杭州联通主站J1", "124.160.88.183", 7709),
            ("杭州华数主站J1", "218.108.98.244", 7709),
            ("青岛联通主站W1", "218.57.11.101", 7709),
            ("云行情上海电信Z1", "114.80.63.12", 7709),
            ("华泰证券(南京电信)", "221.231.141.60", 7709),
            ("华泰证券(上海电信)", "101.227.73.20", 7709),
            ("国泰君安", "113.105.92.100", 7709),
            ("海通", "123.125.108.90", 7709),
        ]

    def connect(self):
        """
        Thread-safe connection logic.
        Should be called within a lock or managed carefully.
        But since we use one connection, we lock around usage.
        The connect check needs to be fast.
        """
        if self.connected:
            return True

        # Note: We do NOT lock the entire loop, but we need to ensure only one thread connects.
        # But this method is called by methods already protected by self.lock?
        # Yes, if we implement it that way.

        for name, ip, port in self.hosts:
            try:
                # Use a short timeout for connection attempts
                if self.api.connect(ip, port, time_out=2):
                    logger.info(f"Connected to TDX server: {name} ({ip})")
                    self.connected = True
                    return True
            except Exception as e:
                # logger.debug(f"Failed to connect to {name}: {e}")
                continue

        logger.error("Failed to connect to any TDX server.")
        return False

    def disconnect(self):
        with self.lock:
            if self.connected:
                self.api.disconnect()
                self.connected = False

    def fetch_stock_list(self):
        """
        Fetches stock list from TDX.
        Note: Often partial (Market 1 missing on many servers).
        Use stock_list_provider.py for full list.
        """
        with self.lock:
            if not self.connect(): return []

            stocks = []
            try:
                for market in [0, 1]:
                    start = 0
                    while True:
                        data = self.api.get_security_list(market, start)
                        if not data: break

                        for item in data:
                            code = item['code']
                            if market == 1 and (code.startswith('60') or code.startswith('68')):
                                stocks.append(code)
                            elif market == 0 and (code.startswith('00') or code.startswith('30')):
                                stocks.append(code)

                        start += len(data)
                        if len(data) < 1000: break
            except Exception as e:
                logger.error(f"TDX fetch_stock_list error: {e}")
                self.connected = False # Force reconnect next time

            return stocks

    def fetch_daily_bars(self, code):
        """
        Thread-safe fetch of daily bars.
        """
        with self.lock:
            if not self.connect(): return pd.DataFrame()

            market = 1 if code.startswith(('6', '5')) else 0
            if code.startswith(('0', '3')): market = 0
            if code.startswith(('6', '68')): market = 1

            try:
                data = []
                start = 0
                # Fetch up to 5 batches (approx 4-5 years)
                for i in range(5):
                    bars = self.api.get_security_bars(9, market, code, start, 800)
                    if not bars: break
                    data = bars + data
                    start += len(bars)
                    if len(bars) < 800: break

                if not data: return pd.DataFrame()

                df = self.api.to_df(data)
                col_map = {
                    'datetime': 'Date', 'open': 'Open', 'high': 'High',
                    'low': 'Low', 'close': 'Close', 'vol': 'Volume', 'amount': 'Amount'
                }
                df.rename(columns=col_map, inplace=True)
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
                return df

            except Exception as e:
                logger.error(f"TDX fetch_daily_bars error for {code}: {e}")
                self.connected = False
                return pd.DataFrame()

    def fetch_xdxr_info(self, code):
        """
        Thread-safe fetch of XDXR info.
        """
        with self.lock:
            if not self.connect(): return pd.DataFrame()

            market = 1 if code.startswith(('6', '68')) else 0
            try:
                xdxr = self.api.get_xdxr_info(market, code)
                if not xdxr: return pd.DataFrame()
                return self.api.to_df(xdxr)
            except Exception as e:
                logger.error(f"TDX fetch_xdxr_info error for {code}: {e}")
                self.connected = False
                return pd.DataFrame()

    def to_qfq(self, code, df):
        """
        Executes QFQ (Forward Adjust) logic.
        Fetches XDXR info (uses lock internally) and applies adjustment.
        """
        if df.empty: return df

        # This calls fetch_xdxr_info which uses lock.
        # So we don't need to lock here, unless to_qfq itself modifies shared state (it doesn't).
        xdxr = self.fetch_xdxr_info(code)

        if xdxr.empty:
            return df

        # Ensure dates
        xdxr['date'] = pd.to_datetime(xdxr[['year', 'month', 'day']])
        xdxr = xdxr.sort_values('date', ascending=False)

        df['factor'] = 1.0
        df.sort_index(ascending=True, inplace=True)
        adj_df = df.copy()

        for _, row in xdxr.iterrows():
            date = row['date']
            if date > adj_df.index.max(): continue

            mask = adj_df.index < date
            if not mask.any(): continue

            cash_div = row['fenhong'] / 10.0 if row['fenhong'] else 0.0
            share_split = row['songzhuangu'] / 10.0 if row['songzhuangu'] else 0.0

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
