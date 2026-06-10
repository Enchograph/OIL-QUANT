# WTI原油因子数据自动更新系统

**一句话介绍**: 自动获取WTI原油相关183个因子的最新数据，覆盖214个原始因子中的85.5%。

**适用场景**: 原油量化分析、机器学习预测、策略研究

---

## 🚀 三步快速开始

### 第一步：安装依赖
```bash
pip install pandas numpy requests akshare xlrd openpyxl
```

### 第二步：配置API Key
编辑 `config.py`，填入：
```python
EIA_API_KEY = "your_32_char_eia_api_key"  # 从 https://www.eia.gov/opendata/register.php 申请
FRED_API_KEY = "your_fred_api_key"        # 可选，从 https://fred.stlouisfed.org/docs/api/api_key.html 申请
```

### 第三步：运行更新
```bash
python run_all_updates.py
```

**输出文件**：
- `wti_factors_YYYYMMDD.csv` - 更新的因子数据
- `coverage_report_YYYYMMDD.txt` - 覆盖情况报告

---

## 📁 项目结构

```
Factors_Clean/
├── 📄 核心文件（你用这些）
│   ├── run_all_updates.py          ⭐ 主脚本 - 一键更新所有数据
│   ├── config.py                    ⚙️ 配置文件 - 填你的API Key
│   ├── test_network.py              🌐 测试网络连通性
│   ├── test_column_alignment.py     ✅ 测试列名与原始文件是否一致
│   └── test_data_freshness.py       ⏱️ 测试数据时效性
│
├── 📚 文档（你需要看这些）
│   ├── README.md                    📖 本文件 - 快速开始
│   ├── QUICKSTART.md                🚀 详细使用指南
│   ├── DATA_FRESHNESS_REPORT.md     ⚠️ 重要！数据延迟说明
│   └── FACTOR_COVERAGE_REPORT.md    📊 214个因子详细清单
│
├── 🔧 数据获取器（不需要改）
│   └── fetchers/
│       ├── eia_fetcher.py           # EIA能源数据
│       ├── cftc_fetcher.py          # CFTC期货持仓
│       ├── gdel_fetcher.py          # GDELT地缘政治事件
│       ├── gpr_fetcher.py           # GPR地缘政治风险
│       ├── tpu_fetcher.py           # TPU贸易政策
│       ├── china_fetcher.py         # akshare中国数据
│       └── free_data_fetcher.py     # 免费数据整合
│
├── 📦 数据文件（原始数据）
│   ├── factors_WTI_cleaned_v2.csv   # 原始参考数据（214列）
│   ├── gpr_data/data_gpr_export.xls  # GPR地缘政治风险指数
│   ├── geopolitical_data/TPU原始数据.xlsx # TPU贸易政策数据
│   └── 数据说明.xlsx                # 数据说明文档
│
└── requirements.txt                 # Python依赖列表
```

---

## 📊 数据覆盖情况

### 总体统计

| 指标 | 数值 |
|------|------|
| **原始因子总数** | 214 |
| **可自动更新** | **183 (85.5%)** |
| **需手动补充** | 31 (14.5%) |

### 按延迟分类

| 延迟 | 数量 | 代表因子 | 使用场景 |
|------|------|----------|----------|
| 🟢 **T+1 日频** | ~53 | VIX, WTI价格, 美元指数 | 日度预测 |
| 🟡 **T+3-7 周频** | 8 | 原油库存, CFTC持仓 | 周度分析 |
| 🟡 **月度(30天)** | 122 | GPR, TPU, 美国产量 | 月度策略 |
| ❌ **无法自动** | 31 | OPEC, 中国数据 | 手动补充 |

**关键提示**：
- ✅ **53个因子**可日度实时更新（适合日频模型）
- ⚠️ **122个因子**是月度数据（月内数值不变，需前向填充）
- ❌ **31个因子**需手动补充（OPEC月报、中国海关等）

---

## ⚠️ 重要提示

### 1. 数据延迟风险

| 数据源 | 延迟 | 说明 |
|--------|------|------|
| **CBOE (VIX/OVX)** | T+1 | 收盘后次日发布 ✅ |
| **EIA (日频价格)** | 1-2天 | 适合日频分析 ✅ |
| **EIA (周频库存)** | 2-3天 | 每周三发布上周数据 ⚠️ |
| **CFTC (期货持仓)** | 3-5工作日 | 周五收盘，下周二发布 ⚠️ |
| **GPR/TPU** | 30天 | 月度数据，月内不变 ⚠️ |
| **US_out (美国产量)** | 1-2月 | 月频数据，延迟严重 ❌ |

