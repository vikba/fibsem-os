
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QLabel, QPushButton,
)

from fibsem.applications.solist.workflow import WORKFLOW


class SolistWorkflowWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.completed = set()  # Demo status only
        self.selected = None

        # Left panel: workflow tree
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)

        for phase, operations in WORKFLOW.items():
            group = QTreeWidgetItem([phase])
            self.tree.addTopLevelItem(group)

            for operation in operations:
                item = QTreeWidgetItem([operation])
                item.setData(0, Qt.UserRole, (phase, operation))
                group.addChild(item)

        self.tree.expandAll()
        self.tree.currentItemChanged.connect(self.select_operation)

        # Right panel: operation details
        details = QWidget()
        right = QVBoxLayout(details)

        self.phase_label = QLabel("Phase")
        self.operation_label = QLabel("Select an operation")
        self.status_label = QLabel("Not started")
        self.info_label = QLabel("Parameters and controls: TODO")

        right.addWidget(self.phase_label)
        right.addWidget(self.operation_label)
        right.addWidget(self.status_label)
        right.addWidget(self.info_label)
        right.addStretch()

        self.demo_button = QPushButton("Simulate completion")
        self.demo_button.clicked.connect(self.toggle_completion)
        right.addWidget(self.demo_button)

        # Main layout
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(details)
        splitter.setSizes([350, 650])

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        # Select the first operation
        first = self.tree.topLevelItem(0).child(0)
        self.tree.setCurrentItem(first)

    def select_operation(self, item, previous=None):
        self.selected = item.data(0, Qt.UserRole) if item else None
        self.demo_button.setEnabled(self.selected is not None)

        if self.selected is None:
            return

        phase, operation = self.selected
        self.phase_label.setText(f"Phase: {phase}")
        self.operation_label.setText(f"Operation: {operation}")

        status = (
            "Completed (simulated)"
            if self.selected in self.completed
            else "Not started"
        )
        self.status_label.setText(f"Status: {status}")

    def toggle_completion(self):
        if self.selected is None:
            return

        if self.selected in self.completed:
            self.completed.remove(self.selected)
        else:
            self.completed.add(self.selected)

        self.select_operation(self.tree.currentItem())
