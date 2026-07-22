import importlib.util
import os
import sys
from typing import Dict, Type, Optional, List
from pathlib import Path
import logging

from core.strategy import Strategy

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """Реестр классов стратегий с возможностью динамической загрузки из папки."""
    
    def __init__(self, strategies_folder: str = "strategies"):
        self._strategies_folder = Path(strategies_folder)
        self._classes: Dict[str, Type[Strategy]] = {}
        self._module_cache: Dict[str, str] = {}  # имя_класса -> путь_к_файлу
        
        # Создаём папку, если её нет
        self._strategies_folder.mkdir(exist_ok=True)
        
        # Добавляем папку в sys.path для возможности импорта
        folder_str = str(self._strategies_folder.absolute())
        if folder_str not in sys.path:
            sys.path.insert(0, folder_str)
    
    def scan(self) -> Dict[str, Type[Strategy]]:
        """
        Сканирует папку strategies и загружает все классы-наследники Strategy.
        Возвращает словарь {имя_класса: класс}.
        """
        self._classes.clear()
        self._module_cache.clear()
        
        for file_path in self._strategies_folder.glob("*.py"):
            if file_path.name.startswith("__"):
                continue
            
            module_name = file_path.stem
            
            try:
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if spec is None or spec.loader is None:
                    continue
                    
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                
                # Ищем классы-наследники Strategy
                for attr_name in dir(module):
                    obj = getattr(module, attr_name)
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, Strategy)
                        and obj is not Strategy
                    ):
                        self._classes[obj.__name__] = obj
                        self._module_cache[obj.__name__] = str(file_path)
                        logger.info(f"Загружена стратегия: {obj.__name__} из {file_path.name}")
                        
            except Exception as e:
                logger.error(f"Ошибка загрузки {file_path.name}: {e}")
        
        return self._classes
    
    def reload(self) -> Dict[str, Type[Strategy]]:
        """Принудительная перезагрузка (очищает кэш модулей и сканирует заново)."""
        # Удаляем загруженные модули из sys.modules
        for module_name in list(sys.modules.keys()):
            if module_name in self._module_cache.values():
                del sys.modules[module_name]
        
        self._module_cache.clear()
        return self.scan()
    
    def get(self, class_name: str) -> Optional[Type[Strategy]]:
        """Возвращает класс стратегии по имени."""
        return self._classes.get(class_name)
    
    def get_all(self) -> Dict[str, Type[Strategy]]:
        """Возвращает все зарегистрированные классы."""
        return self._classes.copy()
    
    def get_all_names(self) -> List[str]:
        """Возвращает список имён всех зарегистрированных классов."""
        return list(self._classes.keys())
    
    def register(self, class_name: str, strategy_class: Type[Strategy]) -> None:
        """Ручная регистрация класса (для тестов или встроенных стратегий)."""
        self._classes[class_name] = strategy_class