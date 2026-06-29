
from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox

class AddStrategyDialog(QDialog):
    def __init__(self, registry: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить стратегию")
        layout = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.class_combo = QComboBox()
        self.class_combo.addItems(list(registry.keys()))

        layout.addRow("Имя стратегии:", self.name_edit)
        layout.addRow("Класс:", self.class_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)