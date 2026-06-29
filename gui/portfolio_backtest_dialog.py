

import asyncio
import logging
from datetime import datetime, timedelta
import pandas as pd
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QPushButton, QLabel, QProgressBar, QTableWidget, QTableWidgetItem,
    QTabWidget, QWidget, QDoubleSpinBox, QMessageBox, QScrollArea,
    QAbstractItemView
)
from PyQt6.QtCore import QTimer, Qt
import pyqtgraph as pg

from core.historical_data import HistoricalDataLoader
from core.portfolio_backtest_engine import PortfolioBacktestEngine
from core.commission import FixedCommission
from strategies import STRATEGY_REGISTRY
from core.mocks import MockEventBus, MockOrderManager

logger = logging.getLogger(__name__)

class PortfolioBacktestDialog(QDialog):
    def __init__(self, event_bus, async_loop, parent=None):
        super().__init__(parent)
        self.event_bus = event_bus
        self.async_loop = async_loop
        self.setWindowTitle("Портфельный бэктест")
        self.resize(1000, 800)
        self.setMinimumSize(800, 600)

        main_layout = QVBoxLayout(self)

        # --- Таблица стратегий ---
        table_label = QLabel("Стратегии в портфеле:")
        main_layout.addWidget(table_label)

        self.strategy_table = QTableWidget()
        self.strategy_table.setColumnCount(5)
        self.strategy_table.setHorizontalHeaderLabels([
            "Класс", "Имя", "Тикер(ы)", "Параметры", "Доля (%)"
        ])
        self.strategy_table.horizontalHeader().setStretchLastSection(True)
        self.strategy_table.setMinimumHeight(150)
        self.strategy_table.verticalHeader().setVisible(False)
        self.strategy_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.strategy_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # При клике на строку результатов будем переключать вкладки
        self.strategy_table.cellClicked.connect(self.on_strategy_row_clicked)
        main_layout.addWidget(self.strategy_table)

        btn_layout = QHBoxLayout()
        self.add_strategy_btn = QPushButton("Добавить стратегию")
        self.add_strategy_btn.clicked.connect(self.add_strategy_row)
        btn_layout.addWidget(self.add_strategy_btn)
        self.remove_strategy_btn = QPushButton("Удалить")
        self.remove_strategy_btn.clicked.connect(self.remove_strategy_row)
        btn_layout.addWidget(self.remove_strategy_btn)
        main_layout.addLayout(btn_layout)

        # --- Общие настройки ---
        settings_layout = QFormLayout()
        self.capital_edit = QLineEdit("100000")
        settings_layout.addRow("Начальный капитал:", self.capital_edit)

        self.commission_edit = QLineEdit("0.0")
        settings_layout.addRow("Комиссия (руб. за сделку):", self.commission_edit)

        today = datetime.now()
        one_month_ago = today - timedelta(days=30)
        self.start_date_edit = QLineEdit(one_month_ago.strftime('%Y%m%d'))
        self.end_date_edit = QLineEdit(today.strftime('%Y%m%d'))
        settings_layout.addRow("Дата начала (YYYYMMDD):", self.start_date_edit)
        settings_layout.addRow("Дата конца:", self.end_date_edit)

        self.data_dir_edit = QLineEdit("C:/Users/Mvsol/Desktop/data/United")
        settings_layout.addRow("Папка с данными:", self.data_dir_edit)

        main_layout.addLayout(settings_layout)

        # --- Прогресс ---
        self.progress = QProgressBar()
        main_layout.addWidget(self.progress)
        self.status_label = QLabel("")
        main_layout.addWidget(self.status_label)

        # --- Кнопки запуска ---
        action_layout = QHBoxLayout()
        self.start_btn = QPushButton("Запустить")
        self.start_btn.clicked.connect(self.on_start)
        action_layout.addWidget(self.start_btn)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.reject)
        action_layout.addWidget(close_btn)
        main_layout.addLayout(action_layout)

        # --- Вкладки результатов (внутри скролла) ---
        self.results_tabs = QTabWidget()
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.results_tabs)
        main_layout.addWidget(scroll_area)

        # Вкладка портфеля
        self.portfolio_tab = QWidget()
        portfolio_layout = QVBoxLayout(self.portfolio_tab)
        self.portfolio_plot = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()}, title="Эквити портфеля")
        self.portfolio_plot.addLegend()
        self.portfolio_curve = self.portfolio_plot.plot(pen='g', name='Equity')
        portfolio_layout.addWidget(self.portfolio_plot)
        self.portfolio_metrics_table = QTableWidget()
        self.portfolio_metrics_table.setColumnCount(2)
        self.portfolio_metrics_table.setHorizontalHeaderLabels(["Метрика", "Значение"])
        self.portfolio_metrics_table.horizontalHeader().setStretchLastSection(True)
        portfolio_layout.addWidget(self.portfolio_metrics_table)
        self.results_tabs.addTab(self.portfolio_tab, "Портфель")

        # Индивидуальные вкладки будут добавляться динамически
        self.individual_tabs = {}  # name -> QWidget

    # ========== Работа с таблицей стратегий ==========
    def add_strategy_row(self):
        row = self.strategy_table.rowCount()
        self.strategy_table.insertRow(row)

        # Выбор класса
        class_combo = QComboBox()
        class_combo.addItems(STRATEGY_REGISTRY.keys())
        self.strategy_table.setCellWidget(row, 0, class_combo)

        # Имя (автоматическое)
        name_edit = QLineEdit(f"strat_{row+1}")
        self.strategy_table.setCellWidget(row, 1, name_edit)

        # Тикеры – из subscriptions временного экземпляра
        cls = STRATEGY_REGISTRY[class_combo.currentText()]
        try:
            temp = cls(name="tmp", event_bus=MockEventBus(), order_manager=MockOrderManager())
            tickers = ", ".join(sorted({s for s, _ in temp.subscriptions}))
        except:
            tickers = "?"
        ticker_label = QLineEdit(tickers)
        self.strategy_table.setCellWidget(row, 2, ticker_label)

        # Параметры – можно задать через строку key=value,...
        # Для SMACrossoverStrategy предложим fast=10,slow=30
        params_default = ""
        if cls.__name__ == "SMACrossoverStrategy":
            params_default = "fast=10,slow=30"
        params_edit = QLineEdit(params_default)
        self.strategy_table.setCellWidget(row, 3, params_edit)

        # Доля капитала
        share_spin = QDoubleSpinBox()
        share_spin.setRange(0, 100)
        share_spin.setValue(100 // (row+1))
        share_spin.setSuffix("%")
        self.strategy_table.setCellWidget(row, 4, share_spin)

    def remove_strategy_row(self):
        row = self.strategy_table.currentRow()
        if row >= 0:
            self.strategy_table.removeRow(row)

    def on_strategy_row_clicked(self, row, col):
        """Переключаем вкладку результатов на выбранную стратегию."""
        name_item = self.strategy_table.cellWidget(row, 1)
        if not name_item:
            return
        name = name_item.text().strip()
        for i in range(self.results_tabs.count()):
            if self.results_tabs.tabText(i) == name:
                self.results_tabs.setCurrentIndex(i)
                break

    # ========== Запуск бэктеста ==========
    def on_start(self):
        # Сбор конфигураций из таблицы
        strategy_configs = []
        for row in range(self.strategy_table.rowCount()):
            class_combo = self.strategy_table.cellWidget(row, 0)
            name_edit = self.strategy_table.cellWidget(row, 1)
            ticker_edit = self.strategy_table.cellWidget(row, 2)
            params_edit = self.strategy_table.cellWidget(row, 3)
            share_spin = self.strategy_table.cellWidget(row, 4)
            if not all([class_combo, name_edit, ticker_edit, params_edit, share_spin]):
                continue

            class_name = class_combo.currentText()
            name = name_edit.text().strip()
            tickers_str = ticker_edit.text().strip()
            params_str = params_edit.text().strip()
            share = share_spin.value()

            if not name:
                QMessageBox.warning(self, "Ошибка", "Имя стратегии не может быть пустым")
                return
            cls = STRATEGY_REGISTRY.get(class_name)
            if not cls:
                continue

            # Разбор тикеров и таймфреймов
            subscriptions = []
            if tickers_str:
                # Ожидаем формат: "AAPL, GOOGL" или "AAPL:1m, GOOGL:5m"
                parts = [p.strip() for p in tickers_str.split(',')]
                for part in parts:
                    if ':' in part:
                        sym, tf = part.split(':')
                        subscriptions.append((sym.strip(), tf.strip()))
                    else:
                        subscriptions.append((part, '1m'))  # по умолчанию 1m
            else:
                # Попытаемся получить из временного экземпляра
                temp = cls(name=name, event_bus=MockEventBus(), order_manager=MockOrderManager())
                subscriptions = temp.subscriptions

            # Разбор параметров
            kwargs = {}
            if params_str:
                for pair in params_str.split(','):
                    if '=' in pair:
                        k, v = pair.split('=')
                        k = k.strip()
                        v = v.strip()
                        # Простейшее преобразование типов
                        try:
                            v = float(v) if '.' in v else int(v)
                        except:
                            pass
                        kwargs[k] = v

            strategy_configs.append({
                'class': cls,
                'name': name,
                'allocation_pct': share,
                'subscriptions': subscriptions,
                'mode': 'AUTO',
                'kwargs': kwargs
            })

        if not strategy_configs:
            QMessageBox.warning(self, "Ошибка", "Добавьте хотя бы одну стратегию")
            return

        # Загрузка данных
        data_dir = self.data_dir_edit.text().strip()
        start_date = self.start_date_edit.text().strip()
        end_date = self.end_date_edit.text().strip()
        loader = HistoricalDataLoader(data_dir)

        # Собираем все уникальные тикеры из подписок
        tickers = set()
        for cfg in strategy_configs:
            for sym, _ in cfg['subscriptions']:
                tickers.add(sym)
        data = {}
        for t in tickers:
            try:
                df = loader.load_ticker(t, start_date=start_date, end_date=end_date)
                if not df.empty:
                    data[t] = df
                else:
                    QMessageBox.warning(self, "Ошибка", f"Нет данных для {t}")
                    return
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки {t}: {e}")
                return

        capital = float(self.capital_edit.text())
        comm = float(self.commission_edit.text())
        engine = PortfolioBacktestEngine(
            data=data,
            strategy_configs=strategy_configs,
            initial_capital=capital,
            commission=FixedCommission(comm)
        )

        self.progress.setMaximum(len(data[tickers.pop()]) if tickers else 1)
        self.progress.setValue(0)
        self.status_label.setText("Выполняется...")

        import threading
        def run():
            try:
                result = engine.run(progress_callback=lambda i, total: self.async_loop.run_coroutine(
                    self._update_progress(i)
                ))
                self.async_loop.run_coroutine(self._show_results(result))
            except Exception as e:
                self.async_loop.run_coroutine(self._show_error(str(e)))

        threading.Thread(target=run, daemon=True).start()

    async def _update_progress(self, value):
        self.progress.setValue(value)

    async def _show_results(self, result):
        self.status_label.setText("Готово")
        # Портфель
        eq_df = result['portfolio_equity_curve']
        if not eq_df.empty:
            self.portfolio_curve.setData(eq_df['timestamp'].apply(lambda t: t.timestamp()).values, eq_df['equity'].values)

        metrics = result['portfolio_metrics']
        self.portfolio_metrics_table.setRowCount(len(metrics))
        for i, (key, value) in enumerate(metrics.items()):
            self.portfolio_metrics_table.setItem(i, 0, QTableWidgetItem(key))
            self.portfolio_metrics_table.setItem(i, 1, QTableWidgetItem(f"{value:.4f}"))

        # Удаляем старые индивидуальные вкладки
        for name, tab in list(self.individual_tabs.items()):
            self.results_tabs.removeTab(self.results_tabs.indexOf(tab))
        self.individual_tabs.clear()

        # Создаём индивидуальные вкладки
        for name, ind_result in result['individual_results'].items():
            tab = QWidget()
            layout = QVBoxLayout(tab)
            plot = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()}, title=f"Эквити {name}")
            eq_df = ind_result['equity_curve']
            if not eq_df.empty:
                plot.plot(eq_df['timestamp'].apply(lambda t: t.timestamp()).values, eq_df['equity'].values, pen='g')
            layout.addWidget(plot)

            metrics_table = QTableWidget()
            metrics_table.setColumnCount(2)
            metrics_table.setHorizontalHeaderLabels(["Метрика", "Значение"])
            metrics_table.horizontalHeader().setStretchLastSection(True)
            ind_metrics = ind_result['metrics']
            metrics_table.setRowCount(len(ind_metrics))
            for i, (key, value) in enumerate(ind_metrics.items()):
                metrics_table.setItem(i, 0, QTableWidgetItem(key))
                metrics_table.setItem(i, 1, QTableWidgetItem(f"{value:.4f}"))
            layout.addWidget(metrics_table)

            self.results_tabs.addTab(tab, name)
            self.individual_tabs[name] = tab

    async def _show_error(self, msg):
        self.status_label.setText(f"Ошибка: {msg}")