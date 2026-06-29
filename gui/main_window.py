# import asyncio
# import logging
# from PyQt6.QtWidgets import (
#     QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
#     QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
# )
# from PyQt6.QtCore import QTimer
# from core.strategy_manager import StrategyManager
# from core.events import EventBus
# from gui.add_strategy_dialog import AddStrategyDialog
# from gui.detail_panel import DetailPanel

# logger = logging.getLogger(__name__)

# class MainWindow(QMainWindow):
#     def __init__(self, event_bus: EventBus, strategy_manager: StrategyManager, registry: dict):
#         super().__init__()
#         self.event_bus = event_bus
#         self.strategy_manager = strategy_manager
#         self.registry = registry
#         self.setWindowTitle("Торговая система")
#         self.resize(1200, 700)

#         central = QWidget()
#         self.setCentralWidget(central)
#         layout = QVBoxLayout(central)

#         # Панель управления
#         control_layout = QHBoxLayout()
#         self.start_all_btn = QPushButton("Запустить все")
#         self.stop_all_btn = QPushButton("Остановить все")
#         self.add_btn = QPushButton("Добавить стратегию")
#         control_layout.addWidget(self.start_all_btn)
#         control_layout.addWidget(self.stop_all_btn)
#         control_layout.addWidget(self.add_btn)
#         control_layout.addStretch()
#         layout.addLayout(control_layout)

#         # Таблица
#         self.table = QTableWidget()
#         self.table.setColumnCount(7)
#         self.table.setHorizontalHeaderLabels(["Имя", "Символ", "Режим", "Позиция", "Эквити", "Статус", "Сигналы"])
#         self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
#         self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
#         self.table.cellDoubleClicked.connect(self.open_detail_panel)
#         layout.addWidget(self.table)

#         # Кнопки действий
#         action_layout = QHBoxLayout()
#         self.stop_btn = QPushButton("Стоп")
#         self.start_btn = QPushButton("Старт")
#         self.remove_btn = QPushButton("Удалить")
#         action_layout.addWidget(self.stop_btn)
#         action_layout.addWidget(self.start_btn)
#         action_layout.addWidget(self.remove_btn)
#         action_layout.addStretch()
#         layout.addLayout(action_layout)

#         # Подключаем синхронные слоты
#         self.start_all_btn.clicked.connect(self.on_start_all)
#         self.stop_all_btn.clicked.connect(self.on_stop_all)
#         self.add_btn.clicked.connect(self.on_add_strategy)
#         self.stop_btn.clicked.connect(self.on_stop_selected)
#         self.start_btn.clicked.connect(self.on_start_selected)
#         self.remove_btn.clicked.connect(self.on_remove_selected)

#         # Таймер обновления таблицы
#         self.timer = QTimer()
#         self.timer.timeout.connect(self.refresh_table)
#         self.timer.start(2000)

#         self.detail_panel = None
#         self.refresh_table()

#     def _run_async(self, coro):
#         print("DEBUG: _run_async called")
#         loop = asyncio.get_event_loop()
#         if loop.is_closed():
#             print("DEBUG: loop is closed")
#             return
#         task = loop.create_task(coro)
#         def handle_exception(t):
#             if t.exception():
#                 import traceback
#                 traceback.print_exception(type(t.exception()), t.exception(), t.__traceback__)
#         task.add_done_callback(handle_exception)
#         print("DEBUG: task created, id:", id(task))

#     # Слоты-обёртки
#     def on_start_all(self):
#         self._run_async(self._start_all())

#     async def _start_all(self):
#         try:
#             await self.strategy_manager.start_all()
#         except Exception as e:
#             QMessageBox.critical(self, "Ошибка", str(e))

#     def on_stop_all(self):
#         self._run_async(self._stop_all())

#     async def _stop_all(self):
#         try:
#             await self.strategy_manager.stop_all()
#         except Exception as e:
#             QMessageBox.critical(self, "Ошибка", str(e))

#     def on_add_strategy(self):
#         print("DEBUG: on_add_strategy CALLED")
#         dialog = AddStrategyDialog(self.registry, parent=self)
#         if dialog.exec():
#             print("DEBUG: dialog accepted")
#             try:
#                 name = dialog.name_edit.text().strip()
#                 symbol = dialog.symbol_edit.text().strip()
#                 mode = dialog.mode_combo.currentText()
#                 timeframes = [tf.strip() for tf in dialog.timeframes_edit.text().split(',') if tf.strip()]
#                 class_name = dialog.class_combo.currentText()
#                 cls = self.registry.get(class_name)
#                 if not cls:
#                     QMessageBox.warning(self, "Ошибка", f"Класс {class_name} не найден")
#                     return
#                 strategy = cls(
#                     name=name,
#                     symbol=symbol,
#                     event_bus=self.event_bus,
#                     order_manager=self.strategy_manager.order_manager,
#                     mode=mode,
#                     timeframes=timeframes
#                 )
#                 print(f"DEBUG: strategy created: {strategy.name}")
#                 self._run_async(self._add_strategy(strategy))
#             except Exception as e:
#                 import traceback
#                 traceback.print_exc()
#                 QMessageBox.critical(self, "Ошибка", str(e))
#         else:
#             print("DEBUG: dialog rejected")

