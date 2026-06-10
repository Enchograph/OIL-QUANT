"""
免费数据源整合模块
覆盖尽可能多的缺失因子
"""

import pandas as pd
import requests
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
import json


class FreeDataFetcher:
    """整合所有可用免费API的数据获取器"""

    def __init__(self, alpha_vantage_key: Optional[str] = None, proxy: Optional[Dict] = None):
        self.alpha_vantage_key = alpha_vantage_key
        self.session = requests.Session()
        # 更完整的headers，模拟真实浏览器
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        })
        # 代理设置
        if proxy:
            self.session.proxies.update(proxy)
            print(f"已配置代理: {proxy}")

    # ==================== 1. CBOE 数据 (免费) ====================

    def get_vix(self, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """
        获取VIX波动率指数 (CBOE免费CSV)
        https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
        """
        try:
            url = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
            df = pd.read_csv(url)
            df['DATE'] = pd.to_datetime(df['DATE'], format='%m/%d/%Y')
            df = df.rename(columns={
                'DATE': 'Date',
                'CLOSE': 'VIX_Price'
            })

            if start_date:
                df = df[df['Date'] >= start_date]
            if end_date:
                df = df[df['Date'] <= end_date]

            print(f"✓ VIX数据获取成功: {len(df)} 条")
            return df[['Date', 'VIX_Price']].sort_values('Date')
        except Exception as e:
            print(f"✗ VIX获取失败: {e}")
            return None

    def get_ovx(self, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """
        获取OVX原油波动率指数 (CBOE免费CSV)
        https://cdn.cboe.com/api/global/us_indices/daily_prices/OVX_History.csv
        """
        try:
            url = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/OVX_History.csv'
            df = pd.read_csv(url)
            df['DATE'] = pd.to_datetime(df['DATE'], format='%m/%d/%Y')
            df = df.rename(columns={
                'DATE': 'Date',
                'OVX': 'OVX_Price'
            })

            if start_date:
                df = df[df['Date'] >= start_date]
            if end_date:
                df = df[df['Date'] <= end_date]

            print(f"✓ OVX数据获取成功: {len(df)} 条")
            return df[['Date', 'OVX_Price']].sort_values('Date')
        except Exception as e:
            print(f"✗ OVX获取失败: {e}")
            return None

    # ==================== 2. EIA 数据 (免费) ====================

    def get_wti_spot(self, eia_api_key: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """
        获取WTI原油现货价格 (EIA免费API)
        Series: RWTC (Cushing WTI Spot Price)
        """
        try:
            # 验证API Key格式
            if not eia_api_key or len(eia_api_key) < 20 or 'http' in eia_api_key:
                print(f"✗ EIA API Key格式错误: {eia_api_key[:50] if eia_api_key else 'None'}...")
                print("  请访问 https://www.eia.gov/opendata/register.php 申请正确的API Key")
                return None

            url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
            params = {
                "api_key": eia_api_key,
                "frequency": "daily",
                "data[0]": "value",
                "facets[series][]": "RWTC",
                "sort[0][column]": "period",
                "sort[0][direction]": "asc"
            }
            if start_date:
                params["start"] = start_date
            if end_date:
                params["end"] = end_date

            response = self.session.get(url, params=params, timeout=30)

            if response.status_code != 200:
                print(f"✗ WTI现货: HTTP {response.status_code}")
                print(f"  响应内容: {response.text[:200]}")
                return None

            data = response.json()

            # 检查API错误
            if 'error' in data:
                print(f"✗ WTI现货 API错误: {data['error']}")
                return None

            records = data.get("response", {}).get("data", [])

            if not records:
                print("✗ WTI现货: 无数据返回")
                return None

            df = pd.DataFrame(records)
            df['period'] = pd.to_datetime(df['period'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
            df = df.rename(columns={
                'period': 'Date',
                'value': 'WTI_Crude_Oil'
            })

            print(f"✓ WTI现货价格获取成功: {len(df)} 条")
            return df[['Date', 'WTI_Crude_Oil']].sort_values('Date')
        except Exception as e:
            print(f"✗ WTI现货获取失败: {e}")
            return None

    def get_wti_futures(self, eia_api_key: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """
        获取WTI期货价格 (EIA免费API)
        """
        try:
            # EIA WTI期货数据
            url = "https://api.eia.gov/v2/petroleum/pri/fut/data/"
            params = {
                "api_key": eia_api_key,
                "frequency": "daily",
                "data[0]": "value",
                "facets[series][]": "EER_EPD2F_PE1_NUS_DPG",  # WTI Futures
                "sort[0][column]": "period",
                "sort[0][direction]": "asc"
            }
            if start_date:
                params["start"] = start_date
            if end_date:
                params["end"] = end_date

            response = self.session.get(url, params=params, timeout=30)
            data = response.json()
            records = data.get("response", {}).get("data", [])

            if records:
                df = pd.DataFrame(records)
                df['period'] = pd.to_datetime(df['period'])
                df['value'] = pd.to_numeric(df['value'], errors='coerce')
                df = df.rename(columns={
                    'period': 'Date',
                    'value': 'WTI_Fut_Price'
                })
                print(f"✓ WTI期货价格获取成功: {len(df)} 条")
                return df[['Date', 'WTI_Fut_Price']].sort_values('Date')
            else:
                print("✗ WTI期货: EIA无此数据，尝试其他来源")
                return None
        except Exception as e:
            print(f"✗ WTI期货获取失败: {e}")
            return None

    # ==================== 3. Yahoo Finance (免费但有限流) ====================

    def get_yahoo_data(self, symbol: str, start_date: str = None, end_date: str = None,
                       column_name: str = None, max_retries: int = 3) -> Optional[pd.DataFrame]:
        """
        从Yahoo Finance获取数据 (有频率限制)
        使用更完善的请求头和重试机制
        """
        import time
        import random

        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

        start_ts = int(pd.Timestamp(start_date).timestamp())
        end_ts = int(pd.Timestamp(end_date).timestamp())

        # 编码symbol
        encoded_symbol = symbol.replace('=', '%3D').replace('^', '%5E')

        url = f"https://query1.finance.yahoo.com/v7/finance/download/{encoded_symbol}"
        params = {
            'period1': start_ts,
            'period2': end_ts,
            'interval': '1d',
            'events': 'history'
        }

        # 使用专门的headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/csv;charset=utf-8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://finance.yahoo.com/',
            'Origin': 'https://finance.yahoo.com'
        }

        for attempt in range(max_retries):
            try:
                # 添加随机延时避免限流
                if attempt > 0:
                    delay = random.uniform(2, 5)
                    print(f"  重试 {attempt}/{max_retries}, 等待 {delay:.1f} 秒...")
                    time.sleep(delay)

                response = self.session.get(url, params=params, headers=headers, timeout=30)

                if response.status_code == 200:
                    df = pd.read_csv(pd.io.common.StringIO(response.text))
                    df['Date'] = pd.to_datetime(df['Date'])

                    if column_name:
                        df = df.rename(columns={'Close': column_name})
                        return df[['Date', column_name]].sort_values('Date')
                    return df.sort_values('Date')

                elif response.status_code == 401:
                    print(f"✗ Yahoo {symbol}: 401 未授权，可能需要cookie")
                    # 尝试获取cookie
                    try:
                        crumb_url = "https://query1.finance.yahoo.com/v1/test/getcrumb"
                        crumb_response = self.session.get(crumb_url, headers=headers, timeout=10)
                        if crumb_response.status_code == 200:
                            crumb = crumb_response.text
                            params['crumb'] = crumb
                            continue
                    except:
                        pass
                    break

                elif response.status_code == 429:
                    print(f"✗ Yahoo {symbol}: 429 请求过于频繁")
                    if attempt < max_retries - 1:
                        time.sleep(5)
                        continue

                else:
                    print(f"✗ Yahoo {symbol}: 状态码 {response.status_code}")
                    if attempt < max_retries - 1:
                        continue

            except Exception as e:
                print(f"✗ Yahoo {symbol} 尝试 {attempt+1} 失败: {e}")
                if attempt < max_retries - 1:
                    continue

        return None

    def get_gold_futures(self, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """获取黄金期货 GC=F"""
        df = self.get_yahoo_data('GC=F', start_date, end_date, 'Gold_Futures')
        if df is not None:
            print(f"✓ 黄金期货(GC=F)获取成功: {len(df)} 条")
        return df

    def get_spx(self, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """获取标普500指数 ^GSPC"""
        df = self.get_yahoo_data('^GSPC', start_date, end_date, 'SPX_Price')
        if df is not None:
            print(f"✓ 标普500指数获取成功: {len(df)} 条")
        return df

    # ==================== 4. Alpha Vantage (免费500次/天) ====================

    def get_alpha_vantage_data(self, symbol: str, column_name: str) -> Optional[pd.DataFrame]:
        """
        使用Alpha Vantage API获取数据
        免费版: 500次/天
        """
        if not self.alpha_vantage_key:
            print(f"✗ Alpha Vantage: 未提供API Key")
            return None

        try:
            url = "https://www.alphavantage.co/query"
            params = {
                'function': 'TIME_SERIES_DAILY',
                'symbol': symbol,
                'apikey': self.alpha_vantage_key,
                'outputsize': 'full',
                'datatype': 'json'
            }

            response = self.session.get(url, params=params, timeout=30)
            data = response.json()

            if 'Time Series (Daily)' not in data:
                print(f"✗ Alpha Vantage {symbol}: {data.get('Note', '未知错误')}")
                return None

            ts_data = data['Time Series (Daily)']
            records = []
            for date_str, values in ts_data.items():
                records.append({
                    'Date': pd.to_datetime(date_str),
                    column_name: float(values['4. close'])
                })

            df = pd.DataFrame(records).sort_values('Date')
            print(f"✓ Alpha Vantage {symbol}获取成功: {len(df)} 条")
            time.sleep(12)  # 免费版限制5次/分钟
            return df
        except Exception as e:
            print(f"✗ Alpha Vantage {symbol} 失败: {e}")
            return None

    # ==================== 5. 加密货币 (免费) ====================

    def get_btc_price(self, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """
        获取比特币价格 (CoinGecko免费API)
        """
        try:
            url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            params = {
                'vs_currency': 'usd',
                'days': '365',
                'interval': 'daily'
            }

            response = self.session.get(url, params=params, timeout=30)
            data = response.json()

            if 'prices' not in data:
                print("✗ CoinGecko BTC: 无价格数据")
                return None

            prices = data['prices']
            df = pd.DataFrame(prices, columns=['timestamp', 'BTC_Price'])
            df['Date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.date
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.groupby('Date')['BTC_Price'].last().reset_index()

            if start_date:
                df = df[df['Date'] >= start_date]
            if end_date:
                df = df[df['Date'] <= end_date]

            print(f"✓ BTC价格获取成功: {len(df)} 条")
            return df[['Date', 'BTC_Price']].sort_values('Date')
        except Exception as e:
            print(f"✗ BTC获取失败: {e}")
            return None

    # ==================== 6. FRED 数据 (免费) ====================

    def get_fred_data(self, series_id: str, fred_api_key: str,
                      start_date: str = None, end_date: str = None,
                      column_name: str = None) -> Optional[pd.DataFrame]:
        """
        获取FRED经济数据 (免费API)
        """
        try:
            url = f"https://api.stlouisfed.org/fred/series/observations"
            params = {
                'series_id': series_id,
                'api_key': fred_api_key,
                'file_type': 'json',
                'sort_order': 'asc'
            }
            if start_date:
                params['observation_start'] = start_date
            if end_date:
                params['observation_end'] = end_date

            response = self.session.get(url, params=params, timeout=30)
            data = response.json()

            if 'observations' not in data:
                print(f"✗ FRED {series_id}: 无数据")
                return None

            observations = data['observations']
            records = []
            for obs in observations:
                value = obs['value']
                if value and value != '.':
                    records.append({
                        'Date': pd.to_datetime(obs['date']),
                        column_name or series_id: float(value)
                    })

            df = pd.DataFrame(records)
            print(f"✓ FRED {series_id}获取成功: {len(df)} 条")
            return df.sort_values('Date')
        except Exception as e:
            print(f"✗ FRED {series_id} 失败: {e}")
            return None

    # ==================== 7. 商品指数替代方案 ====================

    def get_crb_alternative(self, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """
        获取CRB替代数据 (使用Bloomberg Commodity Index ETF: DBC)
        注意: 这是替代指标，非官方CRB指数
        """
        try:
            # DBC是Bloomberg Commodity Index的ETF，可作为CRB的替代
            df = self.get_yahoo_data('DBC', start_date, end_date, 'CRB_Price_Alt')
            if df is not None:
                print(f"✓ CRB替代数据(DBC ETF)获取成功: {len(df)} 条")
            return df
        except Exception as e:
            print(f"✗ CRB替代获取失败: {e}")
            return None

    # ==================== 8. 计算WTI基差 ====================

    def calculate_wti_basis(self, spot_df: pd.DataFrame, fut_df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        计算WTI基差 = 期货价格 - 现货价格
        """
        try:
            if spot_df is None or fut_df is None:
                print("✗ WTI基差计算: 缺少现货或期货数据")
                return None

            merged = pd.merge(spot_df, fut_df, on='Date', how='inner')
            if len(merged) == 0:
                print("✗ WTI基差计算: 无重叠日期")
                return None

            merged['WTI_Basis'] = merged['WTI_Fut_Price'] - merged['WTI_Crude_Oil']
            print(f"✓ WTI基差计算成功: {len(merged)} 条")
            return merged[['Date', 'WTI_Basis']]
        except Exception as e:
            print(f"✗ WTI基差计算失败: {e}")
            return None

    # ==================== 综合获取所有数据 ====================

    def fetch_all_free_data(self, eia_api_key: str = None, fred_api_key: str = None,
                           start_date: str = None, end_date: str = None) -> Dict[str, pd.DataFrame]:
        """
        获取所有可用的免费数据

        Args:
            eia_api_key: EIA API Key (免费申请)
            fred_api_key: FRED API Key (免费申请)
            start_date: 开始日期 '2026-01-01'
            end_date: 结束日期 '2026-03-30'

        Returns:
            Dict[str, pd.DataFrame]: 各因子数据字典
        """
        results = {}

        print("=" * 60)
        print("开始获取免费数据源...")
        print("=" * 60)

        # 1. CBOE数据 (VIX, OVX) - 免费
        print("\n【1/8】CBOE波动率数据...")
        results['vix'] = self.get_vix(start_date, end_date)
        results['ovx'] = self.get_ovx(start_date, end_date)

        # 2. EIA数据 (WTI现货、期货) - 免费
        if eia_api_key:
            print("\n【2/8】EIA能源数据...")
            results['wti_spot'] = self.get_wti_spot(eia_api_key, start_date, end_date)
            results['wti_fut'] = self.get_wti_futures(eia_api_key, start_date, end_date)
        else:
            print("\n【2/8】跳过EIA数据 (未提供API Key)")

        # 3. Yahoo Finance (黄金期货、标普500) - 免费有限流
        print("\n【3/8】Yahoo Finance数据...")
        results['gold'] = self.get_gold_futures(start_date, end_date)
        results['spx'] = self.get_spx(start_date, end_date)

        # 4. Alpha Vantage (备用) - 免费500次/天
        if self.alpha_vantage_key:
            print("\n【4/8】Alpha Vantage数据...")
            # 仅在Yahoo失败时使用
            if results['gold'] is None:
                results['gold'] = self.get_alpha_vantage_data('GC=F', 'Gold_Futures')
        else:
            print("\n【4/8】跳过Alpha Vantage (未提供API Key)")

        # 5. 加密货币 (BTC) - 免费
        print("\n【5/8】加密货币数据...")
        results['btc'] = self.get_btc_price(start_date, end_date)

        # 6. FRED数据 - 免费
        if fred_api_key:
            print("\n【6/8】FRED经济数据...")
            results['dollar_index'] = self.get_fred_data('DTWEXBGS', fred_api_key, start_date, end_date, 'Dollar_Index')
        else:
            print("\n【6/8】跳过FRED数据 (未提供API Key)")

        # 7. CRB替代 - 免费
        print("\n【7/8】商品指数替代数据...")
        results['crb_alt'] = self.get_crb_alternative(start_date, end_date)

        # 8. 计算WTI基差
        print("\n【8/8】计算WTI基差...")
        results['wti_basis'] = self.calculate_wti_basis(
            results.get('wti_spot'),
            results.get('wti_fut')
        )

        # 统计结果
        print("\n" + "=" * 60)
        print("免费数据获取完成!")
        print("=" * 60)
        success_count = sum(1 for v in results.values() if v is not None)
        print(f"成功: {success_count}/{len(results)} 个数据源")

        for name, df in results.items():
            if df is not None:
                print(f"  ✓ {name}: {len(df)} 条")
            else:
                print(f"  ✗ {name}: 失败")

        return results


def merge_free_data(results: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    将所有获取到的免费数据合并为一个DataFrame
    """
    merged = None

    column_mapping = {
        'vix': 'VIX_Price',
        'ovx': 'OVX_Price',
        'wti_spot': 'WTI_Crude_Oil',
        'wti_fut': 'WTI_Fut_Price',
        'gold': 'Gold_Futures',
        'spx': 'SPX_Price',
        'btc': 'BTC_Price',
        'crb_alt': 'CRB_Price_Alt',
        'wti_basis': 'WTI_Basis',
        'dollar_index': 'Dollar_Index'
    }

    for key, df in results.items():
        if df is None or df.empty:
            continue

        # 标准化列名
        if key in column_mapping:
            value_col = [c for c in df.columns if c != 'Date'][0]
            df = df.rename(columns={value_col: column_mapping[key]})

        if merged is None:
            merged = df
        else:
            merged = pd.merge(merged, df, on='Date', how='outer')

    if merged is not None:
        merged = merged.sort_values('Date')

    return merged


if __name__ == '__main__':
    # 示例使用
    fetcher = FreeDataFetcher(alpha_vantage_key=None)

    # 获取最近30天的数据
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    # 这里需要填入你的API Key
    EIA_API_KEY = "your_eia_api_key"  # 免费申请: https://www.eia.gov/opendata/
    FRED_API_KEY = "your_fred_api_key"  # 免费申请: https://fred.stlouisfed.org/docs/api/api_key.html

    results = fetcher.fetch_all_free_data(
        eia_api_key=EIA_API_KEY if EIA_API_KEY != "your_eia_api_key" else None,
        fred_api_key=FRED_API_KEY if FRED_API_KEY != "your_fred_api_key" else None,
        start_date=start,
        end_date=end
    )

    # 合并数据
    combined = merge_free_data(results)
    if combined is not None:
        print(f"\n合并后数据: {len(combined)} 行, {len(combined.columns)} 列")
        print(combined.head())
