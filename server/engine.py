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

        # 预计算静态的周线和月线历史数据 (完全已收盘的历史周期)
        # resample('W-FRI'): 周五作为周结束
        # closed='right', label='right' (默认): (t-1, t]
        # 注意: 我们需要确保数据不包含未来。Resample 后索引通常是周期结束日。

        # 预先计算所有静态周线数据?
        # 实际上，如果我们在每一步只根据"截至当日"的数据来生成周线，是最安全的。
        # 预计算可以优化，但必须小心。
        # 这里为了严谨防前瞻，我们每一步动态生成。

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
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        self.kdj_length = 9
        self.kdj_signal = 3

        # 结果缓存
        self.daily_processed = None

    def calculate_indicators(self, df):
        """计算 MACD 和 KDJ 指标"""
        if len(df) < 30: return df

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
                # Ensure no duplicate columns if called multiple times (though we work on copy)
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

        参数:
            current_date: 当前回测日期 (Timestamp)
            raw_df: 原始日线数据 (截断至 current_date)
            freq: 'W-FRI' or 'M'
        """
        # 截取截至 current_date 的日线
        daily_slice = raw_df.loc[:current_date].copy()
        if daily_slice.empty: return pd.DataFrame()

        # Resample
        # closed='right', label='right' by default for M/W
        # 这会自动把日线聚合。
        # 最后一行即为包含 current_date 的周期 (可能未收盘，但在回测视角下就是当前的形态)
        resampled = daily_slice.resample(freq).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        })

        # 过滤掉未来的 (resample 可能会生成以周期结束日为索引的行，即使该结束日 > current_date)
        # 例如 current_date 是周三(2023-01-04)，周期结束日是周五(2023-01-06)。
        # Pandas resample 会把这一行标记为 2023-01-06。这是允许的，表示"截至本周的K线"。
        # 但我们需要确保这个 "2023-01-06" 行只包含了截至 2023-01-04 的数据。
        # 上面的 .agg() 是基于 daily_slice 的，所以它是正确的动态K线。

        return resampled

    async def run(self, progress_callback=None):
        """执行回测循环 (Async for WebSocket)"""

        # 1. 预计算日线指标 (用于C端展示，同时也用于日线级别的策略判断)
        # 这里的指标是基于全量历史计算的“静态”指标。
        # 在遍历时取 loc[current_date] 是安全的防前瞻 (因为 current_date 的指标只依赖过去)
        # 只要我们不取 loc[current_date + 1] 即可。
        # 修正: 严格来说，current_date 的指标应该基于 loc[:current_date] 计算。
        # 但日线指标通常只依赖过去 N 天。静态计算结果与动态计算结果在 current_date 是一致的。
        # 唯独 "MACD 缩小/放大" 需要比较 t 与 t-1。

        self.daily_processed = self.calculate_indicators(self.raw_data.copy())

        # 填充 NaN 以防计算报错
        cols_to_fill = ['MACD_DIF', 'MACD_HIST', 'MACD_DEA', 'K', 'D', 'J']
        for col in cols_to_fill:
            if col in self.daily_processed.columns:
                self.daily_processed[col] = self.daily_processed[col].fillna(0)

        trade_dates = self.daily_processed.index
        total_steps = len(trade_dates)

        # 跳过初始数据不足阶段 (例如前30天指标无效)
        start_idx = 30

        for i in range(start_idx, total_steps):
            current_date = trade_dates[i]

            # 进度回调
            if progress_callback and i % 5 == 0:
                progress = int((i / total_steps) * 100)
                await progress_callback(progress)

            # --- 获取日线数据 ---
            daily_row = self.daily_processed.loc[current_date]

            # 获取前两天的数据用于判断拐点 (t-1, t-2)
            d_row_1 = self.daily_processed.iloc[i-1]
            d_row_2 = self.daily_processed.iloc[i-2]

            # --- 动态合成周/月线并计算指标 ---
            # 性能优化: 只取最近 N 条历史来计算指标
            lookback = 100

            # 截取 raw_df
            # Optimization: pass raw_df slice
            # Or use optimized method

            # 周线
            weekly_full = self.get_dynamic_period_data(current_date, self.raw_data, 'W-FRI')
            if len(weekly_full) > lookback:
                w_window = weekly_full.iloc[-lookback:].copy()
            else:
                w_window = weekly_full.copy()

            w_window = self.calculate_indicators(w_window)
            if len(w_window) < 3: continue

            curr_w = w_window.iloc[-1]
            prev_w = w_window.iloc[-2]
            prev_w2 = w_window.iloc[-3]

            # 月线
            monthly_full = self.get_dynamic_period_data(current_date, self.raw_data, 'ME') # 'ME' is Month End
            if len(monthly_full) > lookback:
                m_window = monthly_full.iloc[-lookback:].copy()
            else:
                m_window = monthly_full.copy()

            m_window = self.calculate_indicators(m_window)
            if len(m_window) < 3: continue

            curr_m = m_window.iloc[-1]
            prev_m = m_window.iloc[-2]
            prev_m2 = m_window.iloc[-3]

            # --- 策略逻辑判断 ---

            # 辅助函数
            def is_macd_growing(c, p1, p2):
                # MACD 柱子绝对递增 (Histogram)
                # 假设字段存在且非 NaN
                try:
                    return (c['MACD_HIST'] > p1['MACD_HIST']) and (p1['MACD_HIST'] > p2['MACD_HIST'])
                except KeyError:
                    return False

            def is_j_up_turn(c, p1, p2):
                # J 上拐: t > t-1, t-1 <= t-2
                try:
                    return (c['J'] > p1['J']) and (p1['J'] <= p2['J'])
                except KeyError:
                    return False

            def is_dea_up_turn(c, p1, p2):
                # DEA 上拐
                try:
                    return (c['MACD_DEA'] > p1['MACD_DEA']) and (p1['MACD_DEA'] <= p2['MACD_DEA'])
                except KeyError:
                    return False

            # 买入信号
            signal_buy = False
            # 买入: 月MACD绝对递增 且 月J<80 且 周MACD绝对递增 且 (日J上拐且J<80 或 日DEA上拐)
            if self.position == 0:
                # 1. 月线
                cond_m = is_macd_growing(curr_m, prev_m, prev_m2) and (curr_m['J'] < 80)
                # 2. 周线
                cond_w = is_macd_growing(curr_w, prev_w, prev_w2)
                # 3. 日线
                cond_d = (is_j_up_turn(daily_row, d_row_1, d_row_2) and daily_row['J'] < 80) or \
                         is_dea_up_turn(daily_row, d_row_1, d_row_2)

                if cond_m and cond_w and cond_d:
                    # 额外条件: 资金足够
                    if self.cash > daily_row['Close'] * 100:
                        signal_buy = True

            # 卖出信号
            signal_sell = False
            is_stop_loss = False

            if self.position == 1:
                # 止损: 收盘 < 买入价 * 0.97
                if daily_row['Close'] < self.entry_price * 0.97:
                    signal_sell = True
                    is_stop_loss = True
                else:
                    # 卖出逻辑:
                    # 日线 MACD 缩小 (Hist[t] < Hist[t-1])
                    cond_macd_shrink = daily_row['MACD_HIST'] < d_row_1['MACD_HIST']

                    # 且 (J在80以上下拐 或 J < D)
                    # J下拐: t < t-1, t-1 >= t-2
                    j_down_turn = (daily_row['J'] < d_row_1['J']) and (d_row_1['J'] >= d_row_2['J'])

                    # "J值在80以上区间下拐": 指拐点位置的值 > 80 (即 d_row_1['J'] > 80)
                    cond_j_turn = j_down_turn and (d_row_1['J'] > 80)

                    cond_j_cross = daily_row['J'] < daily_row['D']

                    if cond_macd_shrink and (cond_j_turn or cond_j_cross):
                        signal_sell = True

            # --- 执行交易 ---
            if signal_buy and self.position == 0:
                # 全仓买入 (简单模拟, 每次买1手以上，整手买入)
                price = daily_row['Close']
                # 扣除一些手续费? 暂不考虑
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
                        "price": price
                    })

            elif signal_sell and self.position == 1:
                price = daily_row['Close']
                revenue = self.shares * price
                self.cash += revenue
                self.shares = 0
                self.position = 0

                reason = "Stop Loss" if is_stop_loss else "Signal"
                self.trades.append({
                    "action": "sell",
                    "date": str(current_date.date()),
                    "price": price,
                    "reason": reason
                })

            # 记录当日权益
            if self.position == 1:
                equity = self.cash + (self.shares * daily_row['Close'])
            else:
                equity = self.cash

            self.equity_curve.append({
                "date": str(current_date.date()),
                "value": equity
            })

        return {
            "bars": self.daily_processed.to_json(orient='index', date_format='iso'),
            "trades": self.trades,
            "equity_curve": self.equity_curve
        }
