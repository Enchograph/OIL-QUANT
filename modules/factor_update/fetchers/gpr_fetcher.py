"""
GPR地缘政治风险数据获取器
获取Caldara和Iacoviello的地缘政治风险指数
数据来源: https://www.matteoiacoviello.com/gpr.htm
"""
import pandas as pd
import requests
from datetime import datetime
from io import BytesIO
from pathlib import Path
from .base_fetcher import BaseFetcher


class GPRFetcher(BaseFetcher):
    """
    获取GPR地缘政治风险指数数据:
    - GPR: 总地缘政治风险指数
    - GPRT: 地缘政治威胁
    - GPRA: 地缘政治行动
    - GPRH: 地缘政治风险历史
    - GPRHT: 地缘政治风险历史威胁
    - GPRHA: 地缘政治风险历史行动
    - 以及各国别和地区数据
    """

    # GPR数据下载链接
    DATA_URL = "http://www2.warwick.ac.uk/fac/soc/economics/research/centres/cage/manage/publications/bn06.2014.pdf"
    EXCEL_URL = "https://www.matteoiacoviello.com/gpr_files/gpr_monthly.xlsx"
    EXCEL_URL_DAILY = "https://www.matteoiacoviello.com/gpr_files/gpr_daily.xlsx"
    LOCAL_MONTHLY_FILE = Path(__file__).resolve().parent.parent / "gpr_data" / "data_gpr_export.xls"

    # 主要指标
    MAIN_INDICATORS = [
        "GPR", "GPRT", "GPRA", "GPRH", "GPRHT", "GPRHA",
        "SHARE_GPR", "N10", "SHARE_GPRH", "N3H",
        "GPRH_NOEW", "GPR_NOEW", "GPRH_AND", "GPR_AND",
        "GPRH_BASIC", "GPR_BASIC"
    ]

    # 各国别指标 (部分示例)
    COUNTRY_INDICATORS = [
        "GPRC_ARG", "GPRC_AUS", "GPRC_BEL", "GPRC_BRA", "GPRC_CAN",
        "GPRC_CHE", "GPRC_CHL", "GPRC_CHN", "GPRC_COL", "GPRC_DEU",
        "GPRC_DNK", "GPRC_EGY", "GPRC_ESP", "GPRC_FIN", "GPRC_FRA",
        "GPRC_GBR", "GPRC_HKG", "GPRC_HUN", "GPRC_IDN", "GPRC_IND",
        "GPRC_ISR", "GPRC_ITA", "GPRC_JPN", "GPRC_KOR", "GPRC_MEX",
        "GPRC_MYS", "GPRC_NLD", "GPRC_NOR", "GPRC_PER", "GPRC_PHL",
        "GPRC_POL", "GPRC_PRT", "GPRC_RUS", "GPRC_SAU", "GPRC_SWE",
        "GPRC_THA", "GPRC_TUN", "GPRC_TUR", "GPRC_TWN", "GPRC_UKR",
        "GPRC_USA", "GPRC_VEN", "GPRC_VNM", "GPRC_ZAF"
    ]

    COUNTRY_HIST_INDICATORS = [f"GPRHC_{c.split('_')[1]}" for c in COUNTRY_INDICATORS]

    def __init__(self):
        super().__init__("gpr")

    def _download_monthly(self) -> pd.DataFrame:
        """下载月度GPR数据"""
        try:
            self.logger.info("下载月度GPR数据...")
            response = requests.get(self.EXCEL_URL, timeout=60)
            response.raise_for_status()

            df = pd.read_excel(BytesIO(response.content))

            # 通常GPR数据的列名在第一行
            if 'month' in df.columns:
                df['date'] = pd.to_datetime(df['month'].astype(str))
            elif 'year' in df.columns and 'month' in df.columns:
                df['date'] = pd.to_datetime(df[['year', 'month']].assign(day=1))
            else:
                # 尝试第一列作为日期
                df = df.rename(columns={df.columns[0]: 'date'})
                df['date'] = pd.to_datetime(df['date'], errors='coerce')

            df = df.set_index('date')
            df = df.sort_index()

            self.logger.info(f"月度数据: {len(df)} 行")
            return df

        except Exception as e:
            self.logger.error(f"下载月度GPR数据失败: {e}")
            return pd.DataFrame()

    def _load_local_monthly(self) -> pd.DataFrame:
        """从本地离线文件加载月度GPR数据"""
        try:
            if not self.LOCAL_MONTHLY_FILE.exists():
                self.logger.warning(f"本地GPR文件不存在: {self.LOCAL_MONTHLY_FILE}")
                return pd.DataFrame()

            self.logger.info(f"使用本地GPR离线文件: {self.LOCAL_MONTHLY_FILE}")
            df = pd.read_excel(self.LOCAL_MONTHLY_FILE)

            if "date" not in df.columns:
                if "Date" in df.columns:
                    df = df.rename(columns={"Date": "date"})
                elif "month" in df.columns:
                    df = df.rename(columns={"month": "date"})
                else:
                    df = df.rename(columns={df.columns[0]: "date"})

            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).set_index("date").sort_index()
            self.logger.info(f"本地月度数据: {len(df)} 行")
            return df
        except Exception as e:
            self.logger.error(f"加载本地GPR数据失败: {e}")
            return pd.DataFrame()

    def _download_daily(self) -> pd.DataFrame:
        """下载日度GPR数据"""
        try:
            self.logger.info("下载日度GPR数据...")
            response = requests.get(self.EXCEL_URL_DAILY, timeout=60)
            response.raise_for_status()

            df = pd.read_excel(BytesIO(response.content))

            # 解析日期列
            date_col = None
            for col in ['date', 'day', 'time']:
                if col in df.columns:
                    date_col = col
                    break

            if date_col:
                df['date'] = pd.to_datetime(df[date_col], errors='coerce')
                df = df.set_index('date')
            else:
                # 尝试第一列
                df = df.rename(columns={df.columns[0]: 'date'})
                df['date'] = pd.to_datetime(df['date'], errors='coerce')
                df = df.set_index('date')

            df = df.sort_index()
            self.logger.info(f"日度数据: {len(df)} 行")
            return df

        except Exception as e:
            self.logger.error(f"下载日度GPR数据失败: {e}")
            return pd.DataFrame()

    def fetch(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取GPR数据"""
        # 优先使用日度数据
        df_daily = self._download_daily()

        if not df_daily.empty:
            # 重采样为日度（如果原始不是日度）
            df = df_daily.resample('D').ffill()
        else:
            # 回退到月度数据
            df_monthly = self._download_monthly()
            if df_monthly.empty:
                df_monthly = self._load_local_monthly()
            if df_monthly.empty:
                return pd.DataFrame()
            # 月度数据展开为日度
            df = df_monthly.resample('D').ffill()

        # 筛选日期范围
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]

        # 标准化列名
        canonical_columns = {
            indicator.upper(): indicator
            for indicator in self.MAIN_INDICATORS + self.COUNTRY_INDICATORS + self.COUNTRY_HIST_INDICATORS
        }
        column_mapping = {}
        for col in df.columns:
            col_str = str(col).strip().upper()
            normalized_key = col_str.replace(" ", "_").replace("-", "_")
            target = canonical_columns.get(col_str) or canonical_columns.get(normalized_key)
            if target:
                column_mapping[col] = target

        df = df.rename(columns=column_mapping)

        # 选择我们需要的列
        available_cols = [c for c in self.MAIN_INDICATORS + self.COUNTRY_INDICATORS + self.COUNTRY_HIST_INDICATORS
                         if c in df.columns]
        df = df[available_cols]

        return df


if __name__ == "__main__":
    fetcher = GPRFetcher()
    df = fetcher.fetch("2020-01-01", "2024-12-31")
    print(df.head())
    print(f"\n共获取 {len(df)} 行数据")
    print(f"列: {list(df.columns)}")
