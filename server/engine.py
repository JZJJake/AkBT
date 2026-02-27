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
        if len(df) < 30: return df

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

    def check_signal_now(self):
        """
        FAST Screener check (Optimized):
        Calculates indicators on the *entire* available history once,
        then checks the signal condition on the LAST available bar.

        Strategy: Condition 3 (Relaxed)
        - (Daily J turn up < 80) OR (Daily DEA turn up)
        """
        if len(self.raw_data) < 50: return False

        # 1. Calculate Daily Indicators (Vectorized, Fast)
        daily_df = self.calculate_indicators(self.raw_data.copy())

        if len(daily_df) < 3: return False

        # --- Get Last Bars ---
        # Note: 'daily_df' contains ALL history. We check the LAST row.
        # Screener assumes "Today".

        d_curr = daily_df.iloc[-1]
        d_prev = daily_df.iloc[-2]
        d_prev2 = daily_df.iloc[-3]

        # --- Logic: Condition 3 (Relaxed) ---
        # (Daily J turn up & < 80) OR (Daily DEA turn up)

        def get_val(row, key, default=0):
            # Handle potential NaN
            val = row.get(key, default)
            return 0 if pd.isna(val) else val

        # 1. Daily J turn up & < 80
        # J_curr > J_prev AND J_prev <= J_prev2
        j_curr = get_val(d_curr, 'J')
        j_prev = get_val(d_prev, 'J')
        j_prev2 = get_val(d_prev2, 'J')

        d_j_turn_up = (j_curr > j_prev) and (j_prev <= j_prev2)
        d_j_ok = d_j_turn_up and (j_curr < 80)

        # 2. Daily DEA turn up
        # DEA_curr > DEA_prev AND DEA_prev <= DEA_prev2
        dea_curr = get_val(d_curr, 'MACD_DEA')
        dea_prev = get_val(d_prev, 'MACD_DEA')
        dea_prev2 = get_val(d_prev2, 'MACD_DEA')

        d_dea_turn_up = (dea_curr > dea_prev) and (dea_prev <= dea_prev2)

        is_buy = d_j_ok or d_dea_turn_up

        return is_buy

    async def run(self, progress_callback=None):
        """执行回测循环 (Async for WebSocket)"""

        # 1. 计算日线指标 (全量计算，遍历时取值)
        self.daily_processed = self.calculate_indicators(self.raw_data.copy())

        # Fill NaN
        cols_to_fill = ['MACD_DIF', 'MACD_HIST', 'MACD_DEA', 'K', 'D', 'J', 'EMA20']
        for col in cols_to_fill:
            if col in self.daily_processed.columns:
                self.daily_processed[col] = self.daily_processed[col].fillna(0)

        # 添加信号标记列
        self.daily_processed['buy_signal'] = False

        trade_dates = self.daily_processed.index
        total_steps = len(trade_dates)

        # Start after enough data
        start_idx = 50

        for i in range(start_idx, total_steps):
            current_date = trade_dates[i]

            if progress_callback and i % 10 == 0:
                progress = int((i / total_steps) * 100)
                await progress_callback(progress)

            # --- 获取日线数据 ---
            # t (今天), t-1 (昨天)
            d_curr = self.daily_processed.iloc[i]
            d_prev = self.daily_processed.iloc[i-1]
            d_prev2 = self.daily_processed.iloc[i-2]

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

            if len(weekly_df) < 4 or len(monthly_df) < 4: continue

            # 提取最后几行
            w_curr = weekly_df.iloc[-1]
            w_prev = weekly_df.iloc[-2]
            w_prev2 = weekly_df.iloc[-3]
            w_prev3 = weekly_df.iloc[-4]

            m_curr = monthly_df.iloc[-1]
            m_prev = monthly_df.iloc[-2]

            # --- 策略条件判断 ---

            # 辅助: 安全取值
            def get_val(row, key, default=0):
                return row[key] if key in row else default

            # --- 月线条件 ---
            # 1. DIF > DEA
            m_dif_gt_dea = get_val(m_curr, 'MACD_DIF') > get_val(m_curr, 'MACD_DEA')
            # 2. J 向上 (Current > Prev) 且 J < 80
            m_j_up = (get_val(m_curr, 'J') > get_val(m_prev, 'J')) and (get_val(m_curr, 'J') < 80)
            # 3. MACD 柱子红色 (Current > Prev)
            m_hist_red = get_val(m_curr, 'MACD_HIST') > get_val(m_prev, 'MACD_HIST')

            cond_month = m_dif_gt_dea and m_j_up and m_hist_red

            # --- 周线条件 ---
            # 1. DIF > DEA
            w_dif_gt_dea = get_val(w_curr, 'MACD_DIF') > get_val(w_curr, 'MACD_DEA')
            # 2. MACD 柱子红色
            w_hist_red = get_val(w_curr, 'MACD_HIST') > get_val(w_prev, 'MACD_HIST')
            # 3. J < 80 且 (J上拐 OR 上拐后第二周期继续向上)
            # J上拐: t > t-1, t-1 <= t-2
            w_j_turn_up = (get_val(w_curr, 'J') > get_val(w_prev, 'J')) and \
                          (get_val(w_prev, 'J') <= get_val(w_prev2, 'J'))

            # 上拐后第二周期: t > t-1 > t-2, t-2 <= t-3
            w_j_cont_up = (get_val(w_curr, 'J') > get_val(w_prev, 'J')) and \
                          (get_val(w_prev, 'J') > get_val(w_prev2, 'J')) and \
                          (get_val(w_prev2, 'J') <= get_val(w_prev3, 'J'))

            w_j_ok = (get_val(w_curr, 'J') < 80) and (w_j_turn_up or w_j_cont_up)

            cond_week = w_dif_gt_dea and w_hist_red and w_j_ok

            # --- 日线条件 ---
            # 1. J上拐 且 J < 80
            d_j_turn_up = (get_val(d_curr, 'J') > get_val(d_prev, 'J')) and \
                          (get_val(d_prev, 'J') <= get_val(d_prev2, 'J'))
            d_j_ok = d_j_turn_up and (get_val(d_curr, 'J') < 80)

            # 2. MACD 柱子红色
            d_hist_red = get_val(d_curr, 'MACD_HIST') > get_val(d_prev, 'MACD_HIST')

            cond_daily = d_j_ok and d_hist_red

            # --- 综合买入 ---
            # Strict logic: Monthly + Weekly + Daily
            # signal_buy = cond_month and cond_week and cond_daily

            # Relaxed Condition 3 ONLY (per user request: "First select Buy Condition 3, this is most common")
            # Condition 3: (Daily J turn up & < 80) OR (Daily DEA turn up)

            # 1. Daily J turn up & < 80
            d_j_turn_up = (get_val(d_curr, 'J') > get_val(d_prev, 'J')) and \
                          (get_val(d_prev, 'J') <= get_val(d_prev2, 'J'))
            d_j_ok = d_j_turn_up and (get_val(d_curr, 'J') < 80)

            # 2. Daily DEA turn up (Current > Prev > Prev2 ? Or just Current > Prev & Prev <= Prev2)
            d_dea_turn_up = (get_val(d_curr, 'MACD_DEA') > get_val(d_prev, 'MACD_DEA')) and \
                            (get_val(d_prev, 'MACD_DEA') <= get_val(d_prev2, 'MACD_DEA'))

            cond_daily_strict = d_j_ok or d_dea_turn_up

            signal_buy = cond_daily_strict

            # --- 执行交易 ---
            if signal_buy:
                # print(f"[{current_date.date()}] Buy Signal Triggered! Price: {d_curr['Close']}")
                # Mark signal in DataFrame for frontend (Even if not executed due to cash/pos)
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

                    self.trades.append({
                        "action": "buy",
                        "date": str(current_date.date()),
                        "price": price,
                        "reason": "Strategy Signal"
                    })

            # --- 卖出逻辑 (简单止损/止盈) ---
            # 暂时沿用之前的逻辑或简单持有?
            # 用户只定义了买入策略，没详细定义卖出。
            # 沿用之前的: 收盘 < 买入 * 0.97 止损
            # 或者: 日线 MACD 缩小 且 (J高位下拐 或 死叉)

            if self.position == 1:
                should_sell = False
                sell_reason = ""

                # Stop Loss
                if d_curr['Close'] < self.entry_price * 0.97:
                    should_sell = True
                    sell_reason = "Stop Loss"
                else:
                    # Previous Logic: MACD shrink AND (J turn down > 80 OR J < D)
                    macd_shrink = get_val(d_curr, 'MACD_HIST') < get_val(d_prev, 'MACD_HIST')

                    j_turn_down = (get_val(d_curr, 'J') < get_val(d_prev, 'J')) and \
                                  (get_val(d_prev, 'J') >= get_val(d_prev2, 'J'))
                    j_high_turn = j_turn_down and (get_val(d_prev, 'J') > 80)
                    j_cross = get_val(d_curr, 'J') < get_val(d_curr, 'D')

                    if macd_shrink and (j_high_turn or j_cross):
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
