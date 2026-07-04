import json
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

class StateStore(ABC):
    @abstractmethod
    async def save_strategy_state(self, name: str, state: dict) -> None:
        ...

    @abstractmethod
    async def load_strategy_state(self, name: str) -> Optional[dict]:
        ...

    @abstractmethod
    async def delete_strategy_state(self, name: str) -> None:
        ...

    @abstractmethod
    async def save_strategies_list(self, strategies: list) -> None:
        ...

    @abstractmethod
    async def load_strategies_list(self) -> Optional[list]:
        ...

    @abstractmethod
    async def save_component_state(self, component_name: str, state: dict) -> None:
        """Сохраняет состояние произвольного компонента (OrderManager, CapitalManager и т.д.)."""
        ...

    @abstractmethod
    async def load_component_state(self, component_name: str) -> Optional[dict]:
        """Загружает состояние компонента. Возвращает None если не найдено."""
        ...

class JsonStateStore(StateStore):
    def __init__(self, base_path: str = "data/states"):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)
        self._strategies_file = os.path.join(base_path, "strategies_list.json")

    async def save_strategy_state(self, name: str, state: dict) -> None:
        path = os.path.join(self.base_path, f"{name}.json")
        with open(path, "w") as f:
            json.dump(state, f, indent=2, default=str)

    async def load_strategy_state(self, name: str) -> Optional[dict]:
        path = os.path.join(self.base_path, f"{name}.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return None

    async def delete_strategy_state(self, name: str) -> None:
        path = os.path.join(self.base_path, f"{name}.json")
        rem =  os.path.join(self.base_path, f"{name}_removed.json")
        if os.path.exists(path):
            # os.remove(path)
            os.rename(path, rem)

    async def save_strategies_list(self, strategies: list) -> None:
        with open(self._strategies_file, "w") as f:
            json.dump(strategies, f, indent=2)

    async def load_strategies_list(self) -> Optional[list]:
        if os.path.exists(self._strategies_file):
            with open(self._strategies_file, "r") as f:
                return json.load(f)
        return []

    async def save_component_state(self, component_name: str, state: dict) -> None:
        """Сохраняет состояние компонента в <component_name>_state.json."""
        path = os.path.join(self.base_path, f"{component_name}_state.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)

    async def load_component_state(self, component_name: str) -> Optional[dict]:
        """Загружает состояние компонента. Возвращает None если файл не найден."""
        path = os.path.join(self.base_path, f"{component_name}_state.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
