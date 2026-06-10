"""
EIA数据获取器
获取美国能源信息署的原油相关数据
"""
import pandas as pd
import requests
from datetime import datetime
from typing import Dict, List
from .base_fetcher import BaseFetcher


class EIAFetcher(BaseFetcher):
    """
    获取EIA数据：
    - US_out: 美国原油产量
    - C_stock: 商业原油库存
    - Cushing_stock: 库欣原油库存
    - US_stock_strategy: 战略石油储备
    - US_OR: 炼油厂产能利用率
    """

    BASE_URL = "https://api.eia.gov/v2"

    # EIA数据系列配置
    SERIES_CONFIG = {
        # 美国原油产量 (千桶/日) - 月度
        "US_out": {
            "route": "petroleum/crd/crpdn/data",
            "frequency": "monthly",
            "facets": {
                "duoarea": ["NUS"],
                "product": ["EPC0"],
                "process": ["FPF"],
            },
            "series": "MCRFPUS1"
        },
        # 商业原油库存 (千桶) - 周度
        "C_stock": {
            "route": "petroleum/stoc/wstk/data",
            "frequency": "weekly",
            "facets": {
                "duoarea": ["NUS"],
                "product": ["EPC0"],
                "process": ["SAX"],
            },
            "series": "WCESTUS1"
        },
        # 库欣原油库存 (千桶) - 周度
        "Cushing_stock": {
            "route": "petroleum/stoc/wstk/data",
            "frequency": "weekly",
            "facets": {
                "duoarea": ["YCUOK"],
                "product": ["EPC0"],
                "process": ["SAX"],
            },
            "series": "WCESTCU1"
        },
        # 战略石油储备 (千桶) - 周度
        "US_stock_strategy": {
            "route": "petroleum/stoc/wstk/data",
            "frequency": "weekly",
            "facets": {
                "duoarea": ["NUS"],
                "product": ["EPC0"],
                "process": ["SPR"],
            },
            "series": "WCSSTUS1"
        },
        # 炼油厂产能利用率 (%) - 周度
        "US_OR": {
            "route": "petroleum/pnp/refw/data",
            "frequency": "weekly",
            "facets": {
                "duoarea": ["NUS"],
                "series": ["WPULEUS3"],
            },
            "series": "WPULEUS3"
        },
    }

    def __init__(self, api_key: str = None):
        super().__init__("eia")
        self.api_key = api_key

    def _fetch_series(self, name: str, config: dict, start: str, end: str) -> pd.Series:
        """获取单个数据系列"""
        if not self.api_key:
            self.logger.error("EIA API Key未设置")
            return pd.Series(dtype=float, name=name)

        url = f"{self.BASE_URL}/{config['route']}/"

        # 构建参数
        params = {
            "api_key": self.api_key,
            "frequency": config["frequency"],
            "data[0]": "value",
            "start": start[:7] if config["frequency"] == "monthly" else start,
            "end": end[:7] if config["frequency"] == "monthly" else end,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "offset": 0,
            "length": 5000
        }

        # 添加facets
        for facet, values in config.get("facets", {}).items():
            for i, val in enumerate(values):
                params[f"facets[{facet}][]"] = val

        try:
            self.logger.info(f"获取 {name}...")
            response = requests.get(url, params=params, timeout=30)

            if response.status_code != 200:
                self.logger.error(f"{name}: HTTP {response.status_code}")
                return pd.Series(dtype=float, name=name)

            data = response.json()
            records = data.get("response", {}).get("data", [])

            if not records:
                self.logger.warning(f"{name}: 无数据")
                return pd.Series(dtype=float, name=name)

            df = pd.DataFrame(records)
            df['period'] = pd.to_datetime(df['period'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
            df = df.set_index('period')['value']
            df = df.sort_index()

            # 重采样为日度（向前填充）
            df = df.resample('D').ffill()
            df.name = name

            self.logger.info(f"  {name}: {len(df)} 行")
            return df

        except Exception as e:
            self.logger.error(f"{name}: 获取失败 - {e}")
            return pd.Series(dtype=float, name=name)

    def fetch(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取所有EIA数据"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if start_date is None:
            start_date = "2016-01-01"

        if not self.api_key:
            self.logger.error("EIA API Key未设置，跳过EIA数据获取")
            return pd.DataFrame()

        all_series = []
        for name, config in self.SERIES_CONFIG.items():
            series = self._fetch_series(name, config, start_date, end_date)
            if not series.empty:
                all_series.append(series)

        if not all_series:
            return pd.DataFrame()

        # 合并所有系列
        df = pd.concat(all_series, axis=1)
        df = df.sort_index()

        return df


if __name__ == "__main__":
    from config import EIA_API_KEY

    fetcher = EIAFetcher(api_key=EIA_API_KEY)
    df = fetcher.fetch("2024-01-01", "2024-12-31")
    print(df.tail())
    print(f"\n共获取 {len(df)} 行数据")
    print(f"列: {list(df.columns)}")
