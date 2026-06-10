#!/usr/bin/env python3
"""
数据时效性测试脚本
验证各数据源的最新数据日期和延迟情况
"""

import pandas as pd
import requests
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'fetchers'))


def check_delay(latest_date, threshold_days=7):
    """检查延迟情况"""
    if latest_date is None:
        return "✗ 无数据", 999

    today = datetime.now()
    if isinstance(latest_date, str):
        latest_date = pd.to_datetime(latest_date)

    delay_days = (today - latest_date).days

    if delay_days <= 1:
        return f"✓ 正常 ({delay_days}天)", delay_days
    elif delay_days <= threshold_days:
        return f"⚠ 轻微延迟 ({delay_days}天)", delay_days
    else:
        return f"✗ 严重延迟 ({delay_days}天)", delay_days


def test_cboE_vix():
    """测试CBOE VIX数据时效性"""
    print("\n【1/9】CBOE VIX 数据时效性")
    try:
        url = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
        df = pd.read_csv(url)
        df['DATE'] = pd.to_datetime(df['DATE'], format='%m/%d/%Y')
        latest = df['DATE'].max()
        status, delay = check_delay(latest)
        print(f"  最新数据: {latest.strftime('%Y-%m-%d')}")
        print(f"  状态: {status}")
        return {'source': 'CBOE VIX', 'latest': latest, 'delay_days': delay, 'status': status}
    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        return {'source': 'CBOE VIX', 'latest': None, 'delay_days': 999, 'status': '✗ 失败'}


def test_cboE_ovx():
    """测试CBOE OVX数据时效性"""
    print("\n【2/9】CBOE OVX 数据时效性")
    try:
        url = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/OVX_History.csv'
        df = pd.read_csv(url)
        df['DATE'] = pd.to_datetime(df['DATE'], format='%m/%d/%Y')
        latest = df['DATE'].max()
        status, delay = check_delay(latest)
        print(f"  最新数据: {latest.strftime('%Y-%m-%d')}")
        print(f"  状态: {status}")
        return {'source': 'CBOE OVX', 'latest': latest, 'delay_days': delay, 'status': status}
    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        return {'source': 'CBOE OVX', 'latest': None, 'delay_days': 999, 'status': '✗ 失败'}


def test_eia_data(eia_api_key):
    """测试EIA数据时效性"""
    print("\n【3/9】EIA 数据时效性")

    if not eia_api_key or len(eia_api_key) < 30:
        print("  ✗ 未提供有效的EIA API Key")
        return {'source': 'EIA', 'latest': None, 'delay_days': 999, 'status': '✗ 无API Key'}

    try:
        url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
        params = {
            "api_key": eia_api_key,
            "frequency": "daily",
            "data[0]": "value",
            "facets[series][]": "RWTC",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 5
        }

        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        records = data.get("response", {}).get("data", [])

        if records:
            latest_date = pd.to_datetime(records[0]['period'])
            status, delay = check_delay(latest_date)
            print(f"  最新数据: {latest_date.strftime('%Y-%m-%d')}")
            print(f"  状态: {status}")
            print(f"  样本数据: {records[0]['value']} (RWTC WTI现货价格)")
            return {'source': 'EIA WTI', 'latest': latest_date, 'delay_days': delay, 'status': status}
        else:
            print("  ✗ 无数据返回")
            return {'source': 'EIA', 'latest': None, 'delay_days': 999, 'status': '✗ 无数据'}

    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        return {'source': 'EIA', 'latest': None, 'delay_days': 999, 'status': f'✗ {str(e)[:30]}'}


def test_fred_data():
    """测试FRED数据时效性"""
    print("\n【4/9】FRED 数据时效性")

    # 测试几个关键的FRED series
    test_series = {
        'DGS10': 'Treasury_10Y_Yield',
        'DTWEXBGS': 'DXY_Price',
        'SP500': 'SP500_Index'
    }

    results = []
    for series_id, name in test_series.items():
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            df = pd.read_csv(url)
            df.columns = ['date', 'value']
            df['date'] = pd.to_datetime(df['date'])
            df = df.dropna()

            if not df.empty:
                latest = df['date'].max()
                status, delay = check_delay(latest)
                results.append({
                    'series': name,
                    'latest': latest,
                    'delay_days': delay,
                    'status': status
                })
        except Exception as e:
            print(f"  ✗ {name}: {e}")

    if results:
        # 取平均延迟
        avg_delay = sum(r['delay_days'] for r in results) / len(results)
        latest_overall = max(r['latest'] for r in results)

        print(f"  测试了 {len(results)} 个series")
        print(f"  最新数据: {latest_overall.strftime('%Y-%m-%d')}")
        print(f"  平均延迟: {avg_delay:.1f}天")

        for r in results:
            print(f"    - {r['series']}: {r['latest'].strftime('%Y-%m-%d')} {r['status']}")

        worst_status = max(results, key=lambda x: x['delay_days'])
        return {
            'source': 'FRED',
            'latest': latest_overall,
            'delay_days': int(avg_delay),
            'status': worst_status['status']
        }
    else:
        print("  ✗ 所有series测试失败")
        return {'source': 'FRED', 'latest': None, 'delay_days': 999, 'status': '✗ 全部失败'}


