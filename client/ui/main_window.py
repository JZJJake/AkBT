from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QComboBox, QDateEdit,
                               QCompleter, QLabel, QFrame, QProgressBar, QMessageBox, QDockWidget)
from PySide6.QtCore import Qt, QDate, QStringListModel, QTimer
import pyqtgraph as pg
import pandas as pd
import numpy as np
import json
import io
import requests
from client.ui.chart_items import CandlestickItem, DateAxis
from client.api.worker import BacktestWorker
from client.ui.stats_panel import StatsPanel

class MainWindow(QMainWindow):
    """
    客户端主窗口 UI 框架。
    包含顶部工具栏 (搜索、日期选择) 和中部图表区 (K线、成交量、MACD、KDJ)。
    新增: 回测统计面板 (StatsPanel)
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("A股策略回测统计分析软件 (C端)")
        self.resize(1400, 900)

        # 中央部件与主布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)

        # 1. 创建顶部工具栏
        self.create_toolbar()

        # 2. 创建图表显示区域
        self.create_charts()

        # 3. 创建统计面板 (DockWidget)
        self.create_stats_panel()

        # 4. 初始化工作线程引用
        self.worker = None

        # 5. 异步加载全市场股票列表
        QTimer.singleShot(100, self.load_stock_list)

    def create_toolbar(self):
        """创建顶部工具栏组件: 搜索框、周期切换、日期选择、运行按钮。"""
        toolbar_layout = QHBoxLayout()
        self.main_layout.addLayout(toolbar_layout)

        # 股票搜索框 (支持 代码/名称/拼音 模糊匹配)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索股票 (代码/拼音/汉字) 或输入 ALL 回测全部")
        self.search_input.setFixedWidth(300)
        toolbar_layout.addWidget(self.search_input)

        # Completer 初始为空
        self.completer = QCompleter([])
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.search_input.setCompleter(self.completer)

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
        self.p_main.setTitle("主图 (K线 / 资金曲线)")
        self.p_main.showGrid(x=True, y=True)
        self.p_main.hideAxis('bottom') # 隐藏底部轴，避免与下方图表重复
        self.p_main.setLabel('left', 'Price')

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

    def create_stats_panel(self):
        """创建右侧统计面板 (QDockWidget)"""
        self.stats_panel = StatsPanel(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.stats_panel)

    def load_stock_list(self):
        """从服务端加载全市场股票列表"""
        try:
            url = "http://127.0.0.1:8000/api/market/stocks"
            # 增加超时，防止阻塞太久
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                stocks = resp.json()
                search_items = []
                for s in stocks:
                    # 格式: "000001 平安银行 payh pinganyinhang"
                    item_str = f"{s['code']} {s['name']} {s['pinyin']} {s['full_pinyin']}"
                    search_items.append(item_str)

                # 更新 Completer
                model = QStringListModel(search_items)
                self.completer.setModel(model)
            else:
                print(f"Failed to load stocks: {resp.status_code}")
        except Exception as e:
            print(f"Error loading stock list: {e}")

    def run_backtest(self):
        """处理回测按钮点击: 启动后台线程异步执行回测任务。"""
        # 1. 禁用按钮，避免重复点击
        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        # 2. 获取输入参数
        ticker_text = self.search_input.text().strip()
        if not ticker_text:
             ticker_text = "000001" # Default

        # 支持多股: 以逗号分隔，或 "ALL"
        if ticker_text.upper() == "ALL":
             codes = ["ALL"]
        else:
             # 解析用户输入
             # 用户可能输入 "000001 平安银行..." 或 "000001, 600519"
             # 简单解析: split by comma, then take first part of space split
             parts = ticker_text.split(',')
             codes = []
             for p in parts:
                 c = p.strip().split(' ')[0]
                 if c: codes.append(c)

        start_date = self.start_date.date().toString("yyyy-MM-dd")
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        period = self.period_combo.currentText()

        # 3. 创建并启动工作线程
        self.worker = BacktestWorker(codes, start_date, end_date, period, mode="remote")

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
        # result 包含 {bars, trades, equity_curve}
        try:
            # 1. 解析数据
            bars_json = result.get("bars")
            df = pd.DataFrame()
            if bars_json:
                df = pd.read_json(io.StringIO(bars_json), orient='index')
                df.index = pd.to_datetime(df.index)
                df.sort_index(inplace=True)

            trades = result.get("trades", [])
            equity_curve = result.get("equity_curve", [])

            # 2. 刷新图表
            self.update_charts(df, trades, equity_curve)

            # 3. 更新统计面板
            self.stats_panel.update_stats(trades, equity_curve)

        except Exception as e:
            self.handle_backtest_error(f"Failed to parse result: {str(e)}")

    def handle_backtest_error(self, msg):
        """显示错误信息"""
        print(f"Backtest Error: {msg}")
        QMessageBox.warning(self, "Backtest Error", msg)
        self.run_btn.setEnabled(True)

    def thread_finished(self):
        """线程结束清理"""
        self.run_btn.setEnabled(True)
        self.worker = None

    def update_charts(self, df, trades=None, equity_curve=None):
        """根据 DataFrame 数据绘制所有图表。"""
        # 清空旧数据
        self.p_main.clear()
        self.p_vol.clear()
        self.p_macd.clear()
        self.p_kdj.clear()

        # 多股模式下 df 可能为空
        is_multi_stock = df.empty

        # 设置 X 轴
        # 如果是单股，用 df.index
        # 如果是多股 (df empty)，用 equity_curve 的 date
        dates = []
        if not df.empty:
            dates = df.index.tolist()
        elif equity_curve:
            # equity_curve is list of dict [{'date': '...', 'value': ...}]
            dates = [pd.to_datetime(item['date']) for item in equity_curve]

        if not dates:
            return

        # 更新日期轴
        self.date_axis.dates = dates
        self.date_axis.update() # 强制重绘

        x_indices = np.arange(len(dates))

        # --- 绘制主图 ---
        if not is_multi_stock:
            # 单股: 绘制 K 线
            self.p_main.setTitle("主图 (K线)")
            ohlc_data = []
            for i, row in enumerate(df.itertuples()):
                ohlc_data.append((i, row.Open, row.Close, row.Low, row.High))
            candlestick = CandlestickItem(ohlc_data)
            self.p_main.addItem(candlestick)

            # 绘制买卖点
            if trades:
                self.plot_trades(trades, df)

            # 绘制成交量
            brushes = []
            for row in df.itertuples():
                if row.Close >= row.Open:
                    brushes.append(pg.mkBrush('r'))
                else:
                    brushes.append(pg.mkBrush('g'))
            vol_item = pg.BarGraphItem(x=x_indices, height=df['Volume'], width=0.6, brushes=brushes)
            self.p_vol.addItem(vol_item)

            # 绘制 MACD
            hist_brushes = []
            for val in df['MACD_HIST']:
                if val >= 0: hist_brushes.append(pg.mkBrush('r'))
                else: hist_brushes.append(pg.mkBrush('g'))
            macd_hist = pg.BarGraphItem(x=x_indices, height=df['MACD_HIST'], width=0.6, brushes=hist_brushes)
            self.p_macd.addItem(macd_hist)
            self.p_macd.plot(x_indices, df['MACD_DIF'], pen='w', name='DIF')
            self.p_macd.plot(x_indices, df['MACD_DEA'], pen='y', name='DEA')

            # 绘制 KDJ
            self.p_kdj.plot(x_indices, df['K'], pen='w', name='K')
            self.p_kdj.plot(x_indices, df['D'], pen='y', name='D')
            self.p_kdj.plot(x_indices, df['J'], pen='m', name='J')

        else:
            # 多股/全市场: 绘制资金曲线
            self.p_main.setTitle("组合资金曲线 (Total Equity)")
            if equity_curve:
                values = [item['value'] for item in equity_curve]
                # 绘制一条青色曲线
                self.p_main.plot(x_indices, values, pen=pg.mkPen('c', width=2), name="Equity")

            # 清空其他图表并显示提示
            # 或者可以显示聚合的 Volume (如果 S 端提供了的话，但目前 S 端只聚合了 Equity)
            # 这里保持为空

    def plot_trades(self, trades, df):
        """在主图上绘制买卖点标记 (箭头)"""
        # trades 格式: [{"action": "buy", "date": "2023-01-01", "price": 100}, ...]
        for trade in trades:
            action = trade.get('action')
            date_str = trade.get('date')
            price = trade.get('price')

            try:
                ts = pd.Timestamp(date_str)
                if ts in df.index:
                    idx = df.index.get_loc(ts)
                    if action == 'buy':
                        arrow = pg.ArrowItem(pos=(idx, price), angle=90, tipAngle=30, headLen=10, tailLen=10, tailWidth=5, pen={'color': 'r', 'width': 1}, brush='r')
                        self.p_main.addItem(arrow)
                    elif action == 'sell':
                        arrow = pg.ArrowItem(pos=(idx, price), angle=-90, tipAngle=30, headLen=10, tailLen=10, tailWidth=5, pen={'color': 'g', 'width': 1}, brush='g')
                        self.p_main.addItem(arrow)
            except Exception:
                pass
