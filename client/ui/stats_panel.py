from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLabel,
                               QDockWidget, QTableWidget, QTableWidgetItem, QHeaderView)
from PySide6.QtCore import Qt
import pandas as pd

class StatsPanel(QDockWidget):
    """
    回测统计报告面板 (DockWidget)
    """
    def __init__(self, parent=None):
        super().__init__("回测统计报告 (Backtest Report)", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        # 主内容区域
        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)

        # 1. 核心指标概览 (FormLayout)
        stats_layout = QFormLayout()
        self.lbl_total_trades = QLabel("0")
        self.lbl_win_rate = QLabel("0.00%")
        self.lbl_total_return = QLabel("0.00%")
        self.lbl_max_drawdown = QLabel("0.00%")

        stats_layout.addRow("总交易次数 (Total Trades):", self.lbl_total_trades)
        stats_layout.addRow("胜率 (Win Rate):", self.lbl_win_rate)
        stats_layout.addRow("总收益率 (Total Return):", self.lbl_total_return)
        stats_layout.addRow("最大回撤 (Max Drawdown):", self.lbl_max_drawdown)

        layout.addLayout(stats_layout)

        # 2. 交易明细表格 (TableWidget)
        layout.addWidget(QLabel("最近交易明细 (Recent Trades):"))
        self.trade_table = QTableWidget()
        self.trade_table.setColumnCount(4)
        self.trade_table.setHorizontalHeaderLabels(["Code", "Date", "Action", "Price"])
        self.trade_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.trade_table)

    def update_stats(self, trades, equity_curve):
        """
        根据回测结果更新统计面板

        参数:
            trades (list): 交易明细 [{"code": "...", "action": "buy", ...}]
            equity_curve (list): 资金曲线 [{"date": "...", "value": ...}]
        """
        # --- 1. 计算核心指标 ---

        # 总交易次数 (Open + Close pair = 1 trade? Or count all actions?)
        # Requirement: len(trades) / 2
        total_actions = len(trades)
        total_trades = total_actions // 2

        # 胜率 (Win Rate)
        # 需匹配买卖对。简单估算:
        # 如果是单股全仓模式，每次 sell 的 revenue > buy cost 则为赢。
        # 但 trades 列表是打平的。我们需要按 code 追踪。
        # 简化逻辑: 统计所有 "sell" 动作。如果 sell price > 最近一次 buy price (同code)?
        # 由于并发回测结果混在一起，且可能存在多次买卖。
        # 严谨做法: 重建持仓流。
        # 简单近似: 遍历 trades，维护一个 {code: last_buy_price} 的字典。
        # 遇到 sell 时，计算 diff。

        wins = 0
        losses = 0
        holding_cost = {} # {code: price}

        # 按日期排序 trades 确保顺序正确 (虽然 server 已经 aggregated，但最好 sort 一下)
        # Server aggregation might just extend list.
        # Let's sort trades by date first.
        trades_sorted = sorted(trades, key=lambda x: x['date'])

        for t in trades_sorted:
            code = t.get('code', 'UNKNOWN')
            action = t.get('action')
            price = t.get('price')

            if action == 'buy':
                holding_cost[code] = price
            elif action == 'sell':
                cost = holding_cost.get(code)
                if cost:
                    if price > cost:
                        wins += 1
                    else:
                        losses += 1
                    # Clear cost (assuming full sell)
                    holding_cost.pop(code, None)

        total_closed_trades = wins + losses
        win_rate = (wins / total_closed_trades * 100) if total_closed_trades > 0 else 0.0

        # 总收益率 (Total Return)
        # (Final Equity - Initial Equity) / Initial Equity
        total_return = 0.0
        if equity_curve:
            # 假设初始资金是 equity_curve 第一点的 value (或者如果第一点是 0?)
            # 我们的 server 逻辑: fillna(initial_cash)
            start_val = equity_curve[0]['value']
            end_val = equity_curve[-1]['value']
            if start_val > 0:
                total_return = (end_val - start_val) / start_val * 100

        # 最大回撤 (Max Drawdown)
        max_dd = 0.0
        if equity_curve:
            values = [x['value'] for x in equity_curve]
            # Peak so far
            peak = values[0]
            max_drop = 0.0
            for v in values:
                if v > peak:
                    peak = v
                dd = (peak - v) / peak if peak > 0 else 0
                if dd > max_drop:
                    max_drop = dd
            max_dd = max_drop * 100

        # --- 2. 更新 UI ---
        self.lbl_total_trades.setText(f"{total_trades}")
        self.lbl_win_rate.setText(f"{win_rate:.2f}% ({wins}/{total_closed_trades})")

        # Color for return
        color = "red" if total_return > 0 else "green"
        self.lbl_total_return.setText(f"<span style='color:{color}'>{total_return:.2f}%</span>")
        self.lbl_max_drawdown.setText(f"{max_dd:.2f}%")

        # --- 3. 更新表格 ---
        # 显示最近 50 条
        recent_trades = trades_sorted[-50:]
        # 倒序显示 (最新的在上面)
        recent_trades.reverse()

        self.trade_table.setRowCount(len(recent_trades))
        for i, t in enumerate(recent_trades):
            code_item = QTableWidgetItem(t.get('code', 'N/A'))
            date_item = QTableWidgetItem(t.get('date', ''))
            action_item = QTableWidgetItem(t.get('action', '').upper())
            price_item = QTableWidgetItem(f"{t.get('price', 0):.2f}")

            # Color action
            if t.get('action') == 'buy':
                action_item.setForeground(Qt.red)
            else:
                action_item.setForeground(Qt.green)

            self.trade_table.setItem(i, 0, code_item)
            self.trade_table.setItem(i, 1, date_item)
            self.trade_table.setItem(i, 2, action_item)
            self.trade_table.setItem(i, 3, price_item)
