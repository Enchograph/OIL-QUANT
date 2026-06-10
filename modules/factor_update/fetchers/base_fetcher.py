"""
数据获取器基类
"""
import pandas as pd
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path


class BaseFetcher(ABC):
    """数据获取器基类"""

    def __init__(self, name: str, raw_dir: str = "./raw_data"):
        self.name = name
        self.raw_dir = Path(raw_dir) / name
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        # 设置日志
        self.logger = logging.getLogger(f"Fetcher.{name}")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    @abstractmethod
    def fetch(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取数据，子类必须实现"""
        pass

    def get_last_date(self) -> str:
        """获取已保存数据的最后日期"""
        try:
            files = sorted(self.raw_dir.glob("*.csv"))
            if files:
                df = pd.read_csv(files[-1], index_col=0, parse_dates=True)
                if not df.empty:
                    return df.index.max().strftime("%Y-%m-%d")
        except Exception as e:
            self.logger.warning(f"读取上次日期失败: {e}")
        return None

    def incremental_update(self) -> pd.DataFrame:
        """增量更新"""
        last_date = self.get_last_date()

        if last_date:
            start = (pd.to_datetime(last_date) + timedelta(days=1)).strftime("%Y-%m-%d")
            today = datetime.now().strftime("%Y-%m-%d")
            if start > today:
                self.logger.info(f"{self.name}: 数据已是最新")
                return pd.DataFrame()
        else:
            start = "2016-01-01"

        end = datetime.now().strftime("%Y-%m-%d")
        self.logger.info(f"{self.name}: 更新 {start} 至 {end}")

        return self.fetch(start, end)

    def save(self, df: pd.DataFrame, filename: str = None):
        """保存数据"""
        if df.empty:
            return

        if filename is None:
            filename = f"{self.name}_{datetime.now().strftime('%Y%m%d')}.csv"

        filepath = self.raw_dir / filename

        # 如果文件存在，合并数据
        if filepath.exists():
            existing = pd.read_csv(filepath, index_col=0, parse_dates=True)
            df = pd.concat([existing, df])
            df = df[~df.index.duplicated(keep='last')]
            df = df.sort_index()

        df.to_csv(filepath)
        self.logger.info(f"{self.name}: 保存 {len(df)} 行到 {filepath}")
