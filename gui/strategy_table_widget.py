from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.strategy_manager import StrategyManager
from core.strategy_registry import StrategyRegistry
from gui.add_strategy_dialog import AddStrategyDialog
import logging

logger = logging.getLogger(__name__)

class StrategyTableWidget(QTableWidget):
    """Таблица со списком стратегий с контекстным меню для управления."""
    
    # Сигнал, когда список стратегий изменился (добавление/удаление)
    strategies_changed = pyqtSignal()

    def __init__(
        self,
        strategy_manager: StrategyManager,
        registry: StrategyRegistry,
        event_bus,
        async_loop,
        parent=None
    ):
        super().__init__(parent)
        self.strategy_manager = strategy_manager
        self.registry = registry
        self.event_bus = event_bus
        self.async_loop = async_loop

        self.setColumnCount(8)
        self.setHorizontalHeaderLabels(
            ["Имя", "Класс", "Режим", "Позиция", "Эквити", "P&L", "Статус", "Сигналы"]
        )
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def refresh(self):
        """Обновляет данные таблицы из StrategyManager."""
        snapshots = self.strategy_manager.get_all_snapshots()
        self.setRowCount(len(snapshots))
        for i, snap in enumerate(snapshots):
            self.setItem(i, 0, QTableWidgetItem(snap['name']))
            strategy = self.strategy_manager._strategies.get(snap['name'])
            class_name = type(strategy).__name__ if strategy else ""
            self.setItem(i, 1, QTableWidgetItem(class_name))
            self.setItem(i, 2, QTableWidgetItem(snap['mode']))
            self.setItem(i, 3, QTableWidgetItem(snap.get('position_str', '')))

            equity_item = QTableWidgetItem(f"{snap['equity']:.2f}")
            equity_color = Qt.GlobalColor.green if snap['equity'] > 0 else Qt.GlobalColor.red
            equity_item.setForeground(equity_color)
            self.setItem(i, 4, equity_item)

            pnl = snap.get('pnl', 0.0)
            pnl_item = QTableWidgetItem(f"{pnl:.2f}")
            pnl_color = Qt.GlobalColor.green if pnl >= 0 else Qt.GlobalColor.red
            pnl_item.setForeground(pnl_color)
            self.setItem(i, 5, pnl_item)

            self.setItem(i, 6, QTableWidgetItem(snap['status']))
            self.setItem(i, 7, QTableWidgetItem(str(snap['signals'])))

    def _run_async(self, coro):
        """Запускает корутину в фоновом asyncio-цикле и ждёт результат."""
        future = self.async_loop.run_coroutine(coro)
        return future.result()

    def selected_strategy_name(self):
        row = self.currentRow()
        if row >= 0:
            item = self.item(row, 0)
            return item.text() if item else None
        return None

    def show_context_menu(self, pos):
        menu = QMenu(self)

        # Добавить стратегию доступно всегда
        add_action = menu.addAction("➕ Добавить стратегию...")
        menu.addSeparator()

        row = self.rowAt(pos.y())
        if row >= 0:
            self.selectRow(row)
            start_action = menu.addAction("▶ Запустить")
            stop_action = menu.addAction("⏹ Остановить")
            menu.addSeparator()
            remove_action = menu.addAction("🗑 Удалить")
        else:
            start_action = stop_action = remove_action = None

        action = menu.exec(self.viewport().mapToGlobal(pos))

        if action == add_action:
            self.on_add_strategy()
        elif action == start_action:
            self.on_start_selected()
        elif action == stop_action:
            self.on_stop_selected()
        elif action == remove_action:
            self.on_remove_selected()

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
                self.refresh()
                self.strategies_changed.emit()
                logger.info(f"Стратегия {name} добавлена")
            except Exception as e:
                logger.exception("Ошибка добавления стратегии")
                QMessageBox.critical(self, "Ошибка", f"Не удалось добавить стратегию: {e}")

    def on_start_selected(self):
        name = self.selected_strategy_name()
        if name:
            self._run_async(self.strategy_manager.start_strategy(name))
            self.refresh()

    def on_stop_selected(self):
        name = self.selected_strategy_name()
        if name:
            self._run_async(self.strategy_manager.stop_strategy(name))
            self.refresh()

    def on_remove_selected(self):
        name = self.selected_strategy_name()
        if name:
            self._run_async(self.strategy_manager.remove_strategy(name))
            self.refresh()
            self.strategies_changed.emit()