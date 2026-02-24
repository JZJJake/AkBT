from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QComboBox, QDateEdit,
                               QCompleter, QLabel, QFrame)
from PySide6.QtCore import Qt, QDate, QStringListModel
import pyqtgraph as pg
import pandas as pd
import numpy as np
from client.data.mock import generate_mock_data
from client.ui.chart_items import CandlestickItem, DateAxis

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

        # 初始化显示模拟数据
        self.run_backtest()

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
        """处理回测按钮点击: 生成/获取数据并刷新图表。"""
        # 1. 获取输入参数
        ticker_text = self.search_input.text()
        # 简单解析: 取第一个空格前的代码，默认为 000001
        code = ticker_text.split(' ')[0] if ticker_text else "000001"

        # 2. 调用 Mock 数据生成器 (模拟 ~300 个交易日)
        # 实际开发中此处将调用 S端 API
        df = generate_mock_data(ticker=code, n_days=300)

        # 3. 刷新 UI
        self.update_charts(df)

    def update_charts(self, df):
        """根据 DataFrame 数据绘制所有图表。"""
        # 清空旧数据
        self.p_main.clear()
        self.p_vol.clear()
        self.p_macd.clear()
        self.p_kdj.clear()

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

        # 自动调整主图视图范围 (可选)
        # self.p_main.autoRange()
