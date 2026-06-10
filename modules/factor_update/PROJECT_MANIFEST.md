# 项目清单与导航

**版本**: 2.0 Final
**创建日期**: 2026-03-30
**项目大小**: 约10MB

---

## 🎯 开始使用（按顺序）

| 步骤 | 文档 | 说明 |
|------|------|------|
| 1 | `README.md` | 📖 先看这个，了解项目概况 |
| 2 | `QUICKSTART.md` | 🚀 5分钟快速上手 |
| 3 | `config.py` | ⚙️ 配置你的API Key |
| 4 | `run_all_updates.py` | ▶️ 运行更新 |

---

## 📚 核心文档（必看）

| 文档 | 大小 | 什么时候看 |
|------|------|-----------|
| `README.md` | 8KB | 第一次使用 |
| `QUICKSTART.md` | 4KB | 快速上手 |
| `DATA_FRESHNESS_REPORT.md` | 15KB | ⚠️ **重要！了解数据延迟** |
| `FACTOR_COVERAGE_REPORT.md` | 12KB | 查看214个因子详情 |

---

## 🔧 核心脚本（直接使用）

| 脚本 | 大小 | 用途 |
|------|------|------|
| `run_all_updates.py` | 28KB | ⭐ **主脚本** - 一键更新183个因子 |
| `config.py` | 4KB | ⚙️ **配置文件** - 填API Key |
| `test_network.py` | 8KB | 🌐 测试网络连通性 |
| `test_column_alignment.py` | 8KB | ✅ 测试列名与v2文件一致性 |
| `test_data_freshness.py` | 10KB | ⏱️ 测试数据时效性 |

---

## 📦 数据获取器（不需要修改）

位于 `fetchers/` 目录，共9个模块：

| 获取器 | 用途 |
|--------|------|
| `eia_fetcher.py` | EIA能源数据（WTI价格、库存、产量） |
| `cftc_fetcher.py` | CFTC期货持仓数据 |
| `gdel_fetcher.py` | GDELT地缘政治事件数据 |
| `gpr_fetcher.py` | GPR地缘政治风险指数 |
| `tpu_fetcher.py` | TPU贸易政策不确定性 |
| `china_fetcher.py` | akshare中国数据（BDTI、油价） |
| `free_data_fetcher.py` | 免费数据整合模块 |

---

## 📂 数据文件（原始数据）

| 文件 | 大小 | 说明 |
|------|------|------|
| `factors_WTI_cleaned_v2.csv` | 8.5MB | 原始参考数据（214列） |
| `gpr_data/data_gpr_export.xls` | 1MB | GPR地缘政治风险指数 |
| `geopolitical_data/TPU原始数据.xlsx` | 260KB | TPU贸易政策数据 |
| `数据说明.xlsx` | 12KB | 原始数据说明 |

---

## 📊 数据覆盖汇总

### 按自动化程度

| 类别 | 数量 | 占比 |
|------|------|------|
| **可自动更新** | 183 | 85.5% |
| **需手动补充** | 31 | 14.5% |
| **总计** | **214** | **100%** |

### 按延迟分类

| 延迟 | 数量 | 代表因子 | 使用建议 |
|------|------|----------|----------|
| **T+1 日频** | ~53 | VIX, WTI价格, DXY | 日度预测 ✅ |
| **T+3-7 周频** | 8 | 库存, CFTC持仓 | 周度分析 ⚠️ |
| **月度(30天)** | 122 | GPR, TPU, US_out | 前向填充 ⚠️ |
| **无法自动** | 31 | OPEC, 中国数据 | 手动补充 ❌ |

---

## ⚠️ 特别注意事项

### 1. 高延迟风险因子

| 因子 | 延迟 | 风险说明 |
|------|------|----------|
| **US_out** | 1-2月 | 美国原油产量，月频数据 |
| **GPR系列** | 30天 | 地缘政治风险，月内无变化 |
| **TPU系列** | 30天 | 贸易政策不确定性，月内无变化 |
| **CFTC持仓** | 3-5工作日 | 期货持仓，周度发布 |

### 2. 使用前必读

1. **日频模型**: 建议使用53个T+1日频因子
2. **周度模型**: 可使用61个周频因子
3. **月度数据**: 122个月度因子需前向填充 `ffill()`
4. **手动数据**: 31个因子需手动下载补充

---

## 🚀 典型工作流程

```bash
# 1. 配置API Key
vim config.py

# 2. 测试网络
python test_network.py your_eia_key

# 3. 测试列名对齐
python test_column_alignment.py

# 4. 运行更新
python run_all_updates.py

# 5. 查看报告
cat coverage_report_*.txt
```

---

## 📝 输出文件说明

运行后会生成：

| 文件 | 说明 |
|------|------|
| `wti_factors_YYYYMMDD.csv` | 更新的因子数据（主输出） |
| `coverage_report_YYYYMMDD.txt` | 数据覆盖情况报告 |
| `wti_update_YYYYMMDD.log` | 运行日志 |
| `data_freshness_report_YYYYMMDD.txt` | 时效性测试报告 |

---

## 🔍 问题排查指南

| 问题 | 检查文档/脚本 |
|------|--------------|
| 不知道如何开始 | `README.md` → `QUICKSTART.md` |
| API Key申请 | `QUICKSTART.md` 第二步 |
| 网络连接失败 | `test_network.py` |
| 数据延迟疑问 | `DATA_FRESHNESS_REPORT.md` |
| 列名不一致 | `test_column_alignment.py` |
| 因子覆盖疑问 | `FACTOR_COVERAGE_REPORT.md` |

---

## 📞 快速参考

### API Key申请
- **EIA**: https://www.eia.gov/opendata/register.php
- **FRED**: https://fred.stlouisfed.org/docs/api/api_key.html

### 数据源官网
- **EIA**: https://www.eia.gov/
- **CBOE**: https://www.cboe.com/
- **FRED**: https://fred.stlouisfed.org/
- **CFTC**: https://www.cftc.gov/
- **GDELT**: https://www.gdeltproject.org/

---

**建议**: 第一次使用请按顺序阅读 `README.md` → `QUICKSTART.md` → `DATA_FRESHNESS_REPORT.md`
