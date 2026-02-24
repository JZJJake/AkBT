from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QComboBox, QDateEdit,
                               QCompleter, QLabel, QFrame, QProgressBar)
from PySide6.QtCore import Qt, QDate, QStringListModel
import pyqtgraph as pg
import pandas as pd
import numpy as np
import json
import io
# from client.data.mock import generate_mock_data # Removed mock data import
from client.ui.chart_items import CandlestickItem, DateAxis
from client.api.worker import BacktestWorker

# 模拟搜索数据字典 (代码, 简称, 拼音)
STOCK_DICT = {
    '000001': ['平安银行', 'payh', 'pinganyinhang'],
    '600519': ['贵州茅台', 'gzmt', 'guizhoumaotai'],
    '000002': ['万科A', 'wka', 'wankea'],
    '000651': ['格力电器', 'gldq', 'gelidianqi'],
    '601318': ['中国平安', 'zgpa', 'zhongguopingan'],
}

class MainWindow(QMainWindow):
    """
    客户端主窗口 UI 框架。
    包含顶部工具栏 (搜索、日期选择) 和中部图表区 (K线、成交量、MACD、KDJ)。
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("A股策略回测统计分析软件 (C端)")
        self.resize(1200, 800)

        # 中央部件与主布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)

        # 1. 创建顶部工具栏
        self.create_toolbar()

        # 2. 创建图表显示区域
        self.create_charts()

        # 3. 初始化工作线程引用
        self.worker = None

        # 初始默认运行一次 (可选)
        # self.run_backtest()

    def create_toolbar(self):
        """创建顶部工具栏组件: 搜索框、周期切换、日期选择、运行按钮。"""
        toolbar_layout = QHBoxLayout()
        self.main_layout.addLayout(toolbar_layout)

        # 股票搜索框 (支持 代码/名称/拼音 模糊匹配)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索股票 (代码/拼音/汉字)")
        toolbar_layout.addWidget(self.search_input)

        # 设置 QCompleter 实现自动补全与下拉提示
        search_items = []
        for code, info in STOCK_DICT.items():
            # 将所有关键字合并为一个字符串，配合 MatchContains 实现模糊搜索
            # 格式: "000001 平安银行 PAYH pinganyinhang"
            item_str = f"{code} {info[0]} {info[1]} {info[2]}"
            search_items.append(item_str)

        completer = QCompleter(search_items)
        completer.setCaseSensitivity(Qt.CaseInsensitive) # 忽略大小写
        completer.setFilterMode(Qt.MatchContains)        # 包含匹配模式
        self.search_input.setCompleter(completer)

        # 周期切换 (日/周/月)
        self.period_combo = QComboBox()
        self.period_combo.addItems(["Daily (日线)", "Weekly (周线)", "Monthly (月线)"])
        toolbar_layout.addWidget(QLabel("周期:"))
        toolbar_layout.addWidget(self.period_combo)

        # 回测日期区间选择
        self.start_date = QDateEdit(QDate.currentDate().addDays(-365))
        self.start_date.setCalendarPopup(True) # 弹出式日历
        self.end_date = QDateEdit(QDate.currentDate())
        self.end_date.setCalendarPopup(True)

        toolbar_layout.addWidget(QLabel("开始:"))
        toolbar_layout.addWidget(self.start_date)
        toolbar_layout.addWidget(QLabel("结束:"))
        toolbar_layout.addWidget(self.end_date)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(150)
        toolbar_layout.addWidget(self.progress_bar)

        # 执行回测按钮
        self.run_btn = QPushButton("执行回测")
        self.run_btn.clicked.connect(self.run_backtest)
        toolbar_layout.addWidget(self.run_btn)

        # 弹性占位符，将按钮靠左排列
        toolbar_layout.addStretch()

    def create_charts(self):
        """使用 GraphicsLayoutWidget 创建垂直排列的4个联动图表。"""
        # GraphicsLayoutWidget 是 PyQtGraph 中高效管理多个 PlotItem 的容器
        self.glw = pg.GraphicsLayoutWidget()
        self.main_layout.addWidget(self.glw)

        # 初始化自定义日期轴 (将在 update_charts 中绑定数据)
        self.date_axis = DateAxis(dates=[], orientation='bottom')

        # --- 图表 1: 主图 (K线) ---
        # 第一行第一列
        self.p_main = self.glw.addPlot(row=0, col=0)
        self.p_main.setTitle("主图 (K线)")
        self.p_main.showGrid(x=True, y=True)
        self.p_main.hideAxis('bottom') # 隐藏底部轴，避免与下方图表重复

        # --- 图表 2: 成交量 (Volume) ---
        self.glw.nextRow() # 换行
        self.p_vol = self.glw.addPlot(row=1, col=0)
        self.p_vol.setMaximumHeight(150) # 限制高度
        self.p_vol.setTitle("成交量")
        self.p_vol.showGrid(x=True, y=True)
        self.p_vol.hideAxis('bottom')
        self.p_vol.setXLink(self.p_main) # 与主图 X轴联动 (平移/缩放同步)

        # --- 图表 3: MACD 指标 ---
        self.glw.nextRow()
        self.p_macd = self.glw.addPlot(row=2, col=0)
        self.p_macd.setMaximumHeight(150)
        self.p_macd.setTitle("MACD (12,26,9)")
        self.p_macd.showGrid(x=True, y=True)
        self.p_macd.hideAxis('bottom')
        self.p_macd.setXLink(self.p_main)

        # --- 图表 4: KDJ 指标 ---
        self.glw.nextRow()
        # 将自定义 DateAxis 绑定到底部图表
        self.p_kdj = self.glw.addPlot(row=3, col=0, axisItems={'bottom': self.date_axis})
        self.p_kdj.setMaximumHeight(150)
        self.p_kdj.setTitle("KDJ (9,3,3)")
        self.p_kdj.showGrid(x=True, y=True)
        self.p_kdj.setXLink(self.p_main)

    def run_backtest(self):
        """处理回测按钮点击: 启动后台线程异步执行回测任务。"""
        # 1. 禁用按钮，避免重复点击
        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        # 2. 获取输入参数
        ticker_text = self.search_input.text()
        code = ticker_text.split(' ')[0] if ticker_text else "000001"
        start_date = self.start_date.date().toString("yyyy-MM-dd")
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        period = self.period_combo.currentText()

        # 3. 创建并启动工作线程
        # 使用 remote 模式连接真实后端
        self.worker = BacktestWorker(code, start_date, end_date, period, mode="remote")

        # 连接信号
        self.worker.progress_updated.connect(self.update_progress)
        self.worker.data_received.connect(self.handle_backtest_result)
        self.worker.error_occurred.connect(self.handle_backtest_error)
        self.worker.finished.connect(self.thread_finished) # 清理

        # 启动线程
        self.worker.start()

    def update_progress(self, val):
        """更新进度条"""
        self.progress_bar.setValue(val)

    def handle_backtest_result(self, result):
        """处理回测线程返回的结果 (JSON 格式)"""
        # 1. 解析 bars 数据 (DataFrame JSON)
        try:
            bars_json = result.get("bars")
            df = pd.read_json(io.StringIO(bars_json), orient='index')
            # 确保索引为 DatetimeIndex
            df.index = pd.to_datetime(df.index)
            df.sort_index(inplace=True)

            # 2. 刷新图表
            trades = result.get("trades", [])
            self.update_charts(df, trades)

            # 3. 处理资金曲线 (后续实现)
            equity_curve = result.get("equity_curve", [])

        except Exception as e:
            self.handle_backtest_error(f"Failed to parse result: {str(e)}")

    def handle_backtest_error(self, msg):
        """显示错误信息"""
        print(f"Backtest Error: {msg}")
        self.run_btn.setEnabled(True)

    def thread_finished(self):
        """线程结束清理"""
        self.run_btn.setEnabled(True)
        self.worker = None

    def update_charts(self, df, trades=None):
        """根据 DataFrame 数据绘制所有图表。"""
        # 清空旧数据
        self.p_main.clear()
        self.p_vol.clear()
        self.p_macd.clear()
        self.p_kdj.clear()

        if df.empty:
            return

        # 更新日期轴的日期映射列表
        dates = df.index.tolist()
        self.date_axis.dates = dates
        self.date_axis.update() # 强制重绘

        # X轴使用整数索引 [0, 1, 2, ... N]
        x_indices = np.arange(len(df))

        # --- 绘制主图: K线 ---
        # 转换数据为 CandlestickItem 所需格式: (索引, Open, Close, Low, High)
        ohlc_data = []
        for i, row in enumerate(df.itertuples()):
            # row 是命名元组, 包含 Open, High, Low, Close 等属性
            ohlc_data.append((i, row.Open, row.Close, row.Low, row.High))

        candlestick = CandlestickItem(ohlc_data)
        self.p_main.addItem(candlestick)

        # --- 绘制买卖点 (Trades) ---
        if trades:
            self.plot_trades(trades, df)

        # --- 绘制成交量 ---
        # 根据涨跌设置颜色 (红/绿)
        brushes = []
        for row in df.itertuples():
            if row.Close >= row.Open:
                brushes.append(pg.mkBrush('r'))
            else:
                brushes.append(pg.mkBrush('g'))

        vol_item = pg.BarGraphItem(x=x_indices, height=df['Volume'], width=0.6, brushes=brushes)
        self.p_vol.addItem(vol_item)

        # --- 绘制 MACD ---
        # MACD柱状图 (HIST): 正值红，负值绿 (此处简化为数值正负，实际策略中可能关注动量)
        hist_brushes = []
        for val in df['MACD_HIST']:
            if val >= 0:
                hist_brushes.append(pg.mkBrush('r'))
            else:
                hist_brushes.append(pg.mkBrush('g'))

        macd_hist = pg.BarGraphItem(x=x_indices, height=df['MACD_HIST'], width=0.6, brushes=hist_brushes)
        self.p_macd.addItem(macd_hist)

        # MACD 快慢线 (DIF: 白, DEA: 黄)
        self.p_macd.plot(x_indices, df['MACD_DIF'], pen='w', name='DIF')
        self.p_macd.plot(x_indices, df['MACD_DEA'], pen='y', name='DEA')

        # --- 绘制 KDJ ---
        # K: 白, D: 黄, J: 紫
        self.p_kdj.plot(x_indices, df['K'], pen='w', name='K')
        self.p_kdj.plot(x_indices, df['D'], pen='y', name='D')
        self.p_kdj.plot(x_indices, df['J'], pen='m', name='J')

    def plot_trades(self, trades, df):
        """在主图上绘制买卖点标记 (箭头)"""
        # trades 格式: [{"action": "buy", "date": "2023-01-01", "price": 100}, ...]
        # 需要找到日期对应的索引

        for trade in trades:
            action = trade.get('action') # "buy" or "sell"
            date_str = trade.get('date') # "YYYY-MM-DD"
            price = trade.get('price')

            # 查找日期索引
            try:
                ts = pd.Timestamp(date_str)
                # 使用 searchsorted 查找最接近的索引，或者用 get_loc 如果索引完全匹配
                # 这里假设 trades 里的 date 是准确存在的交易日
                if ts in df.index:
                    idx = df.index.get_loc(ts)

                    if action == 'buy':
                        # 向上箭头 (Buy) - 红色 (或按照惯例 Buy通常在下方指向上)
                        # PyQtGraph ArrowItem options: tipAngle, baseAngle, headLen, tailLen, tailWidth, pen, brush
                        # pos 是数据坐标 (x_index, y_price)
                        # Arrow pointing UP means base is down, tip is up.
                        # To point to a point (idx, price) from BELOW, we need the arrow to point UP.
                        # angle=90 points UP.
                        arrow = pg.ArrowItem(pos=(idx, price), angle=90, tipAngle=30, headLen=10, tailLen=10, tailWidth=5, pen={'color': 'r', 'width': 1}, brush='r')
                        self.p_main.addItem(arrow)

                    elif action == 'sell':
                        # 向下箭头 (Sell) - 绿色 (从上方指向下方点)
                        # angle=-90 points DOWN.
                        arrow = pg.ArrowItem(pos=(idx, price), angle=-90, tipAngle=30, headLen=10, tailLen=10, tailWidth=5, pen={'color': 'g', 'width': 1}, brush='g')
                        self.p_main.addItem(arrow)
            except Exception as e:
                print(f"Error plotting trade {trade}: {e}")
