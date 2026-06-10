"""
CFTC数据获取器
获取美国商品期货交易委员会的期货持仓数据
"""
import pandas as pd
import requests
from datetime import datetime
from io import StringIO
from .base_fetcher import BaseFetcher


class CFTCFetcher(BaseFetcher):
    """
    获取CFTC期货持仓数据:
    - WTI_MM_Net: 资金管理人净持仓
    - WTI_Fut_Vol: 期货交易量
    数据源: CFTC Disaggregated Reports
    """

    # CFTC数据URL模板 - COT报告格式
    COT_URL = "https://www.cftc.gov/dea/newcot/deafut.txt"
    DISAGGREGATED_URL = "https://www.cftc.gov/dea/newcot/f_disagg.txt"

    # WTI原油期货代码 (NYMEX) - 在报告中的第4列
    WTI_CODE = "067651"

    def __init__(self):
        super().__init__("cftc")

    def _parse_disaggregated_report(self, content: str) -> pd.DataFrame:
        """解析分类报告(Disaggregated Report)"""
        lines = content.strip().split('\n')

        records = []
        for line in lines:
            parts = line.split(',')

            # 检查是否是WTI数据 - 第4列是商品代码
            if len(parts) < 5:
                continue
            market_code = parts[3].strip().replace('"', '').strip()
            if market_code != self.WTI_CODE:
                continue

            try:
                # 第2列是日期格式 YYMMDD
                date_str = parts[1].strip().replace('"', '').strip()
                date = pd.to_datetime(date_str, format='%y%m%d')

                record = {
                    'date': date,
                    'market_code': market_code,
                    'market_name': parts[0].strip().replace('"', ''),
                    # 生产者/商户/加工者/用户 (第6-7列)
                    'prod_merc_long': int(parts[5].strip()),
                    'prod_merc_short': int(parts[6].strip()),
                    # 掉期商 (第8-10列)
                    'swap_long': int(parts[7].strip()),
                    'swap_short': int(parts[8].strip()),
                    'swap_spreads': int(parts[9].strip()),
                    # 资金管理人 (第11-13列)
                    'mm_long': int(parts[10].strip()),
                    'mm_short': int(parts[11].strip()),
                    'mm_spreads': int(parts[12].strip()),
                    # 其他报告持仓 (第14-16列)
                    'other_rept_long': int(parts[13].strip()),
                    'other_rept_short': int(parts[14].strip()),
                    'other_rept_spreads': int(parts[15].strip()),
                    # 非报告持仓 (第17-18列)
                    'nonrept_long': int(parts[16].strip()),
                    'nonrept_short': int(parts[17].strip()),
                    # 总持仓 (第19列)
                    'open_interest': int(parts[18].strip()),
                }
                records.append(record)
            except Exception as e:
                continue

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df = df.set_index('date')
        df = df.sort_index()

        return df

    def fetch(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取CFTC数据"""
        try:
            self.logger.info("下载CFTC分类报告...")
            response = requests.get(self.DISAGGREGATED_URL, timeout=60)
            response.raise_for_status()

            df = self._parse_disaggregated_report(response.text)

            if df.empty:
                self.logger.warning("未找到WTI数据")
                return pd.DataFrame()

            # 计算指标
            # 资金管理人净持仓 = 多仓 - 空仓
            df['WTI_MM_Net'] = df['mm_long'] - df['mm_short']

            # 期货交易量（用总持仓近似）
            df['WTI_Fut_Vol'] = df['open_interest']

            # 筛选日期
            if start_date:
                df = df[df.index >= start_date]
            if end_date:
                df = df[df.index <= end_date]

            if df.empty:
                return pd.DataFrame()

            # 重采样为日度（向前填充）
            df = df.resample('D').ffill()

            # 只保留需要的列
            result = df[['WTI_MM_Net', 'WTI_Fut_Vol']]

            self.logger.info(f"CFTC数据: {len(result)} 行")
            return result

        except Exception as e:
            self.logger.error(f"获取CFTC数据失败: {e}")
            return pd.DataFrame()


if __name__ == "__main__":
    fetcher = CFTCFetcher()
    df = fetcher.fetch("2024-01-01", "2024-12-31")
    print(df.tail())
    print(f"\n共获取 {len(df)} 行数据")
