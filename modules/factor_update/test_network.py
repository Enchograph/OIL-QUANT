#!/usr/bin/env python3
"""
网络连接测试脚本
测试各个数据源的连通性
"""

import requests
import sys

def test_cboE():
    """测试CBOE"""
    print("测试 CBOE (VIX数据)...")
    try:
        url = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            lines = response.text.strip().split('\n')
            print(f"  ✓ 连接成功，数据行数: {len(lines)}")
            return True
        else:
            print(f"  ✗ HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False

def test_yahoo():
    """测试Yahoo Finance"""
    print("\n测试 Yahoo Finance...")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        url = "https://query1.finance.yahoo.com/v7/finance/download/GC=F"
        params = {
            'period1': 1700000000,
            'period2': 1700000000,
            'interval': '1d',
            'events': 'history'
        }
        response = requests.get(url, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            print(f"  ✓ 连接成功")
            return True
        elif response.status_code == 401:
            print(f"  ⚠️ 401 未授权 (需要cookie/crumb)")
            return False
        elif response.status_code == 429:
            print(f"  ⚠️ 429 限流")
            return False
        else:
            print(f"  ✗ HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False

def test_eia(api_key=None):
    """测试EIA"""
    print("\n测试 EIA API...")
    try:
        if not api_key:
            print("  ⚠️ 未提供API Key，跳过")
            return None

        if 'http' in api_key:
            print("  ⚠️ API Key格式错误 (是验证链接)")
            return False

        url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
        params = {
            "api_key": api_key,
            "frequency": "daily",
            "data[0]": "value",
            "facets[series][]": "RWTC",
            "length": 5
        }
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            records = data.get("response", {}).get("data", [])
            print(f"  ✓ 连接成功，获取到 {len(records)} 条数据")
            return True
        else:
            print(f"  ✗ HTTP {response.status_code}")
            print(f"     响应: {response.text[:200]}")
            return False
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False

def test_coingecko():
    """测试CoinGecko"""
    print("\n测试 CoinGecko (BTC)...")
    try:
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        params = {'vs_currency': 'usd', 'days': '1', 'interval': 'daily'}
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if 'prices' in data:
                print(f"  ✓ 连接成功")
                return True
        else:
            print(f"  ✗ HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False

def test_fred(api_key=None):
    """测试FRED"""
    print("\n测试 FRED API...")
    try:
        if not api_key:
            print("  ⚠️ 未提供API Key，跳过")
            return None

        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            'series_id': 'SP500',
            'api_key': api_key,
            'file_type': 'json',
            'limit': 5
        }
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            obs = data.get('observations', [])
            print(f"  ✓ 连接成功，获取到 {len(obs)} 条数据")
            return True
        else:
            print(f"  ✗ HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False

def main():
    print("=" * 60)
    print("数据源网络连接测试")
    print("=" * 60)

    # 从命令行获取API Key
    eia_key = sys.argv[1] if len(sys.argv) > 1 else None
    fred_key = sys.argv[2] if len(sys.argv) > 2 else None

    results = {
        'CBOE': test_cboE(),
        'Yahoo': test_yahoo(),
        'EIA': test_eia(eia_key),
        'CoinGecko': test_coingecko(),
        'FRED': test_fred(fred_key)
    }

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    for name, result in results.items():
        if result is True:
            print(f"  ✓ {name}: 正常")
        elif result is False:
            print(f"  ✗ {name}: 失败")
        else:
            print(f"  ○ {name}: 未测试")

    print("\n使用方式:")
    print("  python test_network.py [EIA_API_KEY] [FRED_API_KEY]")

if __name__ == '__main__':
    main()
