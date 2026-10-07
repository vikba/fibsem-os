import sys

from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)


class SolistMainUI(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("SOLIST")
        self.resize(1000, 700)

        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        layout.addWidget(QLabel("SOLIST Workflow"))
        layout.addWidget(QLabel("Placeholder application"))

        self.setCentralWidget(central_widget)


def run_ui():
    app = QApplication.instance()

    if app is None:
        app = QApplication(sys.argv)

    window = SolistMainUI()
    window.show()

    return app.exec_()


if __name__ == "__main__":
    run_ui()