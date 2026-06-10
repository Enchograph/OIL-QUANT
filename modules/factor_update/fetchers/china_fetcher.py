"""
中国数据获取器
使用akshare获取中国原油相关数据
"""
import pandas as pd
from datetime import datetime
from .base_fetcher import BaseFetcher


class ChinaDataFetcher(BaseFetcher):
    """
    获取中国原油相关数据:
    - BDTI: 波罗的海原油运价指数
    - China_wholeprice: 中国柴油批发价
    - China_retailprice: 中国柴油零售价
    - China_final_import: 中国成品油进口
    - China_final_export: 中国成品油出口
    - China_final_con: 中国成品油消费
    - China_out: 中国原油产量
    """

    def __init__(self):
        super().__init__("china")
        self.ak = None
        self._init_akshare()

    def _init_akshare(self):
        """初始化akshare"""
        try:
            import akshare as ak
            self.ak = ak
            self.logger.info("akshare初始化成功")
        except ImportError:
            self.logger.warning("akshare未安装，中国数据获取将不可用")
            self.logger.warning("请运行: pip install akshare")

    def fetch_bdti(self) -> pd.Series:
        """获取BDTI波罗的海原油运价指数"""
        if not self.ak:
            return pd.Series(dtype=float, name="BDTI")

        try:
            self.logger.info("获取BDTI数据...")
            df = pd.DataFrame()

            if hasattr(self.ak, "index_bdti"):
                df = self.ak.index_bdti()
            elif hasattr(self.ak, "bdti"):
                df = self.ak.bdti()
            elif hasattr(self.ak, "index_international_freight"):
                freight_df = self.ak.index_international_freight()
                if not freight_df.empty and '指数名称' in freight_df.columns:
                    df = freight_df[freight_df['指数名称'] == 'BDTI'].copy()

            if df.empty:
                self.logger.warning("BDTI接口在当前akshare版本中不可用，跳过该字段")
                return pd.Series(dtype=float, name="BDTI")

            date_col = '日期' if '日期' in df.columns else 'Date'
            value_col = '收盘' if '收盘' in df.columns else 'Close'
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            df[value_col] = pd.to_numeric(df[value_col], errors='coerce')
            df = df.dropna(subset=[date_col]).set_index(date_col)[value_col]
            df = df.sort_index()
            df.name = "BDTI"

            self.logger.info(f"  BDTI: {len(df)} 行")
            return df

        except Exception as e:
            self.logger.error(f"BDTI获取失败: {e}")
            return pd.Series(dtype=float, name="BDTI")

    def fetch_oil_prices(self) -> pd.DataFrame:
        """获取中国成品油价格"""
        if not self.ak:
            return pd.DataFrame()

        try:
            self.logger.info("获取成品油价格...")
            df = pd.DataFrame()
            if hasattr(self.ak, "energy_oil_price"):
                try:
                    df = self.ak.energy_oil_price()
                except Exception:
                    df = pd.DataFrame()

            if df.empty and hasattr(self.ak, "energy_oil_detail"):
                try:
                    detail_df = self.ak.energy_oil_detail()
                    if not detail_df.empty:
                        grouped = detail_df.copy()
                        grouped['日期'] = pd.to_datetime(grouped['日期'], errors='coerce')
                        grouped = grouped.dropna(subset=['日期'])
                        grouped = grouped.groupby('日期').agg({
                            'V_0': 'mean',
                            'QE_0': 'mean',
                        }).reset_index()
                        grouped = grouped.rename(columns={
                            'V_0': '柴油批发价',
                            'QE_0': '柴油零售价',
                        })
                        df = grouped
                except Exception:
                    df = pd.DataFrame()

            if df.empty:
                return pd.DataFrame()

            result = pd.DataFrame(index=pd.to_datetime(df['日期']))

            wholeprice_col = '柴油批发价' if '柴油批发价' in df.columns else '柴油批发价格'
            retail_col = '柴油零售价' if '柴油零售价' in df.columns else '柴油零售价格'

            if wholeprice_col in df.columns:
                result['China_wholeprice'] = pd.to_numeric(df[wholeprice_col], errors='coerce')
            if retail_col in df.columns:
                result['China_retailprice'] = pd.to_numeric(df[retail_col], errors='coerce')

            result = result.resample('D').ffill()
            return result

        except Exception as e:
            self.logger.error(f"成品油价格获取失败: {e}")
            return pd.DataFrame()

    def fetch_china_oil_data(self) -> pd.DataFrame:
        """获取中国原油产销数据"""
        if not self.ak:
            return pd.DataFrame()

        try:
            self.logger.info("获取中国原油数据...")

            prod_df = pd.DataFrame()
            if hasattr(self.ak, "energy_oil_production"):
                try:
                    prod_df = self.ak.energy_oil_production()
                    prod_df['日期'] = pd.to_datetime(prod_df['日期'])
                    prod_df = prod_df.set_index('日期')
                except Exception:
                    prod_df = pd.DataFrame()

            import_df = pd.DataFrame()
            if hasattr(self.ak, "energy_oil_import"):
                try:
                    import_df = self.ak.energy_oil_import()
                    import_df['日期'] = pd.to_datetime(import_df['日期'])
                    import_df = import_df.set_index('日期')
                except Exception:
                    import_df = pd.DataFrame()

            # 合并数据
            result = pd.DataFrame()
            if not prod_df.empty:
                result['China_out'] = prod_df['产量']
            if not import_df.empty:
                result['China_final_import'] = import_df['进口量']

            if result.empty:
                return pd.DataFrame()

            result = result.resample('D').ffill()
            return result

        except Exception as e:
            self.logger.error(f"中国原油数据获取失败: {e}")
            return pd.DataFrame()

    def fetch(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取所有中国数据"""
        if not self.ak:
            self.logger.error("akshare未安装，无法获取中国数据")
            return pd.DataFrame()

        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if start_date is None:
            start_date = "2016-01-01"

        all_data = []

        # BDTI
        bdti = self.fetch_bdti()
        if not bdti.empty:
            all_data.append(bdti)

        # 成品油价格
        oil_prices = self.fetch_oil_prices()
        if not oil_prices.empty:
            all_data.append(oil_prices)

        # 中国原油数据
        china_oil = self.fetch_china_oil_data()
        if not china_oil.empty:
            all_data.append(china_oil)

        if not all_data:
            return pd.DataFrame()

        df = pd.concat(all_data, axis=1)
        df = df.sort_index()

        # 筛选日期范围
        df = df[df.index >= start_date]
        df = df[df.index <= end_date]

        return df


if __name__ == "__main__":
    fetcher = ChinaDataFetcher()
    df = fetcher.fetch("2024-01-01", "2024-12-31")
    print(df.tail())
    print(f"\n共获取 {len(df)} 行数据")
    print(f"列: {list(df.columns)}")
