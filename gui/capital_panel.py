from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QPushButton, QGroupBox, QMessageBox
)
from PyQt6.QtCore import Qt

class CapitalPanel(QWidget):
    def __init__(self, strategy_manager, parent=None):
        super().__init__(parent)
        self.strategy_manager = strategy_manager
        self.setWindowTitle("Управление капиталом")
        self.resize(400, 300)
        self.layout = QVBoxLayout(self)
        self.total_label = QLabel()
        self.layout.addWidget(self.total_label)
        self.strategy_widgets = {}  # name -> {'spin': QSpinBox, 'info': QLabel}
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.refresh)
        self.layout.addWidget(self.refresh_btn)
        self.apply_btn = QPushButton("Применить")
        self.apply_btn.clicked.connect(self.apply_changes)
        self.layout.addWidget(self.apply_btn)
        self.refresh()

    def refresh(self):
        # Удаляем старые виджеты стратегий
        for w in self.strategy_widgets.values():
            w['group'].deleteLater()
        self.strategy_widgets.clear()

        cm = self.strategy_manager.capital_manager
        self.total_label.setText(f"Общий капитал: {cm.total_capital:.2f}")

        # Создаём виджеты для каждой стратегии
        for name in self.strategy_manager._strategies.items():
            group = QGroupBox(f"{name}") #({strategy.symbol})
            vbox = QVBoxLayout(group)
            hbox = QHBoxLayout()
            hbox.addWidget(QLabel("Доля:"))
            spin = QSpinBox()
            spin.setRange(0, 1000)
            current_share = cm.get_share(name)  # нужен метод в CapitalManager
            spin.setValue(current_share)
            hbox.addWidget(spin)
            vbox.addLayout(hbox)

            info_label = QLabel()
            vbox.addWidget(info_label)
            self.layout.addWidget(group)
            self.strategy_widgets[name] = {'group': group, 'spin': spin, 'info': info_label}

        self.update_info()

    def update_info(self):
        cm = self.strategy_manager.capital_manager
        for name, w in self.strategy_widgets.items():
            share = w['spin'].value()
            allocated = cm.total_capital * share / max(1, sum(w['spin'].value() for w in self.strategy_widgets.values()))
            available = cm.get_available_capital(name)
            w['info'].setText(f"Выделено: {allocated:.2f} | Доступно: {available:.2f}")

        # Обновляем суммы
        total_shares = sum(w['spin'].value() for w in self.strategy_widgets.values())
        if total_shares > 0:
            for name, w in self.strategy_widgets.items():
                pct = w['spin'].value() / total_shares * 100
                w['info'].setText(w['info'].text() + f" ({pct:.1f}%)")

    def apply_changes(self):
        cm = self.strategy_manager.capital_manager
        shares = {name: w['spin'].value() for name, w in self.strategy_widgets.items()}
        total = sum(shares.values())
        if total == 0:
            QMessageBox.warning(self, "Ошибка", "Сумма долей не может быть 0")
            return
        # Устанавливаем доли в капитале (нужен метод set_share)
        for name, share in shares.items():
            cm.set_share(name, share)
        self.refresh()