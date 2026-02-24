import pyqtgraph as pg
from PyQt5 import QtCore, QtGui

class DateAxis(pg.AxisItem):
    """
    自定义日期轴组件，用于将图表的整数索引映射为 YYYY-MM-DD 格式日期字符串。
    """
    def __init__(self, dates, orientation='bottom', **kwargs):
        """
        初始化日期轴。

        参数:
            dates (list): 日期对象列表 (如 pd.Timestamp 或 str)
            orientation (str): 轴方向 ('bottom', 'top', etc.)
        """
        pg.AxisItem.__init__(self, orientation=orientation, **kwargs)
        self.dates = dates

    def tickStrings(self, values, scale, spacing):
        """
        PyQtGraph 内部调用，用于生成刻度标签。
        values: 当前视图中的刻度值 (索引 float)
        """
        strings = []
        for v in values:
            idx = int(v)
            # 确保索引在有效范围内
            if 0 <= idx < len(self.dates):
                ts = self.dates[idx]
                if hasattr(ts, 'strftime'):
                    strings.append(ts.strftime('%Y-%m-%d'))
                else:
                    strings.append(str(ts))
            else:
                strings.append('')
        return strings

class CandlestickItem(pg.GraphicsObject):
    """
    自定义 K线图 (蜡烛图) 绘制项。
    PyQtGraph 默认没有提供标准的 K线 Item，需要手动实现 `paint` 方法。
    """
    def __init__(self, data):
        """
        初始化 K线数据。

        参数:
            data (list of tuples): [(t, open, close, low, high), ...]
            其中 t 为整数索引。
        """
        pg.GraphicsObject.__init__(self)
        self.data = data
        self.generatePicture()

    def generatePicture(self):
        """
        预生成 QPicture 绘图指令，提高重绘性能。
        """
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)

        w = 0.4  # K线柱体半宽

        for (t, open_p, close_p, low_p, high_p) in self.data:
            # 判断涨跌 (A股习惯: 收盘 >= 开盘 为红/涨; 收盘 < 开盘 为绿/跌)
            if close_p >= open_p:
                p.setPen(pg.mkPen('r'))   # 红色边框
                p.setBrush(pg.mkBrush('r')) # 红色填充
            else:
                p.setPen(pg.mkPen('g'))   # 绿色边框
                p.setBrush(pg.mkBrush('g')) # 绿色填充

            # 绘制影线 (最高价 - 最低价)
            p.drawLine(QtCore.QPointF(t, low_p), QtCore.QPointF(t, high_p))

            # 绘制实体 (开盘价 - 收盘价)
            # 如果开盘价等于收盘价 (十字星)，绘制一条横线
            if abs(close_p - open_p) < 0.0001:
                 p.drawLine(QtCore.QPointF(t-w, open_p), QtCore.QPointF(t+w, close_p))
            else:
                p.drawRect(QtCore.QRectF(t-w, open_p, w*2, close_p - open_p))

        p.end()

    def paint(self, p, *args):
        # 实际绘制时重放 QPicture
        self.picture.play(p)

    def boundingRect(self):
        # 返回绘图边界，用于视图范围计算
        return QtCore.QRectF(self.picture.boundingRect())

    def updateData(self, data):
        self.data = data
        self.generatePicture()
        self.informViewBoundsChanged()
