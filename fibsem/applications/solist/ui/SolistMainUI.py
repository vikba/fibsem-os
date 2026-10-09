import sys

from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)


from fibsem.ui.FibsemUI import FibsemUI
from fibsem.applications.solist.ui.workflow_widget import (
    SolistWorkflowWidget,
)


class SolistUI(FibsemUI):
    def __init__(self):
        super().__init__()

        self.solist_workflow = SolistWorkflowWidget(self)
        self.tab_widget.addTab(
            self.solist_workflow,
            "SOLIST workflow",
        )


def run_ui():
    app = QApplication.instance()

    if app is None:
        app = QApplication(sys.argv)

    window = SolistUI()
    window.show()

    return app.exec_()


if __name__ == "__main__":
    run_ui()