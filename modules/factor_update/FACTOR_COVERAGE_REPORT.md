# WTI因子覆盖情况详细报告

**报告日期**: 2026-03-30
**原始数据**: factors_WTI_cleaned_v2.csv (214列)

---

## 执行摘要

| 指标 | 数值 |
|------|------|
| **总因子数** | 214 |
| **可自动化更新** | 183 (85.5%) |
| **需手动/付费补充** | 31 (14.5%) |
| **预计数据覆盖率** | 85-90% |

---

## ⚠️ 重要提示：数据时效性

**各数据源延迟情况**:

| 数据源 | 延迟 | 适用场景 |
|--------|------|----------|
| 🟢 CBOE (VIX/OVX) | T+1 | 日频预测 ✅ |
| 🟢 EIA (日频价格) | 1-2天 | 日频预测 ✅ |
| 🟡 EIA (周频库存) | 2-3天 | 周度分析 ⚠️ |
| 🟡 CFTC (期货持仓) | 3-5工作日 | 周度分析 ⚠️ |
| 🟡 GPR/TPU | 30天 | 月度策略 ⚠️ (月内无变化) |
| 🔴 OPEC/中国/各国 | 无法自动化 | 需手动补充 ❌ |

**详细时效性报告**: 见 `DATA_FRESHNESS_REPORT.md`

---

---

## 详细覆盖情况

### ✅ 完全可自动化 (183列)

#### 1. WTI价格与技术指标 (22列)

| 列名 | 获取方式 | 优先级 |
|------|----------|--------|
| Price | EIA API | P0 |
| WTI_Open | EIA计算 | P0 |
| WTI_High | EIA计算 | P0 |
| WTI_Low | EIA计算 | P0 |
| WTI_Close | EIA计算 | P0 |
| WTI_Return_1d | 计算 | P1 |
| WTI_Return_5d | 计算 | P1 |
| WTI_Return_20d | 计算 | P1 |
| WTI_Return_60d | 计算 | P1 |
| WTI_Volatility_20d | 计算 | P1 |
| WTI_Volatility_60d | 计算 | P1 |
| WTI_MA_5 | 计算 | P1 |
| WTI_MA_20 | 计算 | P1 |
| WTI_MA_60 | 计算 | P1 |
| WTI_High_20d | 计算 | P1 |
| WTI_Low_20d | 计算 | P1 |
| WTI_Breakout_High | 计算 | P2 |
| WTI_Breakdown_Low | 计算 | P2 |
| WTI_Golden_Cross | 计算 | P2 |
| WTI_Death_Cross | 计算 | P2 |
| WTI_Month | 计算 | P0 |
| WTI_Weekday | 计算 | P0 |

**数据源**: EIA Series RWTC (Cushing WTI Spot Price)
**延迟**: 🟢 1-2天 (日频)

---

#### 2. 库存与供需数据 (8列)

| 列名 | 数据源 | 状态 |
|------|--------|------|
| BDTI | akshare | ✅ |
| C_stock | EIA API | ✅ |
| stock | EIA API | ✅ |
| Cushing_stock | EIA API | ✅ |
| US_OR | EIA API | ✅ |
| China_wholeprice | akshare | ✅ |
| China_retailprice | akshare | ✅ |
| US_stock_strategy | EIA API | ✅ |

**延迟标注**:
- 🟡 **C_stock, stock, Cushing_stock, US_stock_strategy**: 周频数据，延迟2-3天 (每周三发布上周数据)
- 🟢 **US_OR**: 周频数据，延迟2-3天
- 🟢 **BDTI, China_wholeprice, China_retailprice**: 日频，延迟1-2天

---

#### 3. CBOE波动率数据 (2列)

| 列名 | 数据源 | 状态 |
|------|--------|------|
| OVX_Price | CBOE CSV | ✅ |
| VIX_Price | CBOE CSV | ✅ |

**数据源**:
- https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
- https://cdn.cboe.com/api/global/us_indices/daily_prices/OVX_History.csv

**延迟**: 🟢 T+1 (收盘后次日发布)

---

#### 4. 美国产量数据 (1列)

| 列名 | 数据源 | 状态 |
|------|--------|------|
| US_out | EIA API | ✅ |

**⚠️ 重要提示**: `US_out` (美国原油产量) 是**月频数据**，延迟1-2个月。月内数值不变化，使用前向填充。

---

#### 5. FRED宏观经济指标 (17列)

