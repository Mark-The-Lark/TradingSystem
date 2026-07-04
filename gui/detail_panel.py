
# import logging
# from PyQt6.QtWidgets import (
#     QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPushButton,
#     QTableWidget, QTableWidgetItem, QComboBox, QLabel, QScrollArea
# )
# from PyQt6.QtCore import QTimer, Qt
# import pyqtgraph as pg
# import pandas as pd
# import numpy as np

# logger = logging.getLogger(__name__)
# from pyqtgraph import GraphicsObject, mkPen, mkBrush
# from PyQt6.QtCore import QRectF, QPointF
# import numpy as np

# class CandlestickItem(GraphicsObject):
#     def __init__(self, data=None):
#         super().__init__()
#         self.data = None
#         self.width = 1  # ширина в секундах (по умолчанию 1 минута)
#         self.wick_pen = mkPen('w', width=1)
#         self.body_pen_up = mkPen('g')
#         self.body_brush_up = mkBrush('g')
#         self.body_pen_down = mkPen('r')
#         self.body_brush_down = mkBrush('r')
#         self.setData(data)

#     def setWidth(self, width):
#         self.width = width
#         self.prepareGeometryChange()
#         self.update()

#     def setData(self, data):
#         if data is not None and data.ndim == 2 and data.shape[1] >= 5:
#             self.data = data[:, :5]
#         else:
#             self.data = None
#         self.prepareGeometryChange()
#         self.update()

#     def paint(self, p, opt, widget):
#         if self.data is None or len(self.data) == 0:
#             return
#         x = self.data[:, 0]
#         o = self.data[:, 1]
#         h = self.data[:, 2]
#         l = self.data[:, 3]
#         c = self.data[:, 4]
#         half_width = self.width / 2

#         for i in range(len(x)):
#             t = x[i]
#             open_val = o[i]
#             close_val = c[i]
#             high_val = h[i]
#             low_val = l[i]

#             # Тело свечи
#             if close_val >= open_val:
#                 p.setPen(self.body_pen_up)
#                 p.setBrush(self.body_brush_up)
#             else:
#                 p.setPen(self.body_pen_down)
#                 p.setBrush(self.body_brush_down)
#             rect = QRectF(t - half_width, open_val, self.width, close_val - open_val)
#             p.drawRect(rect)

#             # Wick'и
#             p.setPen(self.wick_pen)
#             p.drawLine(QPointF(t, low_val), QPointF(t, high_val))

#     def boundingRect(self):
#         if self.data is None or len(self.data) == 0:
#             return QRectF()
#         x = self.data[:, 0]
#         h = self.data[:, 2]
#         l = self.data[:, 3]
#         return QRectF(x.min(), l.min(), x.max() - x.min(), h.max() - l.min())

# class SubPlotWidget(QWidget):
#     """Один подграфик с возможностью добавлять/удалять кривые."""
#     def __init__(self, title="", parent=None):
#         super().__init__(parent)
#         self.title = title
#         self.plot = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
#         self.plot.setLabel('left', title)
#         layout = QVBoxLayout(self)
#         layout.setContentsMargins(0, 0, 0, 0)
#         layout.addWidget(self.plot)
#         self.curves = {}  # name -> PlotDataItem (или CandlestickItem)

#     def add_curve(self, name, pen='y'):
#         if name in self.curves:
#             return
#         curve = self.plot.plot([], [], pen=pen, name=name)
#         self.curves[name] = curve
#         return curve

#     def remove_curve(self, name):
#         if name in self.curves:
#             self.plot.removeItem(self.curves[name])
#             del self.curves[name]

#     def clear_curves(self):
#         for name in list(self.curves.keys()):
#             self.remove_curve(name)

#     def set_data(self, name, x, y):
#         if name in self.curves:
#             self.curves[name].setData(x, y)


# class DetailPanel(QWidget):
#     def __init__(self, strategy_name: str, strategy_manager):
#         super().__init__()
#         self.strategy_name = strategy_name
#         self.strategy_manager = strategy_manager
#         self.setWindowTitle(f"Детали: {strategy_name}")
#         self.resize(1200, 800)

#         main_layout = QVBoxLayout(self)