#     async def _add_strategy(self, strategy):
#         print(f"DEBUG: _add_strategy ENTER for {strategy.name}")  # синхронно до первого await
#         try:
#             await self.strategy_manager.add_strategy(strategy)
#             print("DEBUG: add_strategy completed")
#             self.refresh_table()
#             logger.info(f"Стратегия {strategy.name} добавлена")
#         except Exception as e:
#             import traceback
#             traceback.print_exc()
#             QMessageBox.critical(self, "Ошибка", f"Не удалось добавить стратегию: {e}")

#     def on_stop_selected(self):
#         name = self.selected_strategy_name()
#         if name:
#             self._run_async(self._stop_strategy(name))

#     async def _stop_strategy(self, name):
#         await self.strategy_manager.stop_strategy(name)
#         self.refresh_table()

#     def on_start_selected(self):
#         name = self.selected_strategy_name()
#         if name:
#             self._run_async(self._start_strategy(name))

#     async def _start_strategy(self, name):
#         await self.strategy_manager.start_strategy(name)
#         self.refresh_table()

#     def on_remove_selected(self):
#         name = self.selected_strategy_name()
#         if name:
#             self._run_async(self._remove_strategy(name))

#     async def _remove_strategy(self, name):
#         await self.strategy_manager.remove_strategy(name)
#         self.refresh_table()
#         if self.detail_panel and self.detail_panel.strategy_name == name:
#             self.detail_panel.close()
#             self.detail_panel = None

#     def refresh_table(self):
#         snapshots = self.strategy_manager.get_all_snapshots()
#         self.table.setRowCount(len(snapshots))
#         for i, snap in enumerate(snapshots):
#             self.table.setItem(i, 0, QTableWidgetItem(snap['name']))
#             self.table.setItem(i, 1, QTableWidgetItem(snap['symbol']))
#             self.table.setItem(i, 2, QTableWidgetItem(snap['mode']))
#             self.table.setItem(i, 3, QTableWidgetItem(str(snap['position'])))
#             self.table.setItem(i, 4, QTableWidgetItem(f"{snap['equity']:.2f}"))
#             self.table.setItem(i, 5, QTableWidgetItem(snap['status']))
#             self.table.setItem(i, 6, QTableWidgetItem(str(snap['signals'])))

#     def selected_strategy_name(self):
#         row = self.table.currentRow()
#         if row >= 0:
#             return self.table.item(row, 0).text()
#         return None

#     def open_detail_panel(self, row, col):
#         name = self.table.item(row, 0).text()
#         if self.detail_panel and self.detail_panel.strategy_name == name:
#             self.detail_panel.show()
#             self.detail_panel.raise_()
#         else:
#             self.detail_panel = DetailPanel(name, self.strategy_manager)
#             self.detail_panel.show()