| 列名 | Series ID | 状态 |
|------|-----------|------|
| Treasury_10Y_Yield | DGS10 | ✅ |
| Real_Interest_Rate_10Y | REAINTRATREARAT10Y | ✅ |
| Breakeven_Inflation_10Y | T10YIE | ✅ |
| High_Yield_Spread | BAMLH0A0HYM2 | ✅ |
| Financial_Stress_Index | STLFSI4 | ✅ |
| M2_Money_Supply | M2SL | ✅ |
| Industrial_Production | INDPRO | ✅ |
| Unemployment_Rate | UNRATE | ✅ |
| Consumer_Sentiment | UMCSENT | ✅ |
| DXY_Price | DTWEXBGS | ✅ |
| WTI_Crude_Oil | DCOILWTICO | ✅ |
| US_Dollar_Index | DEXUSEU | ✅ |
| SP500_Index | SP500 | ✅ |
| VIX_Index | VIXCLS | ✅ |
| AUD_USD_Rate | DEXCHUS | ✅ |
| GOLD_Price | GOLDAMGBD228NLBM | ✅ |
| Copper_Futures (需确认) | 待添加 | ⚠️ |
| Natural_Gas_Futures (需确认) | 待添加 | ⚠️ |

**延迟标注**:
- 🟢 **日频指标** (Treasury_10Y, DXY, SP500, VIX, GOLD_Price): 延迟1天
- 🟡 **月频指标** (Unemployment, Industrial_Production, M2, Consumer_Sentiment): 延迟15-30天

**数据源**: https://fred.stlouisfed.org/

---

#### 6. CFTC期货持仓数据 (3列)

| 列名 | 说明 | 状态 |
|------|------|------|
| WTI_Fut_Vol | 期货成交量 | ✅ |
| WTI_MM_Net | 做市商净持仓 | ✅ |
| WTI_Basis | 基差 | ✅ (计算) |

**延迟**: 🟡 **3-5工作日** - CFTC周五收盘后统计，下周二发布报告

**说明**: CFTC数据适合周度分析，不适合日度预测。使用时注意避免前视偏差。

**数据源**: https://www.cftc.gov/

---

#### 7. GDELT地缘政治事件 (12列)

| 列名 | 说明 | 状态 |
|------|------|------|
| NUMBER_ARTICLES | 文章数量 | ✅ |
| TPUD_ARTICLES | TPU文章数 | ✅ |
| TPUD_index | TPU指数 | ✅ |
| TPUD_index_MA7 | 7日移动平均 | ✅ |
| TPUD_index_MA30 | 30日移动平均 | ✅ |
| total_events | 总事件数 | ✅ |
| conflict_count | 冲突事件数 | ✅ |
| conflict_intensity_mean | 冲突强度均值 | ✅ |
| conflict_intensity_sum | 冲突强度总和 | ✅ |
| mentions_mean | 提及均值 | ✅ |
| mentions_sum | 提及总和 | ✅ |
| tone_mean | 情绪均值 | ✅ |

**延迟**: 🟢 **1-2天** - 每日更新，延迟1-2天

**数据源**: https://www.gdeltproject.org/

---

#### 8. TPU贸易政策不确定性 (5列)

| 列名 | 状态 |
|------|------|
| TPUD_index | ✅ |
| TPUD_index_MA7 | ✅ |
| TPUD_index_MA30 | ✅ |
| NUMBER_ARTICLES | ✅ |
| TPUD_ARTICLES | ✅ |

**⚠️ 重要提示**: TPU数据是**月度数据**，延迟约30天。月内数值不变，使用前向填充。

**延迟**: 🟡 **30天 (月度)**

**数据源**: https://www.policyuncertainty.com/

---

#### 9. GPR地缘政治风险 (111列)

包含:
- GPR, GPRT, GPRA, GPRH, GPRHT, GPRHA, SHARE_GPR, N10, SHARE_GPRH, N3H (10列)
- GPRH_NOEW, GPR_NOEW, GPRH_AND, GPR_AND, GPRH_BASIC, GPR_BASIC (6列)
- SHAREH_CAT_1~8 (8列)
- GPRC_国家代码 (44列: ARG, AUS, BEL, BRA, CAN等)
- GPRHC_国家代码 (44列)

**⚠️ 重要提示**: GPR数据是**月度数据**，延迟约30天。月内数值不变，使用前向填充。

**延迟**: 🟡 **30天 (月度)**

**数据源**: Caldara & Iacoviello, "Measuring Geopolitical Risk"

---

#### 10. 其他可用因子 (2列)

| 列名 | 数据源 | 状态 |
|------|--------|------|
| XLE_Price | 新浪财经 | ✅ |
| Emerging_Markets_ETF | 新浪财经 | ✅ |

**延迟**: 🟢 **T+0 实时** - 交易时间实时更新

---