#         # === Информационная панель (позиция, PnL) ===
#         self.info_layout = QHBoxLayout()
#         self.info_labels = {}
#         for key in ['Позиция', 'Цена входа', 'Текущая цена', 'Нереализ. PnL', 'Эквити']:
#             label = QLabel(f"{key}: --")
#             label.setStyleSheet("font-weight: bold; padding: 4px;")
#             self.info_layout.addWidget(label)
#             self.info_labels[key] = label
#         main_layout.addLayout(self.info_layout)

#         # === Панель управления ===
#         control_layout = QHBoxLayout()
#         control_layout.addWidget(QLabel("Таймфрейм:"))
#         self.tf_combo = QComboBox()
#         self.tf_combo.currentTextChanged.connect(self.on_tf_changed)
#         control_layout.addWidget(self.tf_combo)

#         control_layout.addSpacing(20)
#         control_layout.addWidget(QLabel("Добавить индикатор:"))
#         self.indicator_combo = QComboBox()
#         self.indicator_combo.setMinimumWidth(150)
#         control_layout.addWidget(self.indicator_combo)

#         control_layout.addWidget(QLabel("на график:"))
#         self.plot_combo = QComboBox()
#         self.plot_combo.setMinimumWidth(150)
#         control_layout.addWidget(self.plot_combo)

#         self.add_curve_btn = QPushButton("Добавить кривую")
#         self.add_curve_btn.clicked.connect(self.add_curve_to_plot)
#         control_layout.addWidget(self.add_curve_btn)

#         self.remove_curve_btn = QPushButton("Удалить кривую")
#         self.remove_curve_btn.clicked.connect(self.remove_curve_from_plot)
#         control_layout.addWidget(self.remove_curve_btn)

#         control_layout.addStretch()
#         main_layout.addLayout(control_layout)

#         # === Кнопки управления подграфиками ===
#         subplot_control = QHBoxLayout()
#         self.add_plot_btn = QPushButton("+ Подграфик")
#         self.add_plot_btn.clicked.connect(self.add_subplot)
#         subplot_control.addWidget(self.add_plot_btn)

#         self.remove_plot_btn = QPushButton("- Подграфик")
#         self.remove_plot_btn.clicked.connect(self.remove_subplot)
#         subplot_control.addWidget(self.remove_plot_btn)
#         subplot_control.addStretch()
#         main_layout.addLayout(subplot_control)

#         # === Область графиков ===
#         scroll = QScrollArea()
#         scroll.setWidgetResizable(True)
#         self.plot_container = QWidget()
#         self.plot_layout = QVBoxLayout(self.plot_container)
#         scroll.setWidget(self.plot_container)
#         main_layout.addWidget(scroll)

#         # === Вкладки таблиц ===
#         self.tabs = QTabWidget()
#         main_layout.addWidget(self.tabs)

#         # Ордера
#         orders_tab = QWidget()
#         orders_layout = QVBoxLayout(orders_tab)
#         self.orders_table = QTableWidget()
#         self.orders_table.setColumnCount(6)
#         self.orders_table.setHorizontalHeaderLabels(["ID", "Тип", "Сторона", "Объём", "Цена", "Статус"])
#         orders_layout.addWidget(self.orders_table)
#         self.tabs.addTab(orders_tab, "Ордера")

#         # Сигналы
#         signals_tab = QWidget()
#         signals_layout = QVBoxLayout(signals_tab)
#         self.signals_table = QTableWidget()
#         self.signals_table.setColumnCount(4)
#         self.signals_table.setHorizontalHeaderLabels(["Время", "Тип", "Цена", "Статус"])
#         signals_layout.addWidget(self.signals_table)
#         self.tabs.addTab(signals_tab, "Сигналы")

#         # === Данные ===
#         self.price_plot = None      # SubPlotWidget для цены (со свечами)
#         self.equity_plot = None     # SubPlotWidget для эквити
#         self.extra_plots = []       # дополнительные подграфики
#         self.candle_item = None     # CandlestickItem для свечей

#         # Таймер обновления
#         self.timer = QTimer()
#         self.timer.timeout.connect(self.refresh_data)
#         self.timer.start(2000)

#         self.rebuild_ui()

