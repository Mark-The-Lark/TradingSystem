import asyncio
import logging
from concurrent.futures import Future
from PyQt6.QtWidgets import (
    QMainWindow, QMenu, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QApplication
)
from PyQt6.QtCore import QTimer, Qt, QMetaObject, Q_ARG
from core.strategy_manager import StrategyManager
from core.events import EventBus
from gui.add_strategy_dialog import AddStrategyDialog
from gui.detail_panel import DetailPanel
from gui.portfolio_backtest_dialog import PortfolioBacktestDialog
from PyQt6.QtWidgets import QMenu
from core.strategy_registry import StrategyRegistry
logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, event_bus: EventBus, strategy_manager: StrategyManager, registry: StrategyRegistry, async_loop):
        super().__init__()
        self.event_bus = event_bus
        self.strategy_manager = strategy_manager
        self.registry = registry
        self.async_loop = async_loop
        self.setWindowTitle("Торговая система")
        self.resize(1200, 700)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Панель управления
        control_layout = QHBoxLayout()
        self.start_all_btn = QPushButton("Запустить все")
        self.stop_all_btn = QPushButton("Остановить все")
        self.add_btn = QPushButton("Добавить стратегию")
        control_layout.addWidget(self.start_all_btn)
        control_layout.addWidget(self.stop_all_btn)
        control_layout.addWidget(self.add_btn)

        self.backtest_btn = QPushButton("Бэктест")
        control_layout.addWidget(self.backtest_btn)
        self.capital_btn = QPushButton("Капитал")
        control_layout.addWidget(self.capital_btn)
        control_layout.addStretch()
        layout.addLayout(control_layout)
        # Таблица стратегий
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["Имя", "Класс", "Режим", "Позиция", "Эквити", "P&L", "Статус", "Сигналы"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self.open_detail_panel)
        layout.addWidget(self.table)

        self.table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )

        self.table.customContextMenuRequested.connect(
            self.show_context_menu
        )

        # Соединения
        self.start_all_btn.clicked.connect(self.on_start_all)
        self.stop_all_btn.clicked.connect(self.on_stop_all)
        self.backtest_btn.clicked.connect(self.open_backtest_dialog)
        self.capital_btn.clicked.connect(self.open_capital_panel)
        self.add_btn.clicked.connect(self.on_add_strategy)

        # Таймер обновления таблицы
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_table)
        self.timer.start(2000)

        self.detail_panel = None
        self.capital_panel = None
        self.refresh_table()

    def _run_async(self, coro):
        """Запускает корутину в фоновом asyncio-цикле и блокирующе ждёт результата."""
        future = self.async_loop.run_coroutine(coro)
        return future.result()

    def refresh_table(self):
        snapshots = self.strategy_manager.get_all_snapshots()
        self.table.setRowCount(len(snapshots))
        for i, snap in enumerate(snapshots):
            self.table.setItem(i, 0, QTableWidgetItem(snap['name']))
            strategy = self.strategy_manager._strategies.get(snap['name'])
            class_name = type(strategy).__name__ if strategy else ""
            self.table.setItem(i, 1, QTableWidgetItem(class_name))
            self.table.setItem(i, 2, QTableWidgetItem(snap['mode']))
            self.table.setItem(i, 3, QTableWidgetItem(snap.get('position_str', '')))

            equity_item = QTableWidgetItem(f"{snap['equity']:.2f}")
            equity_color = Qt.GlobalColor.green if snap['equity'] > 0 else Qt.GlobalColor.red
            equity_item.setForeground(equity_color)
            self.table.setItem(i, 4, equity_item)

            pnl = snap.get('pnl', 0.0)
            pnl_item = QTableWidgetItem(f"{pnl:.2f}")
            pnl_color = Qt.GlobalColor.green if pnl >= 0 else Qt.GlobalColor.red
            pnl_item.setForeground(pnl_color)
            self.table.setItem(i, 5, pnl_item)

            self.table.setItem(i, 6, QTableWidgetItem(snap['status']))
            self.table.setItem(i, 7, QTableWidgetItem(str(snap['signals'])))

    def selected_strategy_name(self):
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 0)
            return item.text() if item else None
        return None

    # --- Обработчики кнопок ---
    def on_start_all(self):
        self._run_async(self.strategy_manager.start_all())

    def on_stop_all(self):
        self._run_async(self.strategy_manager.stop_all())

    def on_add_strategy(self):
        dialog = AddStrategyDialog(self.registry, parent=self)
        if dialog.exec():
            try:
                name = dialog.name_edit.text().strip()
                if not name:
                    QMessageBox.warning(self, 'Ошибка', 'Имя не может быть пустым')
                    return

                strategy_class = dialog.get_selected_class()
                if not strategy_class:
                    QMessageBox.warning(self, "Ошибка", "Выберите класс стратегии")
                    return

                strategy = strategy_class(
                    name=name,
                    event_bus=self.event_bus,
                    order_manager=self.strategy_manager.order_manager,
                )

                self._run_async(self.strategy_manager.add_strategy(strategy))
                self.refresh_table()
                logger.info(f"Стратегия {name} добавлена")
            except Exception as e:
                logger.exception("Ошибка добавления стратегии")
                QMessageBox.critical(self, "Ошибка", f"Не удалось добавить стратегию: {e}")
                
    #КОНТЕКСТ МЕНЮ ОТ ЯНЫЫ
    def show_context_menu(self, pos):
        menu = QMenu(self)

        add_action = menu.addAction("➕ Добавить стратегию...")
        menu.addSeparator()

        row = self.table.rowAt(pos.y())
        if row >= 0:
            self.table.selectRow(row)
            start_action = menu.addAction("▶ Запустить")
            stop_action = menu.addAction("⏹ Остановить")
            menu.addSeparator()
            remove_action = menu.addAction("🗑 Удалить")
        else:
            start_action = stop_action = remove_action = None

        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        if action == add_action:
            self.on_add_strategy()
        elif action is not None and action == start_action:
            self.on_start_selected()
        elif action is not None and action == stop_action:
            self.on_stop_selected()
        elif action is not None and action == remove_action:
            self.on_remove_selected()

    def on_stop_selected(self):
        name = self.selected_strategy_name()
        if name:
            self._run_async(self.strategy_manager.stop_strategy(name))
            self.refresh_table()

    def on_start_selected(self):
        name = self.selected_strategy_name()
        if name:
            self._run_async(self.strategy_manager.start_strategy(name))
            self.refresh_table()

    def on_remove_selected(self):
        name = self.selected_strategy_name()
        if name:
            self._run_async(self.strategy_manager.remove_strategy(name))
            self.refresh_table()
            if self.detail_panel and self.detail_panel.strategy_name == name:
                self.detail_panel.close()
                self.detail_panel = None

    def open_detail_panel(self, row, col):
        name = self.table.item(row, 0).text()
        if self.detail_panel and self.detail_panel.strategy_name == name:
            self.detail_panel.show()
            self.detail_panel.raise_()
        else:
            self.detail_panel = DetailPanel(name, self.strategy_manager,  self.async_loop)
            self.detail_panel.show()

    def open_backtest_dialog(self):
        dialog = PortfolioBacktestDialog(self.event_bus, self.async_loop, parent=self)
        dialog.exec()

    def open_capital_panel(self):
        if self.capital_panel is None:
            from gui.capital_panel import CapitalPanel
            self.capital_panel = CapitalPanel(self.strategy_manager)
        self.capital_panel.show()
        self.capital_panel.raise_()
        self.capital_panel.refresh()

    def closeEvent(self, event):
        # Собираем запущенные стратегии с ненулевыми позициями
        active_positions = []
        for name, s in self.strategy_manager._strategies.items():
            pos_parts = [f"{sym}:{pos:.2f}" for sym, pos in s.positions.items() if pos != 0]
            if pos_parts:
                active_positions.append(f"{name}: {', '.join(pos_parts)}")

        msg = ""
        if active_positions:
            msg = "У следующих стратегий открыты позиции:\n" + "\n".join(active_positions) + "\n\n"
            msg += "Остановить стратегии и выйти?"
        else:
            msg = "Вы уверены что хотите выйти?"

        reply = QMessageBox.question(
            self, "Подтверждение выхода", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.No:
            event.ignore()
            return

        self._run_async(self.strategy_manager.stop_all())
        event.accept()
