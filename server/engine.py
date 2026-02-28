import pandas as pd
import numpy as np
import pandas_ta as ta

class BacktestEngine:
    def __init__(self, data_feed):
        """
        初始化回测引擎。

        参数:
            data_feed (pd.DataFrame): 包含 Open, High, Low, Close, Volume 的历史数据，索引为 DatetimeIndex。
        """
        self.raw_data = data_feed.copy()

        # 交易记录
        self.trades = []
        self.equity_curve = []

        # 状态机
        self.position = 0 # 0: 空仓, 1: 持仓
        self.shares = 0
        self.entry_price = 0.0
        self.entry_date = None
        self.cash = 100000.0 # 初始资金

        # 策略参数
        self.macd_fast = 10
        self.macd_slow = 25
        self.macd_signal = 7
        self.kdj_length = 9
        self.kdj_signal = 3

        # 结果缓存
        self.daily_processed = None

    def calculate_indicators(self, df):
        """计算 MACD, KDJ, EMA 指标"""
        if len(df) < 10: return df

        # EMA 20
        try:
            ema20 = df.ta.ema(length=20)
            if ema20 is not None:
                df['EMA20'] = ema20
        except Exception:
            pass

        # MACD
        try:
            macd = df.ta.macd(fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
            if macd is not None:
                # pandas_ta columns: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
                rename_dict = {}
                for col in macd.columns:
                    if col.startswith('MACDh'): rename_dict[col] = 'MACD_HIST'
                    elif col.startswith('MACDs'): rename_dict[col] = 'MACD_DEA'
                    elif col.startswith('MACD'): rename_dict[col] = 'MACD_DIF'
                macd = macd.rename(columns=rename_dict)
                df = pd.concat([df, macd], axis=1)
        except Exception:
            pass

        # KDJ
        try:
            kdj = df.ta.kdj(length=self.kdj_length, signal=self.kdj_signal)
            if kdj is not None:
                 # K_9_3, D_9_3, J_9_3
                 rename_dict = {}
                 for col in kdj.columns:
                     if col.startswith('K'): rename_dict[col] = 'K'
                     elif col.startswith('D'): rename_dict[col] = 'D'
                     elif col.startswith('J'): rename_dict[col] = 'J'
                 kdj = kdj.rename(columns=rename_dict)
                 df = pd.concat([df, kdj], axis=1)
        except Exception:
            pass

        return df

    def get_dynamic_period_data(self, current_date, raw_df, freq):
        """
        构造包含“历史静态数据”+“当前未收盘动态数据”的 DataFrame。
        """
        # 截取截至 current_date 的日线
        daily_slice = raw_df.loc[:current_date].copy()
        if daily_slice.empty: return pd.DataFrame()

        # Resample
        resampled = daily_slice.resample(freq).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        })

        # Drop empty periods
        resampled.dropna(subset=['Close'], inplace=True)
        return resampled

    def calculate_slope_xl(self, j_series):
        """
        Calculate XL slope based on user formula:
        DXL = IF(J > REF(J,1), REF(DXL,1), J)
        XL = (J - REF(J,1)) / DXL
        """
        if len(j_series) < 2:
            return pd.Series([0]*len(j_series), index=j_series.index)

        j_values = j_series.values
        dxl = np.zeros_like(j_values, dtype=float)
        xl = np.zeros_like(j_values, dtype=float)

        # Init
        dxl[0] = float(j_values[0])
        xl[0] = 0

        for i in range(1, len(j_values)):
            j_curr = j_values[i]
            j_prev = j_values[i-1]

            if j_curr > j_prev:
                dxl[i] = dxl[i-1]
            else:
                dxl[i] = j_curr

            denom = dxl[i]
            if abs(denom) < 1e-9: # Avoid div by zero
                xl[i] = 0
            else:
                xl[i] = (j_curr - j_prev) / denom

        return pd.Series(xl, index=j_series.index)

    def check_signal_now(self):
        """
        FAST Screener check:
        Strategy: Cond 1 (Monthly) AND Cond 2 (Weekly) AND Cond 3 (Daily)
        """
        if len(self.raw_data) < 50: return False

        def get_val(row, key, default=0):
            val = row.get(key, default)
            return 0 if pd.isna(val) else val

        # --- 1. Daily Indicators ---
        daily_df = self.calculate_indicators(self.raw_data.copy())
        if len(daily_df) < 3: return False

        d_curr = daily_df.iloc[-1]
        d_prev = daily_df.iloc[-2]
        d_prev2 = daily_df.iloc[-3]

        # --- Condition 3: Daily Reversal ---
        # j值上拐且j值小于80
        j_curr = get_val(d_curr, 'J')
        j_prev = get_val(d_prev, 'J')
        j_prev2 = get_val(d_prev2, 'J')
        d_j_turn_up = (j_curr > j_prev) and (j_prev <= j_prev2)
        # macd 柱子值大于前一柱子值
        d_hist_up = get_val(d_curr, 'MACD_HIST') > get_val(d_prev, 'MACD_HIST')

        cond3 = d_j_turn_up and (j_curr < 80) and d_hist_up

        if not cond3: return False

        # --- Condition 2: Weekly Trend ---
        weekly_df = self.raw_data.resample('W-FRI').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        })
        weekly_df.dropna(subset=['Close'], inplace=True)
        weekly_df = self.calculate_indicators(weekly_df)

        if len(weekly_df) < 3 or 'J' not in weekly_df.columns or 'MACD_DIF' not in weekly_df.columns:
            return False

        w_curr = weekly_df.iloc[-1]
        w_prev = weekly_df.iloc[-2]

        # macd的快线在慢线上方
        w_dif_gt_dea = get_val(w_curr, 'MACD_DIF') > get_val(w_curr, 'MACD_DEA')
        # kdj的J线向上
        w_j_up = get_val(w_curr, 'J') > get_val(w_prev, 'J')
        # macd柱子值大于前一柱子值
        w_hist_up = get_val(w_curr, 'MACD_HIST') > get_val(w_prev, 'MACD_HIST')

        cond2 = w_dif_gt_dea and w_j_up and w_hist_up

        if not cond2: return False

        # --- Condition 1: Monthly Trend ---
        monthly_df = self.raw_data.resample('ME').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        })
        monthly_df.dropna(subset=['Close'], inplace=True)
        monthly_df = self.calculate_indicators(monthly_df)

        if len(monthly_df) < 3 or 'J' not in monthly_df.columns or 'MACD_DIF' not in monthly_df.columns:
            # If monthly data is insufficient, strategy fails strict check
            return False

        m_curr = monthly_df.iloc[-1]
        m_prev = monthly_df.iloc[-2]

        # 1. DIF > DEA
        m_dif_gt_dea = get_val(m_curr, 'MACD_DIF') > get_val(m_curr, 'MACD_DEA')
        # 2. Hist > Prev Hist
        m_hist_up = get_val(m_curr, 'MACD_HIST') > get_val(m_prev, 'MACD_HIST')
        # 3. J Up
        m_j_up = get_val(m_curr, 'J') > get_val(m_prev, 'J')

        cond1 = m_dif_gt_dea and m_hist_up and m_j_up

        return cond1

    async def run(self, progress_callback=None):
        """执行回测循环 (Async for WebSocket)"""

        # 1. 计算日线指标 (全量计算，遍历时取值)
        self.daily_processed = self.calculate_indicators(self.raw_data.copy()); self.daily_processed = self.daily_processed.loc[:, ~self.daily_processed.columns.duplicated()]

        # Calculate Daily XL Slope for Sell Logic
        if 'J' in self.daily_processed.columns:
            xl_series = self.calculate_slope_xl(self.daily_processed['J'])
            self.daily_processed['XL'] = xl_series
        else:
            self.daily_processed['XL'] = 0.0

        # Fill NaN
        cols_to_fill = ['MACD_DIF', 'MACD_HIST', 'MACD_DEA', 'K', 'D', 'J', 'EMA20', 'XL']
        for col in cols_to_fill:
            if col in self.daily_processed.columns:
                self.daily_processed[col] = self.daily_processed[col].fillna(0)

        # 添加信号标记列
        self.daily_processed['buy_signal'] = False

        trade_dates = self.daily_processed.index
        total_steps = len(trade_dates)

        # Start after enough data
        start_idx = 50

        def get_val(row, key, default=0):
            return row[key] if key in row else default

        for i in range(start_idx, total_steps):
            current_date = trade_dates[i]

            if progress_callback and i % 10 == 0:
                progress = int((i / total_steps) * 100)
                await progress_callback(progress)

            # --- 获取日线数据 ---
            d_curr = self.daily_processed.iloc[i]
            d_prev = self.daily_processed.iloc[i-1]
            d_prev2 = self.daily_processed.iloc[i-2]

            signal_buy = False

            # --- 动态计算周/月线 ---
            lookback = 100 # Optimize speed

            # 周线 (Weekly)
            weekly_df = self.get_dynamic_period_data(current_date, self.raw_data, 'W-FRI')
            if len(weekly_df) > lookback: weekly_df = weekly_df.iloc[-lookback:]
            weekly_df = self.calculate_indicators(weekly_df)

            # 月线 (Monthly)
            monthly_df = self.get_dynamic_period_data(current_date, self.raw_data, 'ME')
            if len(monthly_df) > lookback: monthly_df = monthly_df.iloc[-lookback:]
            monthly_df = self.calculate_indicators(monthly_df)

            if len(weekly_df) < 3 or 'J' not in weekly_df.columns:
                continue
            if len(monthly_df) < 3 or 'J' not in monthly_df.columns:
                continue

            # 提取最后几行
            w_curr = weekly_df.iloc[-1]
            w_prev = weekly_df.iloc[-2]

            m_curr = monthly_df.iloc[-1]
            m_prev = monthly_df.iloc[-2]

            # --- Condition 3: Daily Reversal ---
            # j值上拐且j值小于80
            j_curr = get_val(d_curr, 'J')
            j_prev = get_val(d_prev, 'J')
            j_prev2 = get_val(d_prev2, 'J')
            d_j_turn_up = (j_curr > j_prev) and (j_prev <= j_prev2)
            # macd 柱子值大于前一柱子值
            d_hist_up = get_val(d_curr, 'MACD_HIST') > get_val(d_prev, 'MACD_HIST')

            cond3 = d_j_turn_up and (j_curr < 80) and d_hist_up

            if cond3:
                # --- Condition 2: Weekly Trend ---
                # macd的快线在慢线上方
                w_dif_gt_dea = get_val(w_curr, 'MACD_DIF') > get_val(w_curr, 'MACD_DEA')
                # kdj的J线向上
                w_j_up = get_val(w_curr, 'J') > get_val(w_prev, 'J')
                # macd柱子值大于前一柱子值
                w_hist_up = get_val(w_curr, 'MACD_HIST') > get_val(w_prev, 'MACD_HIST')

                cond2 = w_dif_gt_dea and w_j_up and w_hist_up

                if cond2:
                    # --- Condition 1: Monthly Trend ---
                    # macd的快线在慢线上方
                    m_dif_gt_dea = get_val(m_curr, 'MACD_DIF') > get_val(m_curr, 'MACD_DEA')
                    # kdj的J线向上且小于80
                    m_j_up = get_val(m_curr, 'J') > get_val(m_prev, 'J')
                    m_j_lt_80 = get_val(m_curr, 'J') < 80
                    # macd柱子值大于前一柱子值
                    m_hist_up = get_val(m_curr, 'MACD_HIST') > get_val(m_prev, 'MACD_HIST')

                    cond1 = m_dif_gt_dea and m_j_up and m_j_lt_80 and m_hist_up

                    # Combined (Strict AND)
                    signal_buy = cond1 and cond2 and cond3

            # --- 执行交易 ---
            if signal_buy:
                self.daily_processed.at[current_date, 'buy_signal'] = True

            if signal_buy and self.position == 0:
                price = d_curr['Close']
                shares_can_buy = int(self.cash // (price * 100)) * 100
                if shares_can_buy > 0:
                    cost = shares_can_buy * price
                    self.shares = shares_can_buy
                    self.cash -= cost
                    self.position = 1
                    self.entry_price = price
                    self.entry_date = current_date
                    self.entry_xl = get_val(d_curr, 'XL')

                    self.trades.append({
                        "action": "buy",
                        "date": str(current_date.date()),
                        "price": price,
                        "reason": "Strategy Signal"
                    })

            # --- 卖出逻辑 ---
            if self.position == 1:
                should_sell = False
                sell_reason = ""

                # Stop Loss
                if d_curr['Close'] < self.entry_price * 0.97:
                    should_sell = True
                    sell_reason = "Stop Loss"
                else:
                    # Signal Sell: 日线下kdj的j值上升斜率低于买入时j值斜率的80%，则卖出
                    xl_curr = get_val(d_curr, 'XL')
                    if xl_curr < self.entry_xl * 0.8:
                        should_sell = True
                        sell_reason = "Signal Sell"

                if should_sell:
                    price = d_curr['Close']
                    revenue = self.shares * price
                    self.cash += revenue
                    self.shares = 0
                    self.position = 0

                    self.trades.append({
                        "action": "sell",
                        "date": str(current_date.date()),
                        "price": price,
                        "reason": sell_reason
                    })

            # Record Equity
            equity = self.cash
            if self.position == 1:
                equity += self.shares * d_curr['Close']

            self.equity_curve.append({
                "date": str(current_date.date()),
                "value": equity
            })

        return {
            "bars": self.daily_processed.to_json(orient='index', date_format='iso'),
            "trades": self.trades,
            "equity_curve": self.equity_curve
        }