#     # =============================================
#     # Методы построения интерфейса
#     # =============================================
#     def rebuild_ui(self):
#         """Полная перестройка UI (вызывается при открытии или смене стратегии)."""
#         # Очистка старых графиков
#         for sp in self.extra_plots:
#             self.plot_layout.removeWidget(sp)
#             sp.deleteLater()
#         self.extra_plots.clear()
#         if self.price_plot:
#             self.plot_layout.removeWidget(self.price_plot)
#             self.price_plot.deleteLater()
#             self.price_plot = None
#         if self.equity_plot:
#             self.plot_layout.removeWidget(self.equity_plot)
#             self.equity_plot.deleteLater()
#             self.equity_plot = None
#         self.candle_item = None

#         strategy = self.strategy_manager._strategies.get(self.strategy_name)
#         if not strategy:
#             return

#         # Таймфреймы
#         self.tf_combo.blockSignals(True)
#         self.tf_combo.clear()
#         self.tf_combo.addItems(strategy.timeframes)
#         self.tf_combo.setCurrentText(strategy.timeframes[0] if strategy.timeframes else '1m')
#         self.tf_combo.blockSignals(False)

#         # Ценовой график (свечной)
#         self.price_plot = SubPlotWidget("Цена")
#         # Вместо обычной линии создаём CandlestickItem
#         self.candle_item = CandlestickItem()
#         self.price_plot.plot.addItem(self.candle_item)
#         self.price_plot.curves['candles'] = self.candle_item
#         self.plot_layout.addWidget(self.price_plot)

#         # Эквити
#         self.equity_plot = SubPlotWidget("Эквити")
#         self.equity_plot.add_curve('equity', pen='g')
#         self.plot_layout.addWidget(self.equity_plot)

#         # Списки индикаторов и графиков
#         self._update_indicator_list()
#         self._update_plot_list()

#         self.refresh_data()

#     def _update_indicator_list(self):
#         self.indicator_combo.clear()
#         strategy = self.strategy_manager._strategies.get(self.strategy_name)
#         if strategy:
#             self.indicator_combo.addItems(list(strategy.indicators.keys()))

#     def _update_plot_list(self):
#         self.plot_combo.clear()
#         self.plot_combo.addItem("Цена", "price")
#         self.plot_combo.addItem("Эквити", "equity")
#         for i, sp in enumerate(self.extra_plots):
#             self.plot_combo.addItem(f"Доп. график {i+1}", f"extra_{i}")

#     def _get_plot_by_key(self, key):
#         if key == "price":
#             return self.price_plot
#         elif key == "equity":
#             return self.equity_plot
#         elif key.startswith("extra_"):
#             try:
#                 idx = int(key.split("_")[1])
#                 return self.extra_plots[idx]
#             except:
#                 return None
#         return None

#     def add_subplot(self):
#         sp = SubPlotWidget("Индикатор")
#         self.extra_plots.append(sp)
#         self.plot_layout.addWidget(sp)
#         self._update_plot_list()

#     def remove_subplot(self):
#         if self.extra_plots:
#             sp = self.extra_plots.pop()
#             self.plot_layout.removeWidget(sp)
#             sp.deleteLater()
#             self._update_plot_list()

#     # =============================================
#     # Управление кривыми
#     # =============================================
#     def add_curve_to_plot(self):
#         indicator_name = self.indicator_combo.currentText()
#         plot_key = self.plot_combo.currentData()
#         if not indicator_name or not plot_key:
#             return
#         plot = self._get_plot_by_key(plot_key)
#         if plot:
#             # Не даём добавлять 'close' на ценовой (там свечи)
#             if plot_key == "price" and indicator_name == "close":
#                 return
#             if indicator_name not in plot.curves:
#                 color = pg.intColor(len(plot.curves))
#                 plot.add_curve(indicator_name, pen=color)

#     def remove_curve_from_plot(self):
#         indicator_name = self.indicator_combo.currentText()
#         plot_key = self.plot_combo.currentData()
#         if not indicator_name or not plot_key:
#             return
#         plot = self._get_plot_by_key(plot_key)
#         if plot:
#             # Не даём удалить свечной график или эквити
#             if (plot_key == "price" and indicator_name == "candles") or \
#                (plot_key == "equity" and indicator_name == "equity"):
#                 return
#             plot.remove_curve(indicator_name)

#     def on_tf_changed(self, tf):
#         self.refresh_data()

