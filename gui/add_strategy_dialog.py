# from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox

# class AddStrategyDialog(QDialog):
#     def __init__(self, registry: dict, parent=None):
#         super().__init__(parent)
#         self.setWindowTitle("Добавить стратегию")
#         layout = QFormLayout(self)

#         self.name_edit = QLineEdit()
#         self.symbol_edit = QLineEdit()
#         self.mode_combo = QComboBox()
#         self.mode_combo.addItems(["AUTO", "SIGNAL"])
#         self.timeframes_edit = QLineEdit()
#         self.timeframes_edit.setText("1m,5m")
#         self.class_combo = QComboBox()
#         self.class_combo.addItems(list(registry.keys()))

#         layout.addRow("Имя:", self.name_edit)
#         layout.addRow("Символ:", self.symbol_edit)
#         layout.addRow("Режим:", self.mode_combo)
#         layout.addRow("Таймфреймы:", self.timeframes_edit)
#         layout.addRow("Класс:", self.class_combo)

#         buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
#         buttons.accepted.connect(self.accept)
#         buttons.rejected.connect(self.reject)
#         layout.addRow(buttons)
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