import asyncio
import logging
from concurrent.futures import Future
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QApplication
)
from PyQt6.QtCore import QTimer, Qt, QMetaObject, Q_ARG
from core.strategy_manager import StrategyManager
from core.events import EventBus
from gui.add_strategy_dialog import AddStrategyDialog
from gui.detail_panel import DetailPanel
from gui.portfolio_backtest_dialog import PortfolioBacktestDialog

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, event_bus: EventBus, strategy_manager: StrategyManager, registry: dict, async_loop):
        super().__init__()
        self.event_bus = event_bus
        self.strategy_manager = strategy_manager
        self.registry = registry
        self.async_loop = async_loop  # экземпляр AsyncLoopThread
        print(f"DEBUG: async_loop type: {type(self.async_loop)}")
        if not hasattr(self.async_loop, 'run_coroutine'):
            raise TypeError("async_loop must be an instance of AsyncLoopThread with run_coroutine method")
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
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # Таблица стратегий
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Имя", "Класс", "Режим", "Позиция", "Эквити", "P&L", "Статус", "Сигналы"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self.open_detail_panel)
        layout.addWidget(self.table)

        # Кнопки действий
        action_layout = QHBoxLayout()
        self.stop_btn = QPushButton("Стоп")
        self.start_btn = QPushButton("Старт")
        self.remove_btn = QPushButton("Удалить")
        action_layout.addWidget(self.stop_btn)
        action_layout.addWidget(self.start_btn)
        action_layout.addWidget(self.remove_btn)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        self.backtest_btn = QPushButton("Бэктест")
        control_layout.addWidget(self.backtest_btn)
        self.backtest_btn.clicked.connect(self.open_backtest_dialog)
        self.capital_btn = QPushButton("Капитал")
        control_layout.addWidget(self.capital_btn)
        self.capital_btn.clicked.connect(self.open_capital_panel)

        # Соединения (обычные слоты)
        self.start_all_btn.clicked.connect(self.on_start_all)
        self.stop_all_btn.clicked.connect(self.on_stop_all)
        self.add_btn.clicked.connect(self.on_add_strategy)
        self.stop_btn.clicked.connect(self.on_stop_selected)
        self.start_btn.clicked.connect(self.on_start_selected)
        self.remove_btn.clicked.connect(self.on_remove_selected)

        # Таймер обновления таблицы (периодически дёргаем refresh_table)
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_table)
        self.timer.start(2000)

        self.detail_panel = None
        self.refresh_table()

    # --- Утилита для вызова асинхронных функций ---
    def _run_async(self, coro):
        """Запускает корутину в фоновом asyncio цикле и дожидается результата (блокирует GUI)."""
        future = self.async_loop.run_coroutine(coro)
        return future.result()  # блокирующий вызов

    # Слот для отображения ошибок из другого потока
    def show_error(self, message):
        QMessageBox.critical(self, "Ошибка", message)

    def refresh_table(self):
        snapshots = self.strategy_manager.get_all_snapshots()
        self.table.setRowCount(len(snapshots))
        for i, snap in enumerate(snapshots):
            self.table.setItem(i, 0, QTableWidgetItem(snap['name']))
            # self.table.setItem(i, 1, QTableWidgetItem(snap['symbol']))
            # self.table.setItem(i, 1, QTableWidgetItem(", ".join(snap.get('symbols', []))))
            strategy = self.strategy_manager._strategies.get(snap['name'])
            class_name = type(strategy).__name__ if strategy else ""
            self.table.setItem(i, 1, QTableWidgetItem(class_name))
            self.table.setItem(i, 2, QTableWidgetItem(snap['mode']))
            # self.table.setItem(i, 3, QTableWidgetItem(str(snap['position'])))
            self.table.setItem(i, 3, QTableWidgetItem(snap.get('position_str', '')))
            # self.table.setItem(i, 4, QTableWidgetItem(f"{snap['equity']:.2f}"))
            equity_item = QTableWidgetItem(f"{snap['equity']:.2f}")
            equity_color = Qt.GlobalColor.green if snap['equity'] > 0 else Qt.GlobalColor.red
            equity_item.setForeground(equity_color)
            self.table.setItem(i, 4, equity_item)
            # self.table.setItem(i, 5, QTableWidgetItem(f"{snap.get('pnl', 0.0):.2f}"))
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
            return self.table.item(row, 0).text()
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
                # symbol = dialog.symbol_edit.text().strip()
                # mode = dialog.mode_combo.currentText()
                # timeframes = [tf.strip() for tf in dialog.timeframes_edit.text().split(',') if tf.strip()]
                class_name = dialog.class_combo.currentText()
                cls = self.registry.get(class_name)
                if not cls:
                    QMessageBox.warning(self, "Ошибка", f"Класс {class_name} не найден")
                    return
                strategy = cls(
                    name=name,
                    # symbol=symbol,
                    event_bus=self.event_bus,
                    order_manager=self.strategy_manager.order_manager,
                    # mode=mode,
                    # timeframes=timeframes
                )
                # Блокируем GUI пока не добавим стратегию (короткая операция)
                self._run_async(self.strategy_manager.add_strategy(strategy))
                self.refresh_table()
                logger.info(f"Стратегия {name} добавлена")
            except Exception as e:
                logger.exception("Ошибка добавления стратегии")
                QMessageBox.critical(self, "Ошибка", f"Не удалось добавить стратегию: {e}")

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
            self.detail_panel = DetailPanel(name, self.strategy_manager)
            self.detail_panel.show()

    def open_backtest_dialog(self):
        dialog = PortfolioBacktestDialog(self.event_bus, self.async_loop, parent=self)
        dialog.exec()

    def closeEvent(self, event):
        # Собираем запущенные стратегии с ненулевыми позициями
        active_positions = []
        for name, s in self.strategy_manager._strategies.items():
            if s._status == 'RUNNING' and s.position != 0:
                active_positions.append(f"{name} ({s.symbol}): {s.position:.2f}")

        # if active_positions:
        msg = "У следующих стратегий открыты позиции:\n" + "\n".join(active_positions)
        msg += "\n\nОстановить стратегии и выйти?"
        reply = QMessageBox.question(
            self, "Подтверждение выхода", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.No:
            event.ignore()
            return

        # Остановка всех стратегий (используем ваш синхронный _run_async)
        async def shutdown():
            await self.strategy_manager.stop_all()

        self._run_async(shutdown())   # дожидается завершения stop_all()
        event.accept()                # разрешаем закрытие окна

    def open_capital_panel(self):
        if not hasattr(self, 'capital_panel') or self.capital_panel is None:
            from gui.capital_panel import CapitalPanel
            self.capital_panel = CapitalPanel(self.strategy_manager)
        self.capital_panel.show()
        self.capital_panel.raise_()
        self.capital_panel.refresh()  # обновить данные