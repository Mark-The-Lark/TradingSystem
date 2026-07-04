import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional

class HistoricalDataLoader:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Директория {data_dir} не найдена")

    def load_ticker(self, ticker: str,
                    start_date: Optional[str] = None,
                    end_date: Optional[str] = None) -> pd.DataFrame:
        """Загружает данные, опционально обрезая по датам (формат YYYYMMDD)."""
        file_path = self.data_dir / f"{ticker}.txt"
        if not file_path.exists():
            raise FileNotFoundError(f"Файл {file_path} не найден")

        # Чтение с автоматическим определением заголовка
        try:
            df = pd.read_csv(file_path, header=0)
            df.columns = [col.strip().replace('<', '').replace('>', '').lower() for col in df.columns]
        except (pd.errors.ParserError, ValueError):
            df = pd.read_csv(file_path, header=None,
                             names=['ticker', 'per', 'date', 'time', 'open', 'high', 'low', 'close', 'vol'])
            df.columns = [c.lower() for c in df.columns]

        # Фильтр по тикеру
        if 'ticker' in df.columns:
            df = df[df['ticker'].astype(str).str.strip() == ticker]

        # Преобразование даты
        df['date'] = df['date'].astype(str).str.zfill(8)
        df['time'] = df['time'].astype(str).str.zfill(6)
        df['timestamp'] = pd.to_datetime(df['date'] + df['time'], format='%Y%m%d%H%M%S', errors='coerce')
        df = df.dropna(subset=['timestamp'])

        # Фильтрация по диапазону дат
        if start_date:
            start_dt = pd.to_datetime(start_date, format='%Y%m%d')
            df = df[df['timestamp'] >= start_dt]
        if end_date:
            end_dt = pd.to_datetime(end_date, format='%Y%m%d')
            df = df[df['timestamp'] <= end_dt + pd.Timedelta(days=1)]  # включаем последний день полностью

        df = df.set_index('timestamp')
        df = df[['open', 'high', 'low', 'close', 'vol']]
        df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        df.sort_index(inplace=True)
        df = df[~df.index.duplicated(keep='first')]
        return df