#     # =============================================
#     # Обновление данных
#     # =============================================
#     def refresh_data(self):
#         strategy = self.strategy_manager._strategies.get(self.strategy_name)
#         if not strategy:
#             return

#         tf = self.tf_combo.currentText()
#         if not tf:
#             return

#         plot_data = strategy.get_plot_data(tf)
#         if not plot_data or 'price' not in plot_data:
#             return
#         tf = self.tf_combo.currentText()
#         interval_secs = {'1m': 1, '5m': 5, '1h': 60}.get(tf, 1)
#         if self.candle_item:
#             self.candle_item.setWidth(interval_secs * 0.8)
#         # Обновление свечного графика
#         if self.candle_item and 'price' in plot_data:
#             t = plot_data['price']['timestamps']
#             o = plot_data['price']['open']
#             h = plot_data['price']['high']
#             l = plot_data['price']['low']
#             c = plot_data['price']['close']
#             if t and o:
#                 data = np.column_stack((t, o, h, l, c))  # должно быть 5 колонок
#                 if data.shape[1] == 5:
#                     self.candle_item.setData(data)
#                 else:
#                     logger.error(f"Неверная форма свечных данных: {data.shape}")

#         # Обновление остальных кривых на всех графиках
#         indicators_data = plot_data.get('indicators', {})
#         all_plots = [self.price_plot, self.equity_plot] + self.extra_plots
#         for plot in all_plots:
#             if not plot:
#                 continue
#             for name, curve in plot.curves.items():
#                 if name == 'candles':
#                     continue
#                 if name == 'equity':
#                     eq = plot_data.get('equity', {})
#                     if eq.get('timestamps') and eq.get('values'):
#                         plot.set_data('equity', eq['timestamps'], eq['values'])
#                 elif name in indicators_data:
#                     ind = indicators_data[name]
#                     if ind['timestamps'] and ind['values']:
#                         plot.set_data(name, ind['timestamps'], ind['values'])

#         # Обновление информационной строки
#         pos = strategy.position
#         entry = strategy._entry_price
#         if plot_data['price']['close']:
#             current_price = plot_data['price']['close'][-1]
#         else:
#             current_price = 0.0
#         if pos != 0 and entry is not None:
#             if pos > 0:
#                 unrealized_pnl = (current_price - entry) * abs(pos)
#             else:
#                 unrealized_pnl = (entry - current_price) * abs(pos)
#         else:
#             unrealized_pnl = 0.0

#         self.info_labels['Позиция'].setText(f"Позиция: {pos:.4f}")
#         self.info_labels['Цена входа'].setText(f"Цена входа: {entry:.2f}" if entry else "Цена входа: --")
#         self.info_labels['Текущая цена'].setText(f"Текущая цена: {current_price:.2f}")
#         self.info_labels['Нереализ. PnL'].setText(f"Нереализ. PnL: {unrealized_pnl:.2f}")
#         self.info_labels['Эквити'].setText(f"Эквити: {strategy.current_equity:.2f}")

#         # Обновление таблиц
#         orders = self.strategy_manager.order_manager.get_order_history(self.strategy_name)[-100:]
#         self.orders_table.setRowCount(len(orders))
#         for i, order in enumerate(orders):
#             self.orders_table.setItem(i, 0, QTableWidgetItem(order.client_order_id))
#             self.orders_table.setItem(i, 1, QTableWidgetItem(order.order_type.value))
#             self.orders_table.setItem(i, 2, QTableWidgetItem(order.side.value))
#             self.orders_table.setItem(i, 3, QTableWidgetItem(str(order.volume)))
#             price_str = f"{order.price:.2f}" if order.price else 'Market'
#             self.orders_table.setItem(i, 4, QTableWidgetItem(price_str))
#             self.orders_table.setItem(i, 5, QTableWidgetItem(order.status.value))

#         signals = getattr(strategy, 'active_signals', [])
#         self.signals_table.setRowCount(len(signals))
#         for i, sig in enumerate(signals):
#             self.signals_table.setItem(i, 0, QTableWidgetItem(str(sig.get('timestamp', ''))))
#             self.signals_table.setItem(i, 1, QTableWidgetItem(sig.get('type', '')))
#             self.signals_table.setItem(i, 2, QTableWidgetItem(str(sig.get('price', ''))))
#             self.signals_table.setItem(i, 3, QTableWidgetItem(sig.get('status', '')))

