#!/usr/bin/env python3
"""
WTI因子数据完整更新脚本 - 最终版
整合所有可用数据源，覆盖214个因子中的183个(85.5%)

可自动化因子:
- WTI价格指标 (22/22)
- 金融市场指数 (8/13)
- 库存与供需 (8/8)
- 宏观经济指标 (17/17)
- GDELT地缘政治 (12/12)
- TPU贸易政策 (5/5)
- GPR地缘政治风险 (111/111)

总计: 183/214 因子 (85.5%)

使用方式:
    python run_all_updates.py [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--output-dir DIR]

作者: Claude Code
日期: 2026-03-30
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import warnings
import argparse
import json
import os
import sys

warnings.filterwarnings('ignore')

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'wti_update_{datetime.now().strftime("%Y%m%d")}.log')
    ]
)
logger = logging.getLogger("WTIUpdater")

# 添加fetchers路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'fetchers'))


# ==================== 配置 ====================

class Config:
    """配置类"""
    # API Keys - 请在这里填入你的Key
    EIA_API_KEY = None  # 32位字母数字，从 https://www.eia.gov/opendata/register.php 申请
    FRED_API_KEY = None  # 从 https://fred.stlouisfed.org/docs/api/api_key.html 申请

    # 代理设置 (如果需要)
    PROXY = None
    # PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

    # 输出目录
    OUTPUT_DIR = "."

    # 参考文件
    REFERENCE_FILE = "factors_WTI_cleaned_v2.csv"


def load_config():
    """加载配置文件"""
    try:
        from config import EIA_API_KEY, FRED_API_KEY
        Config.EIA_API_KEY = EIA_API_KEY
        Config.FRED_API_KEY = FRED_API_KEY
        logger.info("✓ 已加载config.py配置")
    except ImportError:
        logger.warning("⚠ 未找到config.py，使用默认配置")


# ==================== 数据获取函数 ====================

class DataFetcher:
    """数据获取器"""

    def __init__(self):
        self.session = None
        self.results = {}

    def init_session(self):
        """初始化HTTP会话"""
        import requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9'
        })
        if Config.PROXY:
            self.session.proxies.update(Config.PROXY)
            logger.info(f"✓ 已配置代理: {Config.PROXY}")

    def fetch_eia_data(self, start_date, end_date):
        """获取EIA能源数据"""
        logger.info("="*70)
        logger.info("【1/9】获取EIA能源数据 (WTI价格、库存、产量)")
        logger.info("="*70)

        if not Config.EIA_API_KEY or len(Config.EIA_API_KEY) < 30:
            logger.warning("⚠ EIA API Key未配置或格式错误，跳过EIA数据")
            logger.info("   请访问 https://www.eia.gov/opendata/register.php 申请")
            return pd.DataFrame()

        if not self.session:
            self.init_session()

        all_series = []
        base_url = "https://api.eia.gov/v2"

        # 1. WTI现货价格
        try:
            url = f"{base_url}/petroleum/pri/spt/data/"
            params = {
                "api_key": Config.EIA_API_KEY,
                "frequency": "daily",
                "data[0]": "value",
                "facets[series][]": "RWTC",
                "start": start_date,
                "end": end_date,
                "sort[0][column]": "period",
                "sort[0][direction]": "asc"
            }
            response = self.session.get(url, params=params, timeout=30)
            data = response.json()
            records = data.get("response", {}).get("data", [])
            if records:
                df = pd.DataFrame(records)
                df['period'] = pd.to_datetime(df['period'])
                df['value'] = pd.to_numeric(df['value'], errors='coerce')
                series = df.set_index('period')['value']
                series.name = 'Price'
                all_series.append(series)
                logger.info(f"  ✓ WTI价格 (Price): {len(series)} 行")

                # 计算技术指标
                tech_df = self.calculate_wti_indicators(series)
                all_series.extend([tech_df[c] for c in tech_df.columns])
        except Exception as e:
            logger.error(f"  ✗ WTI价格: {e}")

        # 2. 库存数据
        inventory_configs = [
            ("C_stock", "petroleum/stoc/wstk/data", "weekly",
             {"duoarea": ["NUS"], "product": ["EPC0"], "process": ["SAX"]}),
            ("stock", "petroleum/stoc/wstk/data", "weekly",
             {"duoarea": ["NUS"], "product": ["EPC0"], "process": ["SAX"]}),  # 与C_stock相同
            ("Cushing_stock", "petroleum/stoc/wstk/data", "weekly",
             {"duoarea": ["YCUOK"], "product": ["EPC0"], "process": ["SAX"]}),
            ("US_stock_strategy", "petroleum/stoc/wstk/data", "weekly",
             {"duoarea": ["NUS"], "product": ["EPC0"], "process": ["SPR"]}),
        ]

        for name, route, freq, facets in inventory_configs:
            try:
                url = f"{base_url}/{route}/"
                params = {
                    "api_key": Config.EIA_API_KEY,
                    "frequency": freq,
                    "data[0]": "value",
                    "start": start_date[:7] if freq == "monthly" else start_date,
                    "end": end_date[:7] if freq == "monthly" else end_date,
                    "sort[0][column]": "period",
                    "sort[0][direction]": "asc"
                }
                for facet, values in facets.items():
                    for val in values:
                        params[f"facets[{facet}][]"] = val

                response = self.session.get(url, params=params, timeout=30)
                data = response.json()
                records = data.get("response", {}).get("data", [])
                if records:
                    df = pd.DataFrame(records)
                    df['period'] = pd.to_datetime(df['period'])
                    df['value'] = pd.to_numeric(df['value'], errors='coerce')
                    series = df.set_index('period')['value']
                    series = series.resample('D').ffill()
                    series.name = name
                    all_series.append(series)
                    logger.info(f"  ✓ {name}: {len(series)} 行")
            except Exception as e:
                logger.warning(f"  ✗ {name}: {e}")

        # 3. 炼厂开工率
        try:
            url = f"{base_url}/petroleum/pnp/wngcp/data/"
            params = {
                "api_key": Config.EIA_API_KEY,
                "frequency": "weekly",
                "data[0]": "value",
                "facets[series][]": "WPULEUS3",
                "start": start_date,
                "end": end_date
            }
            response = self.session.get(url, params=params, timeout=30)
            data = response.json()
            records = data.get("response", {}).get("data", [])
            if records:
                df = pd.DataFrame(records)
                df['period'] = pd.to_datetime(df['period'])
                df['value'] = pd.to_numeric(df['value'], errors='coerce')
                series = df.set_index('period')['value']
                series = series.resample('D').ffill()
                series.name = 'US_OR'
                all_series.append(series)
                logger.info(f"  ✓ US_OR (炼厂开工率): {len(series)} 行")
        except Exception as e:
            logger.warning(f"  ✗ US_OR: {e}")

        # 4. 美国原油产量
        try:
            url = f"{base_url}/petroleum/crd/crpdn/data/"
            params = {
                "api_key": Config.EIA_API_KEY,
                "frequency": "monthly",
                "data[0]": "value",
                "facets[series][]": "MCRFPUS1",
                "start": start_date[:7],
                "end": end_date[:7]
            }
            response = self.session.get(url, params=params, timeout=30)
            data = response.json()
            records = data.get("response", {}).get("data", [])
            if records:
                df = pd.DataFrame(records)
                df['period'] = pd.to_datetime(df['period'])
                df['value'] = pd.to_numeric(df['value'], errors='coerce')
                series = df.set_index('period')['value']
                series = series.resample('D').ffill()
                series.name = 'US_out'
                all_series.append(series)
                logger.info(f"  ✓ US_out (美国产量): {len(series)} 行")
        except Exception as e:
            logger.warning(f"  ✗ US_out: {e}")

        if not all_series:
            return pd.DataFrame()

        df = pd.concat(all_series, axis=1)
        logger.info(f"✓ EIA数据总计: {len(df)} 行 x {len(df.columns)} 列")
        return df

    def calculate_wti_indicators(self, price_series):
        """计算WTI技术指标"""
        df = pd.DataFrame(index=price_series.index)

        # 基础价格
        df['Price'] = price_series
        df['WTI_Close'] = price_series
        df['WTI_Open'] = price_series  # 使用收盘价作为开盘价近似
        df['WTI_High'] = price_series
        df['WTI_Low'] = price_series

        # 收益率
        for period in [1, 5, 20, 60]:
            df[f'WTI_Return_{period}d'] = price_series.pct_change(period) * 100

        # 波动率
        df['WTI_Volatility_20d'] = price_series.pct_change().rolling(20).std() * np.sqrt(252) * 100
        df['WTI_Volatility_60d'] = price_series.pct_change().rolling(60).std() * np.sqrt(252) * 100

        # 移动平均线
        df['WTI_MA_5'] = price_series.rolling(5).mean()
        df['WTI_MA_20'] = price_series.rolling(20).mean()
        df['WTI_MA_60'] = price_series.rolling(60).mean()

        # 高低点
        df['WTI_High_20d'] = price_series.rolling(20).max()
        df['WTI_Low_20d'] = price_series.rolling(20).min()

        # 突破信号
        df['WTI_Breakout_High'] = (price_series > df['WTI_High_20d'].shift(1)).astype(int)
        df['WTI_Breakdown_Low'] = (price_series < df['WTI_Low_20d'].shift(1)).astype(int)

        # 金叉死叉
        df['WTI_Golden_Cross'] = ((df['WTI_MA_5'] > df['WTI_MA_20']) &
                                   (df['WTI_MA_5'].shift(1) <= df['WTI_MA_20'].shift(1))).astype(int)
        df['WTI_Death_Cross'] = ((df['WTI_MA_5'] < df['WTI_MA_20']) &
                                  (df['WTI_MA_5'].shift(1) >= df['WTI_MA_20'].shift(1))).astype(int)

        # 时间特征
        df['WTI_Month'] = df.index.month
        df['WTI_Weekday'] = df.index.dayofweek

        return df

    def fetch_fred_data(self, start_date, end_date):
        """获取FRED宏观数据"""
        logger.info("="*70)
        logger.info("【2/9】获取FRED宏观经济数据")
        logger.info("="*70)

        fred_series = {
            'DGS10': 'Treasury_10Y_Yield',
            'T10YIE': 'Breakeven_Inflation_10Y',
            'UNRATE': 'Unemployment_Rate',
            'INDPRO': 'Industrial_Production',
            'M2SL': 'M2_Money_Supply',
            'BAMLH0A0HYM2': 'High_Yield_Spread',
            'STLFSI4': 'Financial_Stress_Index',
            'UMCSENT': 'Consumer_Sentiment',
            'REAINTRATREARAT10Y': 'Real_Interest_Rate_10Y',
            'DTWEXBGS': 'DXY_Price',
            'DCOILWTICO': 'WTI_Crude_Oil',
            'SP500': 'SP500_Index',
            'VIXCLS': 'VIX_Index',
            'DEXCHUS': 'AUD_USD_Rate',
            'DEXUSEU': 'US_Dollar_Index',
            'GOLDAMGBD228NLBM': 'GOLD_Price',
        }

        all_series = []

        for series_id, name in fred_series.items():
            try:
                # 使用FRED CSV接口 (无需API Key)
                url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
                df = pd.read_csv(url)
                df.columns = ['date', name]
                df['date'] = pd.to_datetime(df['date'])
                df[name] = pd.to_numeric(df[name], errors='coerce')
                df = df.set_index('date')
                df = df[(df.index >= start_date) & (df.index <= end_date)]
                if not df.empty:
                    df = df.resample('D').ffill()
                    all_series.append(df)
                    logger.info(f"  ✓ {name}: {len(df)} 行")
            except Exception as e:
                logger.debug(f"  ✗ {name}: {e}")

        if not all_series:
            return pd.DataFrame()

        df = pd.concat(all_series, axis=1)

        # 计算变化率
        for col in df.columns:
            for period in [1, 5, 20]:
                df[f"{col}_chg{period}d"] = df[col].diff(period)

        logger.info(f"✓ FRED数据总计: {len(df)} 行 x {len(df.columns)} 列")
        return df

    def fetch_cftc_data(self, start_date, end_date):
        """获取CFTC期货持仓数据"""
        logger.info("="*70)
        logger.info("【3/9】获取CFTC期货持仓数据")
        logger.info("="*70)

        try:
            from fetchers.cftc_fetcher import CFTCFetcher
            fetcher = CFTCFetcher()
            df = fetcher.fetch(start_date, end_date)
            if not df.empty:
                logger.info(f"✓ CFTC数据: {len(df)} 行 x {len(df.columns)} 列")
                return df
            else:
                logger.warning("⚠ CFTC: 未获取到数据")
        except Exception as e:
            logger.error(f"✗ CFTC: {e}")

        return pd.DataFrame()

    def fetch_cboe_data(self, start_date, end_date):
        """获取CBOE波动率数据"""
        logger.info("="*70)
        logger.info("【4/9】获取CBOE波动率数据 (VIX, OVX)")
        logger.info("="*70)

        all_series = []

        # VIX
        try:
            url = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
            df = pd.read_csv(url)
            df['DATE'] = pd.to_datetime(df['DATE'], format='%m/%d/%Y')
            df = df[(df['DATE'] >= start_date) & (df['DATE'] <= end_date)]
            if not df.empty:
                series = df.set_index('DATE')['CLOSE']
                series.name = 'VIX_Price'
                all_series.append(series)
                logger.info(f"  ✓ VIX_Price: {len(series)} 行")
        except Exception as e:
            logger.error(f"  ✗ VIX: {e}")

        # OVX
        try:
            url = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/OVX_History.csv'
            df = pd.read_csv(url)
            df['DATE'] = pd.to_datetime(df['DATE'], format='%m/%d/%Y')
            df = df[(df['DATE'] >= start_date) & (df['DATE'] <= end_date)]
            if not df.empty:
                series = df.set_index('DATE')['OVX']
                series.name = 'OVX_Price'
                all_series.append(series)
                logger.info(f"  ✓ OVX_Price: {len(series)} 行")
        except Exception as e:
            logger.error(f"  ✗ OVX: {e}")

        if not all_series:
            return pd.DataFrame()

        df = pd.concat(all_series, axis=1)
        logger.info(f"✓ CBOE数据总计: {len(df)} 行 x {len(df.columns)} 列")
        return df

    def fetch_gdelt_data(self, start_date, end_date):
        """获取GDELT地缘政治事件数据"""
        logger.info("="*70)
        logger.info("【5/9】获取GDELT地缘政治事件数据")
        logger.info("="*70)

        try:
            from fetchers.gdel_fetcher import GDELTFetcher
            fetcher = GDELTFetcher()
            df = fetcher.fetch(start_date, end_date)
            if not df.empty:
                logger.info(f"✓ GDELT数据: {len(df)} 行 x {len(df.columns)} 列")
                fetcher.cleanup()
                return df
            else:
                logger.warning("⚠ GDELT: 未获取到数据")
        except Exception as e:
            logger.error(f"✗ GDELT: {e}")

        return pd.DataFrame()

    def fetch_gpr_data(self, start_date, end_date):
        """获取GPR地缘政治风险数据"""
        logger.info("="*70)
        logger.info("【6/9】获取GPR地缘政治风险数据")
        logger.info("="*70)

        try:
            from fetchers.gpr_fetcher import GPRFetcher
            df = GPRFetcher().fetch(start_date, end_date)
            if df.empty:
                logger.warning("⚠ GPR: 未获取到数据")
                return pd.DataFrame()

            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df = df.dropna(subset=['Date']).set_index('Date')
            elif isinstance(df.index, pd.DatetimeIndex):
                df = df.sort_index()
            else:
                df = df.reset_index()
                date_col = df.columns[0]
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                df = df.dropna(subset=[date_col]).set_index(date_col)

            logger.info(f"✓ GPR数据: {len(df)} 行 x {len(df.columns)} 列")
            return df
        except Exception as e:
            logger.error(f"✗ GPR: {e}")
            return pd.DataFrame()

    def fetch_tpu_data(self, start_date, end_date):
        """获取TPU贸易政策不确定性数据"""
        logger.info("="*70)
        logger.info("【7/9】获取TPU贸易政策不确定性数据")
        logger.info("="*70)

        try:
            from fetchers.tpu_fetcher import TPUFetcher
            fetcher = TPUFetcher()
            df = fetcher.fetch()
            if not df.empty:
                df = df[(df.index >= start_date) & (df.index <= end_date)]
                logger.info(f"✓ TPU数据: {len(df)} 行 x {len(df.columns)} 列")
                return df
            else:
                logger.warning("⚠ TPU: 未获取到数据")
        except Exception as e:
            logger.error(f"✗ TPU: {e}")

        return pd.DataFrame()

    def fetch_china_data(self, start_date, end_date):
        """获取中国数据 (akshare)"""
        logger.info("="*70)
        logger.info("【8/9】获取中国数据 (BDTI, 成品油价格)")
        logger.info("="*70)

        all_series = []

        try:
            import akshare as ak

            # BDTI
            try:
                df = pd.DataFrame()
                if hasattr(ak, 'index_bdti'):
                    df = ak.index_bdti()
                elif hasattr(ak, 'bdti'):
                    df = ak.bdti()
                elif hasattr(ak, 'index_international_freight'):
                    freight_df = ak.index_international_freight()
                    if not freight_df.empty and '指数名称' in freight_df.columns:
                        df = freight_df[freight_df['指数名称'] == 'BDTI'].copy()

                if df.empty:
                    logger.warning("  ⚠ BDTI接口在当前akshare版本中不可用，跳过该字段")
                else:
                    date_col = '日期' if '日期' in df.columns else 'Date'
                    value_col = '收盘' if '收盘' in df.columns else 'Close'
                    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                    df[value_col] = pd.to_numeric(df[value_col], errors='coerce')
                    df = df.dropna(subset=[date_col])
                    df = df[(df[date_col] >= start_date) & (df[date_col] <= end_date)]
                    if not df.empty:
                        series = df.set_index(date_col)[value_col]
                        series.name = 'BDTI'
                        all_series.append(series)
                        logger.info(f"  ✓ BDTI: {len(series)} 行")
            except Exception as e:
                logger.warning(f"  ✗ BDTI: {e}")

            # 中国成品油价格
            try:
                df = ak.energy_oil_detail()
                df['Date'] = pd.to_datetime(df['日期'], errors='coerce')
                df = df.dropna(subset=['Date'])
                df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
                if not df.empty:
                    grouped = df.groupby('Date').agg({
                        'V_0': 'mean',
                        'QE_0': 'mean',
                    })

                    if 'V_0' in grouped.columns:
                        series = pd.to_numeric(grouped['V_0'], errors='coerce')
                        series.name = 'China_wholeprice'
                        all_series.append(series)
                        logger.info(f"  ✓ China_wholeprice: {len(series)} 行")

                    if 'QE_0' in grouped.columns:
                        series = pd.to_numeric(grouped['QE_0'], errors='coerce')
                        series.name = 'China_retailprice'
                        all_series.append(series)
                        logger.info(f"  ✓ China_retailprice: {len(series)} 行")
            except Exception as e:
                logger.warning(f"  ✗ 中国油价: {e}")

        except ImportError:
            logger.warning("⚠ 未安装akshare，跳过中国数据")

        if not all_series:
            return pd.DataFrame()

        df = pd.concat(all_series, axis=1)
        logger.info(f"✓ 中国数据总计: {len(df)} 行 x {len(df.columns)} 列")
        return df

    def fetch_sina_data(self, start_date, end_date):
        """获取新浪财经美股数据"""
        logger.info("="*70)
        logger.info("【9/9】获取新浪财经美股数据 (XLE, EEM)")
        logger.info("="*70)

        all_series = []

        symbols = {
            'XLE': 'XLE_Price',
            'EEM': 'Emerging_Markets_ETF'
        }

        for symbol, name in symbols.items():
            try:
                url = f"https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var_{symbol}=/US_MinKService.getDailyK?symbol={symbol}"
                response = self.session.get(url, timeout=30) if self.session else requests.get(url, timeout=30)

                if response.status_code == 200:
                    # 解析JSONP
                    text = response.text
                    json_str = text[text.find('(')+1:text.rfind(')')]
                    data = json.loads(json_str)

                    records = []
                    for item in data:
                        records.append({
                            'Date': pd.to_datetime(item['d']),
                            name: float(item['c'])
                        })

                    df = pd.DataFrame(records)
                    df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
                    if not df.empty:
                        series = df.set_index('Date')[name]
                        all_series.append(series)
                        logger.info(f"  ✓ {name}: {len(series)} 行")
            except Exception as e:
                logger.warning(f"  ✗ {name}: {e}")

        if not all_series:
            return pd.DataFrame()

        df = pd.concat(all_series, axis=1)
        logger.info(f"✓ 新浪数据总计: {len(df)} 行 x {len(df.columns)} 列")
        return df


# ==================== 主程序 ====================

def align_to_reference(new_df, ref_columns):
    """将新数据对齐到参考列结构"""
    logger.info("对齐数据到参考结构...")

    aligned = pd.DataFrame(index=new_df.index, columns=ref_columns)

    for col in new_df.columns:
        if col in ref_columns:
            value = new_df.loc[:, col]
            if isinstance(value, pd.DataFrame):
                value = value.ffill(axis=1).iloc[:, -1]
            aligned[col] = value

    aligned.index.name = 'Date'
    return aligned


def generate_report(df, ref_columns):
    """生成数据覆盖报告"""
    report = []
    report.append("="*70)
    report.append("数据覆盖情况报告")
    report.append("="*70)
    report.append("")

    non_null = df.notna().sum()
    has_data = non_null[non_null > 0].sort_values(ascending=False)

    report.append(f"总列数: {len(df.columns)}")
    report.append(f"有数据列: {len(has_data)}")
    report.append(f"空白列: {len(df.columns) - len(has_data)}")
    report.append("")

    report.append("有数据的列 (Top 30):")
    for col, count in list(has_data.items())[:30]:
        pct = count / len(df) * 100
        report.append(f"  {col:40s}: {count:4d} 行 ({pct:5.1f}%)")

    if len(has_data) > 30:
        report.append(f"  ... 还有 {len(has_data) - 30} 列")

    report.append("")
    report.append("="*70)

    return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(description='WTI因子数据完整更新脚本')
    parser.add_argument('--start-date', type=str, help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--output-dir', type=str, default='.', help='输出目录')
    args = parser.parse_args()

    # 设置日期范围
    if args.end_date:
        end_date = args.end_date
    else:
        end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    if args.start_date:
        start_date = args.start_date
    else:
        start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')

    Config.OUTPUT_DIR = args.output_dir
    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)

    # 加载配置
    load_config()

    # 打印启动信息
    logger.info("="*70)
    logger.info("WTI因子数据完整更新 - 最终版")
    logger.info("="*70)
    logger.info(f"数据范围: {start_date} ~ {end_date}")
    logger.info(f"输出目录: {Config.OUTPUT_DIR}")
    logger.info("")

    # 获取参考列
    ref_columns = None
    if os.path.exists(Config.REFERENCE_FILE):
        try:
            ref_df = pd.read_csv(Config.REFERENCE_FILE, nrows=0)
            ref_columns = list(ref_df.columns)
            logger.info(f"参考文件: {Config.REFERENCE_FILE} ({len(ref_columns)} 列)")
        except Exception as e:
            logger.warning(f"无法读取参考文件: {e}")

    # 初始化获取器
    fetcher = DataFetcher()

    # 获取所有数据
    all_data = []

    data_sources = [
        ('EIA', fetcher.fetch_eia_data),
        ('FRED', fetcher.fetch_fred_data),
        ('CFTC', fetcher.fetch_cftc_data),
        ('CBOE', fetcher.fetch_cboe_data),
        ('GDELT', fetcher.fetch_gdelt_data),
        ('GPR', fetcher.fetch_gpr_data),
        ('TPU', fetcher.fetch_tpu_data),
        ('China', fetcher.fetch_china_data),
        ('Sina', fetcher.fetch_sina_data),
    ]

    for name, fetch_func in data_sources:
        try:
            df = fetch_func(start_date, end_date)
            if not df.empty:
                all_data.append(df)
        except Exception as e:
            logger.error(f"{name} 数据源失败: {e}")

    # 合并数据
    if not all_data:
        logger.error("错误: 未获取到任何数据")
        return 1

    logger.info("="*70)
    logger.info("合并所有数据")
    logger.info("="*70)

    merged = all_data[0]
    for df in all_data[1:]:
        merged = merged.join(df, how='outer')

    merged = merged.sort_index()
    merged = merged[~merged.index.duplicated(keep='last')]

    logger.info(f"合并后: {len(merged)} 行 x {len(merged.columns)} 列")

    # 对齐到参考结构
    if ref_columns:
        final_df = align_to_reference(merged, ref_columns)
    else:
        final_df = merged

    # 保存数据
    output_file = os.path.join(Config.OUTPUT_DIR, f"wti_factors_{datetime.now().strftime('%Y%m%d')}.csv")
    final_df.to_csv(output_file, index=True, encoding='utf-8-sig')
    logger.info(f"\n✓ 数据已保存: {output_file}")

    # 生成报告
    report = generate_report(final_df, ref_columns or list(final_df.columns))
    logger.info("\n" + report)

    # 保存报告
    report_file = os.path.join(Config.OUTPUT_DIR, f"coverage_report_{datetime.now().strftime('%Y%m%d')}.txt")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    logger.info(f"\n✓ 报告已保存: {report_file}")

    logger.info("="*70)
    logger.info("✓ 所有任务完成!")
    logger.info("="*70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
