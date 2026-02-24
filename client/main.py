import sys
import os

# 强制使用 PyQt5 兼容模式
os.environ["PYQTGRAPH_QT_LIB"] = "PyQt5"

# 确保项目根目录在 sys.path 中，以便可以导入 'client' 包
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.insert(0, root_dir)

from PyQt5.QtWidgets import QApplication
from client.ui.main_window import MainWindow

def main():
    """
    客户端程序入口。
    初始化 QApplication 并显示主窗口。
    """
    app = QApplication(sys.argv)

    # 设置应用风格 (可选，Fusion 跨平台一致性较好)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