#         # Обновляем список индикаторов
#         self._update_indicator_list()

# gui/detail_panel.py

import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QLabel, QScrollArea, QMessageBox
)
from PyQt6.QtCore import QTimer, Qt, QRectF, QPointF
import pyqtgraph as pg
import numpy as np

logger = logging.getLogger(__name__)

class CandlestickItem(pg.GraphicsObject):
    """Японские свечи с поддержкой ширины."""
    def __init__(self, data=None):
        super().__init__()
        self.data = None
        self.width = 60
        self.wick_pen = pg.mkPen('w', width=1)
        self.body_pen_up = pg.mkPen('g')
        self.body_brush_up = pg.mkBrush('g')
        self.body_pen_down = pg.mkPen('r')
        self.body_brush_down = pg.mkBrush('r')
        self.setData(data)

    def setWidth(self, width):
        self.width = width
        self.prepareGeometryChange()
        self.update()

    def setData(self, data):
        if data is not None and data.ndim == 2 and data.shape[1] >= 5:
            self.data = data[:, :5]
        else:
            self.data = None
        self.prepareGeometryChange()
        self.update()

    def paint(self, p, opt, widget):
        if self.data is None or len(self.data) == 0:
            return
        x = self.data[:, 0]
        o = self.data[:, 1]
        h = self.data[:, 2]
        l = self.data[:, 3]
        c = self.data[:, 4]
        half = self.width / 2

        for i in range(len(x)):
            t = x[i]
            open_val, close_val = o[i], c[i]
            high_val, low_val = h[i], l[i]

            if close_val >= open_val:
                p.setPen(self.body_pen_up)
                p.setBrush(self.body_brush_up)
            else:
                p.setPen(self.body_pen_down)
                p.setBrush(self.body_brush_down)
            rect = QRectF(t - half, open_val, self.width, close_val - open_val)
            p.drawRect(rect)

            p.setPen(self.wick_pen)
            p.drawLine(QPointF(t, low_val), QPointF(t, high_val))

    def boundingRect(self):
        if self.data is None or len(self.data) == 0:
            return QRectF()
        x = self.data[:, 0]
        h = self.data[:, 2]
        l = self.data[:, 3]
        return QRectF(x.min(), l.min(), x.max() - x.min(), h.max() - l.min())


class SubPlotWidget(QWidget):
    """Подграфик с возможностью добавлять/удалять кривые."""
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.title = title
        self.plot = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
        self.plot.addLegend()
        self.plot.setLabel('left', title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)
        self.curves = {}  # name -> pg.PlotDataItem (или иной)

    def add_curve(self, name, pen='y'):
        if name in self.curves:
            return
        curve = self.plot.plot([], [], pen=pen, name=name)
        self.curves[name] = curve
        return curve

    def remove_curve(self, name):
        if name in self.curves:
            self.plot.removeItem(self.curves[name])
            del self.curves[name]

    def clear_curves(self):
        for name in list(self.curves.keys()):
            self.remove_curve(name)

    def set_data(self, name, x, y):
        if name in self.curves:
            self.curves[name].setData(x, y)