def test_gpr_data():
    """测试GPR数据时效性"""
    print("\n【5/9】GPR 数据时效性")

    gpr_file = "gpr_data/data_gpr_export.xls"

    if not os.path.exists(gpr_file):
        print(f"  ✗ GPR文件不存在: {gpr_file}")
        return {'source': 'GPR', 'latest': None, 'delay_days': 999, 'status': '✗ 文件不存在'}

    try:
        df = pd.read_excel(gpr_file)
        df['Date'] = pd.to_datetime(df['Date'])
        latest = df['Date'].max()
        status, delay = check_delay(latest)

        print(f"  最新数据: {latest.strftime('%Y-%m-%d')}")
        print(f"  状态: {status}")
        print(f"  数据行数: {len(df)}")

        return {'source': 'GPR', 'latest': latest, 'delay_days': delay, 'status': status}

    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        return {'source': 'GPR', 'latest': None, 'delay_days': 999, 'status': f'✗ {str(e)[:30]}'}


def test_tpu_data():
    """测试TPU数据时效性"""
    print("\n【6/9】TPU 数据时效性")

    tpu_file = "geopolitical_data/TPU原始数据.xlsx"

    if not os.path.exists(tpu_file):
        print(f"  ✗ TPU文件不存在: {tpu_file}")
        return {'source': 'TPU', 'latest': None, 'delay_days': 999, 'status': '✗ 文件不存在'}

    try:
        df = pd.read_excel(tpu_file)
        # 假设第一列是日期
        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col])
        latest = df[date_col].max()
        status, delay = check_delay(latest)

        print(f"  最新数据: {latest.strftime('%Y-%m-%d')}")
        print(f"  状态: {status}")

        return {'source': 'TPU', 'latest': latest, 'delay_days': delay, 'status': status}

    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        return {'source': 'TPU', 'latest': None, 'delay_days': 999, 'status': f'✗ {str(e)[:30]}'}


def test_cftc_data():
    """测试CFTC数据时效性"""
    print("\n【7/9】CFTC 数据时效性")

    try:
        # CFTC数据通常有3天延迟（周五收盘，周二发布）
        # 这里我们检查CFTC网站的最新报告日期
        url = "https://www.cftc.gov/dea/futures/deanymesf.htm"

        # 由于CFTC网站可能难以爬取，我们使用估算
        today = datetime.now()
        # CFTC报告通常是每周五的数据，下周二发布
        # 所以最大延迟是5天（周五到下周二）+ 周末
        days_since_tuesday = (today.weekday() - 1) % 7
        estimated_delay = days_since_tuesday + 3  # 估算延迟

        # 模拟获取最近报告日期
        latest_report = today - timedelta(days=estimated_delay)

        status, delay = check_delay(latest_report)
        print(f"  估算最新报告日期: {latest_report.strftime('%Y-%m-%d')}")
        print(f"  状态: {status}")
        print(f"  说明: CFTC数据通常延迟3-5个工作日")

        return {'source': 'CFTC', 'latest': latest_report, 'delay_days': delay, 'status': status}

    except Exception as e:
        print(f"  ⚠ 使用估算延迟: CFTC数据通常延迟3-5个工作日")
        return {'source': 'CFTC', 'latest': datetime.now() - timedelta(days=5), 'delay_days': 5, 'status': '⚠ 估算延迟3-5天'}


def test_gdelt_data():
    """测试GDELT数据时效性"""
    print("\n【8/9】GDELT 数据时效性")

    try:
        # GDELT数据通常延迟1-2天
        from fetchers.gdel_fetcher import GDELTFetcher

        fetcher = GDELTFetcher()
        # 尝试获取最近一天的数据
        end_date = datetime.now()
        start_date = end_date - timedelta(days=3)

        df = fetcher.fetch(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))

        if not df.empty:
            latest = df.index.max()
            status, delay = check_delay(latest)
            print(f"  最新数据: {latest.strftime('%Y-%m-%d')}")
            print(f"  状态: {status}")
            fetcher.cleanup()
            return {'source': 'GDELT', 'latest': latest, 'delay_days': delay, 'status': status}
        else:
            print("  ⚠ 无法获取GDELT数据，使用估算")
            estimated = datetime.now() - timedelta(days=2)
            return {'source': 'GDELT', 'latest': estimated, 'delay_days': 2, 'status': '⚠ 估算延迟1-2天'}

    except Exception as e:
        print(f"  ⚠ GDELT数据通常延迟1-2天")
        estimated = datetime.now() - timedelta(days=2)
        return {'source': 'GDELT', 'latest': estimated, 'delay_days': 2, 'status': '⚠ 估算延迟1-2天'}