**详细时效性报告**: 见 `DATA_FRESHNESS_REPORT.md`

### 2. 使用前必看

1. **日频预测模型**：建议使用53个T+1日频因子
2. **周度分析**：可使用61个周频因子（含库存、CFTC）
3. **月度数据（GPR/TPU/US_out）**：月内数值不变，使用前向填充 `ffill()`
4. **OPEC/中国/各国数据**：需手动下载补充

---

## 💡 使用示例

### 示例1：更新最近90天数据
```bash
python run_all_updates.py
```

### 示例2：指定日期范围
```bash
python run_all_updates.py --start-date 2026-01-01 --end-date 2026-03-30
```

### 示例3：先测试再运行
```bash
# 测试网络连通性
python test_network.py your_eia_api_key

# 测试列名对齐
python test_column_alignment.py

# 测试数据时效性
python test_data_freshness.py

# 运行更新
python run_all_updates.py
```

### 示例4：Python代码中使用
```python
import pandas as pd

# 读取更新后的数据
df = pd.read_csv('wti_factors_20260330.csv', parse_dates=['Date'])
df.set_index('Date', inplace=True)

# 查看可用列
print(f"总列数: {len(df.columns)}")
print(f"有数据的列: {df.notna().any().sum()}")

# 筛选日频因子（延迟<3天）
daily_factors = ['VIX_Price', 'OVX_Price', 'WTI_Return_1d', 'DXY_Price', 'SP500_Index']
df_daily = df[daily_factors].dropna()

# 月度数据前向填充
monthly_factors = ['GPR', 'TPUD_index']
df[monthly_factors] = df[monthly_factors].ffill()
```

---

## ❓ 常见问题

### Q1: 脚本运行报错 "No module named 'pandas'"?
```bash
pip install pandas numpy requests akshare xlrd openpyxl
```

### Q2: EIA API Key怎么申请？
1. 访问 https://www.eia.gov/opendata/register.php
2. 填写邮箱注册
3. 查收邮件获取32位API Key
4. 填入 `config.py`

### Q3: 为什么有些因子获取失败？
可能原因：
- 网络限制（Yahoo/CoinGecko需要代理）
- API Key未配置或格式错误
- 数据源临时不可用

**解决方案**: 先运行 `python test_network.py your_eia_key` 测试连通性

### Q4: 数据延迟多久？
- **日频因子**（VIX, WTI价格等）：延迟1-2天
- **周频因子**（库存, CFTC持仓）：延迟2-7天
- **月度因子**（GPR, TPU）：月内无变化，延迟30天

**详细说明**: 见 `DATA_FRESHNESS_REPORT.md`

### Q5: 缺失的31个因子怎么补充？
需要手动下载：
- **OPEC数据**: OPEC官网月度石油市场报告 (MOMR)
- **中国数据**: 海关总署、国家统计局
- **各国消费**: BP世界能源统计年鉴

### Q6: 数据质量如何保证？
1. 运行 `python test_column_alignment.py` 验证列名一致性
2. 对比自动化数据与原始v2数据
3. 查看 `coverage_report_YYYYMMDD.txt` 了解覆盖情况

---

## 📖 相关文档

| 文档 | 说明 |
|------|------|
| `QUICKSTART.md` | 详细使用指南 |
| `DATA_FRESHNESS_REPORT.md` | ⚠️ 数据时效性与延迟详细说明 |
| `FACTOR_COVERAGE_REPORT.md` | 214个因子完整清单 |
| `PROJECT_MANIFEST.md` | 项目文件清单 |

---

## 📞 技术支持

如有问题：
1. 先查看 `QUICKSTART.md` 和 `DATA_FRESHNESS_REPORT.md`
2. 运行测试脚本排查问题
3. 检查API Key配置

---

**版本**: 2.0 Final
**更新日期**: 2026-03-30
**覆盖因子**: 183/214 (85.5%)

**核心结论**: 53个因子可日度实时更新，122个月度因子需前向填充，31个因子需手动补充。