class DetailPanel(QWidget):
    def __init__(self, strategy_name: str, strategy_manager):
        super().__init__()
        self.strategy_name = strategy_name
        self.strategy_manager = strategy_manager
        self.setWindowTitle(f"Детали: {strategy_name}")
        self.resize(1200, 800)

        main_layout = QVBoxLayout(self)

        # === Информационная строка ===
        info_layout = QHBoxLayout()
        self.info_labels = {}
        for key in ['Позиция', 'Цена входа', 'Текущая цена', 'Нереализ. PnL', 'Эквити']:
            label = QLabel(f"{key}: --")
            label.setStyleSheet("font-weight: bold; padding: 4px;")
            info_layout.addWidget(label)
            self.info_labels[key] = label
        main_layout.addLayout(info_layout)

        # === Панель управления ===
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Символ:"))
        self.symbol_combo = QComboBox()
        self.symbol_combo.currentTextChanged.connect(self.on_symbol_changed)
        ctrl.addWidget(self.symbol_combo)

        ctrl.addWidget(QLabel("Таймфрейм:"))
        self.tf_combo = QComboBox()
        self.tf_combo.currentTextChanged.connect(self.on_tf_changed)
        ctrl.addWidget(self.tf_combo)

        ctrl.addSpacing(20)
        ctrl.addWidget(QLabel("Индикатор:"))
        self.indicator_combo = QComboBox()
        self.indicator_combo.setMinimumWidth(150)
        ctrl.addWidget(self.indicator_combo)
        ctrl.addWidget(QLabel("на график:"))
        self.plot_combo = QComboBox()
        self.plot_combo.setMinimumWidth(150)
        ctrl.addWidget(self.plot_combo)

        self.add_curve_btn = QPushButton("+ Кривая")
        self.add_curve_btn.clicked.connect(self.add_curve_to_plot)
        ctrl.addWidget(self.add_curve_btn)
        self.remove_curve_btn = QPushButton("- Кривая")
        self.remove_curve_btn.clicked.connect(self.remove_curve_from_plot)
        ctrl.addWidget(self.remove_curve_btn)
        ctrl.addStretch()
        main_layout.addLayout(ctrl)

        # === Подграфики ===
        subplot_ctrl = QHBoxLayout()
        self.add_plot_btn = QPushButton("+ Подграфик")
        self.add_plot_btn.clicked.connect(self.add_subplot)
        subplot_ctrl.addWidget(self.add_plot_btn)
        self.remove_plot_btn = QPushButton("- Подграфик")
        self.remove_plot_btn.clicked.connect(self.remove_subplot)
        subplot_ctrl.addWidget(self.remove_plot_btn)
        subplot_ctrl.addStretch()
        main_layout.addLayout(subplot_ctrl)

        # === Область графиков ===
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.plot_container = QWidget()
        self.plot_layout = QVBoxLayout(self.plot_container)
        scroll.setWidget(self.plot_container)
        main_layout.addWidget(scroll)

        # === Таблицы ===
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        orders_tab = QWidget()
        orders_layout = QVBoxLayout(orders_tab)
        self.orders_table = QTableWidget()
        self.orders_table.setColumnCount(6)
        self.orders_table.setHorizontalHeaderLabels(["ID", "Тип", "Сторона", "Объём", "Цена", "Статус"])
        orders_layout.addWidget(self.orders_table)
        self.tabs.addTab(orders_tab, "Ордера")

        signals_tab = QWidget()
        signals_layout = QVBoxLayout(signals_tab)
        self.signals_table = QTableWidget()
        self.signals_table.setColumnCount(4)
        self.signals_table.setHorizontalHeaderLabels(["Время", "Тип", "Цена", "Статус"])
        signals_layout.addWidget(self.signals_table)
        self.tabs.addTab(signals_tab, "Сигналы")

        # === Внутренние переменные ===
        self.price_plot = None   # SubPlotWidget для цены
        self.equity_plot = None  # SubPlotWidget для эквити
        self.extra_plots = []
        self.candle_item = None

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_data)
        self.timer.start(2000)

        self.rebuild_ui()

    # ====================== ПОСТРОЕНИЕ ИНТЕРФЕЙСА ======================
    def rebuild_ui(self):
        # Очистка старых графиков
        for sp in self.extra_plots:
            self.plot_layout.removeWidget(sp)
            sp.deleteLater()
        self.extra_plots.clear()
        if self.price_plot:
            self.plot_layout.removeWidget(self.price_plot)
            self.price_plot.deleteLater()
            self.price_plot = None
        if self.equity_plot:
            self.plot_layout.removeWidget(self.equity_plot)
            self.equity_plot.deleteLater()
            self.equity_plot = None
        self.candle_item = None

        strategy = self.strategy_manager._strategies.get(self.strategy_name)
        if not strategy:
            return

        # Заполняем выбор символов (из subscriptions)
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        symbols = sorted({s for s, _ in strategy.subscriptions})
        self.symbol_combo.addItems(symbols)
        self.symbol_combo.setCurrentIndex(0)
        self.symbol_combo.blockSignals(False)

        # Заполняем таймфреймы (все уникальные)
        self.tf_combo.blockSignals(True)
        self.tf_combo.clear()
        tfs = sorted({tf for _, tf in strategy.subscriptions if tf != 'tick'})
        self.tf_combo.addItems(tfs)
        self.tf_combo.setCurrentIndex(0)
        self.tf_combo.blockSignals(False)

        # Создаём ценовой график
        self.price_plot = SubPlotWidget("Цена")
        self.candle_item = CandlestickItem()
        self.price_plot.plot.addItem(self.candle_item)
        self.price_plot.curves['candles'] = self.candle_item
        self.plot_layout.addWidget(self.price_plot)

        # График эквити
        self.equity_plot = SubPlotWidget("Эквити")
        self.equity_plot.add_curve('equity', pen='g')
        self.plot_layout.addWidget(self.equity_plot)

        # Применяем конфигурацию по умолчанию от стратегии
        default_config = strategy.get_default_plot_config()
        if default_config:
            self._apply_default_plot_config(default_config)

        self._update_indicator_list()
        self._update_plot_list()
        self.refresh_data()

    def _apply_default_plot_config(self, config: dict):
        """
        config пример:
        {
            "price": ["sma_fast_AAPL", "sma_slow_AAPL"],
            "extra_0": ["rsi_AAPL"]
        }
        Создаёт кривые на указанных подграфиках (при необходимости создаёт extra подграфики).
        """
        for plot_key, indicators in config.items():
            if plot_key == "price":
                plot = self.price_plot
            elif plot_key == "equity":
                plot = self.equity_plot
            elif plot_key.startswith("extra_"):
                idx = int(plot_key.split("_")[1])
                while len(self.extra_plots) <= idx:
                    self.add_subplot()
                plot = self.extra_plots[idx]
            else:
                continue
            if not plot:
                continue
            for name in indicators:
                if name not in plot.curves:
                    color = pg.intColor(len(plot.curves))
                    plot.add_curve(name, pen=color)

    def _update_indicator_list(self):
        self.indicator_combo.clear()
        strategy = self.strategy_manager._strategies.get(self.strategy_name)
        if not strategy:
            return
        selected_symbol = self.symbol_combo.currentText()
        for name in strategy.indicators.keys():
            if not selected_symbol or name.endswith(f"_{selected_symbol}"):
                self.indicator_combo.addItem(name)

    def _update_plot_list(self):
        self.plot_combo.clear()
        self.plot_combo.addItem("Цена", "price")
        self.plot_combo.addItem("Эквити", "equity")
        for i, sp in enumerate(self.extra_plots):
            self.plot_combo.addItem(f"Доп. график {i+1}", f"extra_{i}")

    def _get_plot_by_key(self, key):
        if key == "price": return self.price_plot
        if key == "equity": return self.equity_plot
        if key.startswith("extra_"):
            idx = int(key.split("_")[1])
            if idx < len(self.extra_plots):
                return self.extra_plots[idx]
        return None

    def add_subplot(self):
        sp = SubPlotWidget("Индикатор")
        self.extra_plots.append(sp)
        self.plot_layout.addWidget(sp)
        self._update_plot_list()

    def remove_subplot(self):
        if self.extra_plots:
            sp = self.extra_plots.pop()
            self.plot_layout.removeWidget(sp)
            sp.deleteLater()
            self._update_plot_list()

    def add_curve_to_plot(self):
        ind = self.indicator_combo.currentText()
        plot_key = self.plot_combo.currentData()
        if not ind or not plot_key:
            return
        plot = self._get_plot_by_key(plot_key)
        if plot and ind not in plot.curves:
            # Защита от добавления свечей или эквити
            if (plot_key == "price" and ind == "candles") or (plot_key == "equity" and ind == "equity"):
                return
            color = pg.intColor(len(plot.curves))
            plot.add_curve(ind, pen=color)

    def remove_curve_from_plot(self):
        ind = self.indicator_combo.currentText()
        plot_key = self.plot_combo.currentData()
        if not ind or not plot_key:
            return
        plot = self._get_plot_by_key(plot_key)
        if plot and ind in plot.curves:
            # Не даём удалить свечной график или эквити
            if (plot_key == "price" and ind == "candles") or (plot_key == "equity" and ind == "equity"):
                QMessageBox.information(self, "Инфо", "Эту кривую нельзя удалить.")
                return
            plot.remove_curve(ind)

    def on_symbol_changed(self, symbol):
        self._update_indicator_list()
        self.refresh_data()

    def on_tf_changed(self, tf):
        self.refresh_data()

    # ====================== ОБНОВЛЕНИЕ ДАННЫХ ======================
    def refresh_data(self):
        strategy = self.strategy_manager._strategies.get(self.strategy_name)
        if not strategy:
            return

        symbol = self.symbol_combo.currentText()
        tf = self.tf_combo.currentText()
        if not symbol or not tf:
            return

        plot_data = strategy.get_plot_data(symbol, tf)
        if not plot_data or 'price' not in plot_data:
            return

        # Свечной график
        if self.candle_item:
            t = plot_data['price']['timestamps']
            o = plot_data['price']['open']
            h = plot_data['price']['high']
            l = plot_data['price']['low']
            c = plot_data['price']['close']
            if t and o:
                data = np.column_stack((t, o, h, l, c))
                if data.shape[1] == 5:
                    self.candle_item.setData(data)
                    # Динамическая ширина свечи
                    interval_secs = {'1m': 1, '5m': 5, '1h': 60}.get(tf, 1)
                    self.candle_item.setWidth(interval_secs * 0.8)

        # Обновление всех кривых на всех графиках
        all_plots = [self.price_plot, self.equity_plot] + self.extra_plots
        for plot in all_plots:
            if not plot:
                continue
            for name, curve in plot.curves.items():
                if name == 'candles':
                    continue
                if name == 'equity':
                    eq = plot_data.get('equity', {})
                    if eq.get('timestamps') and eq.get('values'):
                        plot.set_data('equity', eq['timestamps'], eq['values'])
                elif name in plot_data.get('indicators', {}):
                    ind = plot_data['indicators'][name]
                    if ind['timestamps'] and ind['values']:
                        plot.set_data(name, ind['timestamps'], ind['values'])

        # Информационная строка (только для выбранного символа)
        pos = strategy.positions.get(symbol, 0.0)
        entry = strategy.entry_prices.get(symbol)
        last_price = strategy._last_prices.get(symbol, 0.0)
        if pos != 0 and entry is not None:
            if pos > 0:
                unreal_pnl = (last_price - entry) * pos
            else:
                unreal_pnl = (entry - last_price) * abs(pos)
        else:
            unreal_pnl = 0.0
        self.info_labels['Позиция'].setText(f"Позиция: {pos:.4f}")
        self.info_labels['Цена входа'].setText(f"Цена входа: {entry:.2f}" if entry else "Цена входа: --")
        self.info_labels['Текущая цена'].setText(f"Текущая цена: {last_price:.2f}")
        self.info_labels['Нереализ. PnL'].setText(f"Нереализ. PnL: {unreal_pnl:.2f}")
        self.info_labels['Эквити'].setText(f"Эквити: {strategy.current_equity:.2f}")

        # Таблицы ордеров и сигналов
        orders = self.strategy_manager.order_manager.get_order_history(self.strategy_name)[-100:]
        self.orders_table.setRowCount(len(orders))
        for i, order in enumerate(orders):
            self.orders_table.setItem(i, 0, QTableWidgetItem(order.client_order_id))
            self.orders_table.setItem(i, 1, QTableWidgetItem(order.order_type.value))
            self.orders_table.setItem(i, 2, QTableWidgetItem(order.side.value))
            self.orders_table.setItem(i, 3, QTableWidgetItem(str(order.volume)))
            price_str = f"{order.price:.2f}" if order.price else "—"
            self.orders_table.setItem(i, 4, QTableWidgetItem(price_str))
            self.orders_table.setItem(i, 5, QTableWidgetItem(order.status.value))

        signals = getattr(strategy, 'active_signals', [])
        self.signals_table.setRowCount(len(signals))
        for i, sig in enumerate(signals):
            # active_signals contains Order objects
            created_at = str(getattr(sig, 'created_at', ''))
            side = getattr(sig, 'side', None)
            side_str = side.value if side else ''
            price = getattr(sig, 'price', None)
            price_str = f"{price:.2f}" if price else "Market"
            status = getattr(sig, 'status', None)
            status_str = status.value if status else ''
            self.signals_table.setItem(i, 0, QTableWidgetItem(created_at))
            self.signals_table.setItem(i, 1, QTableWidgetItem(side_str))
            self.signals_table.setItem(i, 2, QTableWidgetItem(price_str))
            self.signals_table.setItem(i, 3, QTableWidgetItem(status_str))

        self._update_indicator_list()
