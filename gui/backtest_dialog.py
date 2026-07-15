import asyncio
import threading
from datetime import datetime, timedelta
import pandas as pd
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QPushButton, QLabel, QProgressBar, QTableWidget, QTableWidgetItem, QTabWidget,
    QWidget
)
import pyqtgraph as pg
from core.commission import FixedCommission

from core.historical_data import HistoricalDataLoader
from core.backtest_engine import BacktestEngine
from strategies import STRATEGY_REGISTRY

class BacktestDialog(QDialog):
    def __init__(self, event_bus, async_loop, parent=None):
        super().__init__(parent)
        self.event_bus = event_bus
        self.async_loop = async_loop
        self.setWindowTitle("Бэктест")
        self.resize(800, 600)

        main_layout = QVBoxLayout(self)

        # Форма настроек
        form = QFormLayout()
        self.ticker_edit = QLineEdit()
        form.addRow("Тикер:", self.ticker_edit)

        self.data_dir_edit = QLineEdit("C:/Users/Mvsol/Desktop/data/United")
        form.addRow("Папка с данными:", self.data_dir_edit)

        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(STRATEGY_REGISTRY.keys())
        form.addRow("Стратегия:", self.strategy_combo)

        self.capital_edit = QLineEdit("100000")
        form.addRow("Начальный капитал:", self.capital_edit)

        today = datetime.now()
        one_month_ago = today - timedelta(days=30)
        self.start_date_edit = QLineEdit(one_month_ago.strftime('%Y%m%d'))
        self.end_date_edit = QLineEdit(today.strftime('%Y%m%d'))
        form.addRow("Дата начала (YYYYMMDD):", self.start_date_edit)
        form.addRow("Дата конца:", self.end_date_edit)
        self.commission_edit = QLineEdit("0.0")
        form.addRow("Комиссия (руб. за сделку):", self.commission_edit)

        main_layout.addLayout(form)

        # Прогресс
        self.progress = QProgressBar()
        main_layout.addWidget(self.progress)
        self.status_label = QLabel("")
        main_layout.addWidget(self.status_label)

        # Кнопки
        btn_layout = QHBoxLayout()
        start_btn = QPushButton("Запустить")
        start_btn.clicked.connect(self.on_start)
        btn_layout.addWidget(start_btn)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

        # Вкладки результатов
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Вкладка метрик
        self.metrics_table = QTableWidget()
        self.metrics_table.setColumnCount(2)
        self.metrics_table.setHorizontalHeaderLabels(["Метрика", "Значение"])
        self.tabs.addTab(self.metrics_table, "Метрики")

        # Вкладка графика
        graph_tab = QWidget()
        graph_layout = QVBoxLayout(graph_tab)
        self.equity_plot = pg.PlotWidget(title="Эквити", axisItems={'bottom': pg.DateAxisItem()})
        graph_layout.addWidget(self.equity_plot)
        self.tabs.addTab(graph_tab, "График")

        # Вкладка сделок
        self.trades_table = QTableWidget()
        self.trades_table.setColumnCount(7)
        self.trades_table.setHorizontalHeaderLabels(
            ["Время", "Тип", "Цена", "Объём", "Комиссия", "PnL", "Причина"]
        )
        self.tabs.addTab(self.trades_table, "Сделки")

        #######   эту часть писала яна обрати внимание!!!!!!!!!! ########

    def on_start(self):
        ticker = self.ticker_edit.text().strip()
        data_dir = self.data_dir_edit.text().strip()
        class_name = self.strategy_combo.currentText()
        capital = float(self.capital_edit.text())
        start_date = self.start_date_edit.text().strip()
        end_date = self.end_date_edit.text().strip()
        comm = float(self.commission_edit.text())
        commission_model = FixedCommission(comm)
        try:
            loader = HistoricalDataLoader(data_dir)
            data = loader.load_ticker(ticker, start_date=start_date, end_date=end_date)
        except Exception as e:
            self.status_label.setText(f"Ошибка: {e}")
            return

        if data.empty:
            self.status_label.setText("Нет данных за указанный период")
            return

        self.status_label.setText(f"Загружено свечей: {len(data)}")

        strategy_cls = STRATEGY_REGISTRY[class_name]
        params = {'name': f"BT_{ticker}", 'symbol': ticker, 'timeframes': ['1m']}
        engine = BacktestEngine(
            data={ticker: data},
            strategy_class=strategy_cls,
            strategy_params=params,
            initial_capital=capital,
            commission=commission_model
        )

        self.progress.setMaximum(len(data))
        self.progress.setValue(0)

        def run_bt():
            try:
                result = engine.run(
                    progress_callback=lambda i, total: self.async_loop.run_coroutine(
                        self._update_progress(i)
                    )
                )
                self.async_loop.run_coroutine(self._show_results(result))
            except Exception as e:
                self.async_loop.run_coroutine(self._show_error(str(e)))

        threading.Thread(target=run_bt, daemon=True).start()

    async def _update_progress(self, value):
        self.progress.setValue(value)

    async def _show_results(self, result):
        if 'error' in result:
            self.status_label.setText(f"Ошибка: {result['error']}")
            return

        self.status_label.setText(f"Готово. Итоговая эквити: {result['final_equity']:.2f}")

        # Метрики
        metrics = result['metrics']
        self.metrics_table.setRowCount(len(metrics))
        for i, (key, value) in enumerate(metrics.items()):
            self.metrics_table.setItem(i, 0, QTableWidgetItem(key))
            formatted = f"{value:.4f}" if isinstance(value, float) else str(value)
            self.metrics_table.setItem(i, 1, QTableWidgetItem(formatted))

        # График эквити
        eq_df = result['equity_curve']
        if not eq_df.empty:
            self.equity_plot.clear()
            x = eq_df['timestamp'].apply(lambda t: t.timestamp()).values
            y = eq_df['equity'].values
            self.equity_plot.plot(x, y, pen='g', name='Equity')

            # Маркеры сделок
            if result['trades']:
                trade_times = [t.entry_time.timestamp() for t in result['trades']]
                # Определим индекс ближайшего значения эквити к моменту сделки
                trade_y = [eq_df['equity'].iloc[(eq_df['timestamp'] - t.entry_time).abs().argmin()] 
                           for t in result['trades']]
                self.equity_plot.plot(trade_times, trade_y, pen=None, symbol='o', symbolBrush='r')

        # Таблица сделок
        trades = result['trades']
        self.trades_table.setRowCount(len(trades))
        for i, t in enumerate(trades):
            self.trades_table.setItem(i, 0, QTableWidgetItem(str(t.entry_time)))
            self.trades_table.setItem(i, 1, QTableWidgetItem(t.direction))
            self.trades_table.setItem(i, 2, QTableWidgetItem(f"{t.entry_price:.2f}"))
            self.trades_table.setItem(i, 3, QTableWidgetItem(f"{t.volume:.2f}"))
            self.trades_table.setItem(i, 4, QTableWidgetItem(f"{t.commission:.2f}"))
            self.trades_table.setItem(i, 5, QTableWidgetItem(f"{t.pnl:.2f}"))
            self.trades_table.setItem(i, 6, QTableWidgetItem(t.exit_reason))

    async def _show_error(self, msg):
        self.status_label.setText(f"Ошибка: {msg}")