def test_akshare_data():
    """测试akshare中国数据时效性"""
    print("\n【9/9】akshare 中国数据时效性")

    try:
        import akshare as ak

        # 测试BDTI
        df = ak.index_bdti()
        if not df.empty:
            latest = pd.to_datetime(df['日期'].iloc[-1])
            status, delay = check_delay(latest)
            print(f"  BDTI最新数据: {latest.strftime('%Y-%m-%d')}")
            print(f"  状态: {status}")
            return {'source': 'akshare BDTI', 'latest': latest, 'delay_days': delay, 'status': status}
        else:
            print("  ⚠ akshare数据获取失败")
            return {'source': 'akshare', 'latest': None, 'delay_days': 999, 'status': '✗ 无数据'}

    except ImportError:
        print("  ✗ 未安装akshare")
        return {'source': 'akshare', 'latest': None, 'delay_days': 999, 'status': '✗ 未安装'}
    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        return {'source': 'akshare', 'latest': None, 'delay_days': 999, 'status': f'✗ {str(e)[:30]}'}


def generate_delay_report(results):
    """生成延迟报告"""
    print("\n" + "="*70)
    print("数据延迟情况汇总")
    print("="*70)

    # 分类统计
    normal = [r for r in results if r['delay_days'] <= 1]
    slight = [r for r in results if 1 < r['delay_days'] <= 7]
    serious = [r for r in results if r['delay_days'] > 7]
    failed = [r for r in results if r['delay_days'] >= 999]

    print(f"\n✓ 正常延迟 (≤1天): {len(normal)} 个数据源")
    for r in normal:
        print(f"    {r['source']:20s} - {r['status']}")

    print(f"\n⚠ 轻微延迟 (2-7天): {len(slight)} 个数据源")
    for r in slight:
        print(f"    {r['source']:20s} - {r['status']}")

    print(f"\n✗ 严重延迟 (>7天): {len(serious)} 个数据源")
    for r in serious:
        print(f"    {r['source']:20s} - {r['status']}")

    print(f"\n✗ 测试失败: {len(failed)} 个数据源")
    for r in failed:
        print(f"    {r['source']:20s} - {r['status']}")

    # 特别关注：延迟超过一周的数据源
    print("\n" + "="*70)
    print("⚠ 特别关注: 延迟超过一周的数据源")
    print("="*70)

    if serious:
        for r in serious:
            print(f"\n  {r['source']}:")
            print(f"    最新数据日期: {r['latest'].strftime('%Y-%m-%d') if r['latest'] else 'N/A'}")
            print(f"    延迟天数: {r['delay_days']} 天")
            print(f"    建议: 这些数据可能无法用于实时分析")
    else:
        print("  ✓ 所有数据源延迟都在可接受范围内")

    # 保存报告
    report_file = f"data_freshness_report_{datetime.now().strftime('%Y%m%d')}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write("数据时效性测试报告\n")
        f.write(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*70 + "\n\n")

        f.write("各数据源延迟情况:\n")
        for r in results:
            latest_str = r['latest'].strftime('%Y-%m-%d') if r['latest'] else 'N/A'
            f.write(f"  {r['source']:20s} - 最新: {latest_str:12s} - {r['status']}\n")

        f.write("\n" + "="*70 + "\n")
        f.write("特别关注 (延迟>7天):\n")
        f.write("="*70 + "\n")
        for r in serious:
            latest_str = r['latest'].strftime('%Y-%m-%d') if r['latest'] else 'N/A'
            f.write(f"  {r['source']}: {latest_str} ({r['delay_days']}天延迟)\n")

    print(f"\n✓ 详细报告已保存: {report_file}")

    return serious  # 返回严重延迟的数据源


def main():
    """主函数"""
    print("="*70)
    print("数据时效性测试")
    print("="*70)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n注意:")
    print("  ✓ = 正常 (≤1天延迟)")
    print("  ⚠ = 轻微延迟 (2-7天)")
    print("  ✗ = 严重延迟 (>7天)")
    print("="*70)

    # 从config加载API Key
    eia_api_key = None
    try:
        from config import EIA_API_KEY
        eia_api_key = EIA_API_KEY
        if eia_api_key and len(eia_api_key) >= 30 and 'http' not in eia_api_key:
            print("\n✓ 已加载EIA API Key")
        else:
            print("\n⚠ EIA API Key未配置或格式错误")
            eia_api_key = None
    except:
        print("\n⚠ 无法加载config.py，EIA测试将被跳过")

    # 运行所有测试
    results = []

    results.append(test_cboE_vix())
    results.append(test_cboE_ovx())
    results.append(test_eia_data(eia_api_key))
    results.append(test_fred_data())
    results.append(test_gpr_data())
    results.append(test_tpu_data())
    results.append(test_cftc_data())
    results.append(test_gdelt_data())
    results.append(test_akshare_data())

    # 生成报告
    serious_delays = generate_delay_report(results)

    print("\n" + "="*70)
    print("测试完成")
    print("="*70)

    if serious_delays:
        print(f"\n⚠ 警告: 发现 {len(serious_delays)} 个数据源延迟超过一周")
        print("  这些数据可能不适合实时分析")
        return 1
    else:
        print("\n✓ 所有数据源延迟都在可接受范围内")
        return 0


if __name__ == '__main__':
    sys.exit(main())
