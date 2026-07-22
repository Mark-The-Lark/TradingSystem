import ast
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox,
    QPushButton, QHBoxLayout, QVBoxLayout, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.strategy_registry import StrategyRegistry


class AddStrategyDialog(QDialog):
    strategy_added = pyqtSignal()

    def __init__(self, registry: StrategyRegistry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.setWindowTitle("Добавить стратегию")
        self.resize(450, 250)

        # Основной layout
        main_layout = QVBoxLayout(self)

        # Форма
        form_layout = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Уникальное имя стратегии")
        form_layout.addRow("Имя:", self.name_edit)

        self.class_combo = QComboBox()
        self._update_class_list()
        form_layout.addRow("Класс:", self.class_combo)

        main_layout.addLayout(form_layout)

        # Кнопки управления
        btn_layout = QHBoxLayout()
        self.reload_btn = QPushButton("🔄 Обновить список")
        self.reload_btn.clicked.connect(self._reload_classes)
        btn_layout.addWidget(self.reload_btn)

        self.import_btn = QPushButton("📂 Импортировать .py")
        self.import_btn.clicked.connect(self._import_file)
        btn_layout.addWidget(self.import_btn)

        main_layout.addLayout(btn_layout)

        # Стандартные кнопки OK/Cancel
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        # Drag-and-drop файлов
        self.setAcceptDrops(True)

    def _update_class_list(self):
        """Заполняет комбобокс именами классов из реестра."""
        self.class_combo.clear()
        names = self.registry.get_all_names()
        if names:
            self.class_combo.addItems(names)
            self.class_combo.setEnabled(True)
        else:
            self.class_combo.addItem("(нет стратегий)")
            self.class_combo.setEnabled(False)

    def _reload_classes(self):
        """Пересканирует папку и обновляет список."""
        self.registry.reload()
        self._update_class_list()
        count = len(self.registry.get_all_names())
        QMessageBox.information(self, "Обновлено", f"Загружено {count} стратегий.")

    def _import_file(self):
        """Открывает диалог выбора .py файла и пытается импортировать его."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл стратегии", "", "Python файлы (*.py)"
        )
        if not file_path:
            return
        self._copy_and_reload(file_path)

    @staticmethod
    def _check_strategy_file(filepath: Path) -> bool:
        """
        Проверяет, содержит ли файл класс, наследующий Strategy.
        Использует ast для статического анализа (без выполнения кода).
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read())
        except (SyntaxError, UnicodeDecodeError):
            return False

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    # Если базовый класс прямо назван 'Strategy'
                    if isinstance(base, ast.Name) and base.id == 'Strategy':
                        return True
                    # Если это атрибут вида module.Strategy или package.module.Strategy
                    if isinstance(base, ast.Attribute) and base.attr == 'Strategy':
                        return True
        return False

    def _copy_and_reload(self, file_path: str):
        """Копирует файл в папку стратегий, если он содержит корректный класс."""
        src = Path(file_path)

        # Проверяем файл
        if not self._check_strategy_file(src):
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Файл {src.name} не содержит класса, наследующего Strategy.\n"
                "Убедитесь, что в файле определён класс, наследующий core.strategy.Strategy."
            )
            return

        dest = self.registry._strategies_folder / src.name

        if dest.exists():
            reply = QMessageBox.question(
                self,
                "Файл существует",
                f"Файл {src.name} уже есть в папке стратегий. Перезаписать?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        try:
            shutil.copy2(src, dest)
            QMessageBox.information(
                self,
                "Успешно",
                f"Файл {src.name} скопирован.\n"
                "Список стратегий будет обновлён автоматически."
            )
            # Автоматически перезагружаем реестр и обновляем комбобокс
            self._reload_classes()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось скопировать файл: {e}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.endswith('.py'):
                self._copy_and_reload(file_path)
                break

    def get_selected_class(self):
        """Возвращает класс стратегии, выбранный в комбобоксе."""
        class_name = self.class_combo.currentText()
        if class_name == "(нет стратегий)":
            return None
        return self.registry.get(class_name)