### ⚠️ 部分可更新 (6列)

| 列名 | 问题 | 建议 |
|------|------|------|
| **Gold_Futures** | Yahoo限流 | 可用FRED GOLD或新浪黄金替代 |
| **BTC_Price** | CoinGecko国内访问受限 | 需代理或改用新浪财经 |
| **WTI_Fut_Price** | 期货数据需代理 | 可用现货近似 |
| **CRB_Price** | 官方需付费 | 可用DBC ETF替代 |
| **original_month** | 需确认计算方法 | 可能为时间特征 |
| **WTI_Crude_Oil** | 可能重复 | 检查与Price列 |

---

### ❌ 无法自动更新 (25列)

#### OPEC数据 (4列)

| 列名 | 原因 | 建议 |
|------|------|------|
| OPEC_out | 无免费API | 手动下载MOMR报告 |
| OPEC_supply | 需IEA订阅 | 付费或OPEC月报 |
| OPEC_pro | 需IEA订阅 | 付费或OPEC月报 |
| OPEC相关产量 | 同上 | 同上 |

#### 中国数据 (5列)

| 列名 | 原因 | 建议 |
|------|------|------|
| China_final_import | 海关总署无免费API | 手动下载 |
| China_final_export | 同上 | 手动下载 |
| China_final_con | 发改委无免费API | 手动下载 |
| China_con | 需BP年鉴 | 手动下载 |
| China_out | 国家统计局 | 手动下载 |

#### 各国消费数据 (9列)

| 列名 | 原因 | 建议 |
|------|------|------|
| Total_con | 需BP年鉴 | 手动下载 |
| US_con | 需BP年鉴 | 手动下载 |
| Germany_con | 需BP年鉴 | 手动下载 |
| Japan_con | 需BP年鉴 | 手动下载 |
| India_con | 需BP年鉴 | 手动下载 |
| Euro_con | 需BP年鉴 | 手动下载 |
| Russia_con | 需BP年鉴 | 手动下载 |
| OECD_con | 需IEA数据 | 付费或手动 |

#### 各国产量数据 (15列)

| 列名 | 原因 | 建议 |
|------|------|------|
| EU_out, Iran_out, Iraq_out, Norway_out, OECD_out等 | 无免费API | OPEC月报/EIA国际数据 |

---

## 数据获取优先级

### P0 - 核心数据 (必须)

- WTI价格 (Price)
- WTI技术指标 (MA, Returns等)
- 库存数据 (C_stock, Cushing_stock等)
- VIX, OVX
- 宏观指标 (Treasury, DXY等)

### P1 - 重要数据 (强烈建议)

- CFTC期货持仓
- BDTI指数
- 中国油价
- 美国产量

### P2 - 补充数据 (按需)

- GDELT事件数据
- TPU指数
- GPR国家细分

### P3 - 可选数据

- 加密货币
- 黄金期货 (替代可用)
- CRB指数 (替代可用)

---

## 数据源汇总

| 数据源 | 覆盖列数 | 费用 | 稳定性 |
|--------|----------|------|--------|
| **EIA API** | ~25 | 免费 | 高 |
| **FRED API** | ~20 | 免费 | 高 |
| **CBOE CSV** | 2 | 免费 | 高 |
| **CFTC** | 3 | 免费 | 中 |
| **GDELT** | 12 | 免费 | 中 |
| **GPR Excel** | 111 | 免费 | 高 |
| **TPU CSV** | 5 | 免费 | 高 |
| **akshare** | ~5 | 免费 | 中 |
| **新浪财经** | 2 | 免费 | 中 |

---

## 运行脚本

```bash
# 基本运行
python run_all_updates.py

# 指定日期范围
python run_all_updates.py --start-date 2026-01-01 --end-date 2026-03-30

# 指定输出目录
python run_all_updates.py --output-dir ./data
```

---

## 输出文件

1. **wti_factors_YYYYMMDD.csv** - 更新的因子数据
2. **coverage_report_YYYYMMDD.txt** - 覆盖情况报告
3. **wti_update_YYYYMMDD.log** - 运行日志

---

## 下一步建议

### 短期 (本周)

1. 配置API Key (EIA, FRED)
2. 运行脚本测试数据获取
3. 验证数据质量

### 中期 (本月)

4. 补充OPEC月报数据 (手动)
5. 配置代理获取Yahoo数据
6. 建立定时更新任务

### 长期 (按需)

7. 评估付费数据源 (Wind/iFind)
8. 补充中国海关数据
9. 补充BP年鉴数据

---

**结论**: 使用免费数据源可覆盖85.5%的因子 (183/214)，足以支撑大部分分析和建模需求。
