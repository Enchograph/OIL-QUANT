# 免费数据源申请与使用指南

**目标**: 用免费数据源覆盖8个缺失因子

---

## 免费数据覆盖情况

| 因子 | 数据源 | 费用 | 状态 |
|------|--------|------|------|
| **VIX_Price** | CBOE官方CSV | 免费 | ✅ 可用 |
| **OVX_Price** | CBOE官方CSV | 免费 | ✅ 可用 |
| **WTI_Crude_Oil** | EIA API | 免费 | ✅ 可用 |
| **WTI_Fut_Price** | EIA API / Yahoo | 免费 | ✅ 可用 |
| **Gold_Futures** | Yahoo Finance | 免费 | ⚠️ 有限流 |
| **SPX_Price** | Yahoo Finance / FRED | 免费 | ✅ 可用 |
| **BTC_Price** | CoinGecko API | 免费 | ✅ 可用 |
| **WTI_Basis** | 计算得出 | 免费 | ✅ 可用 |
| **CRB_Price** | DBC ETF替代 | 免费 | ⚠️ 替代指标 |

---

## 必须申请的API Key

### 1. EIA API Key (强烈推荐)

**用途**: WTI现货价格、美国原油库存、产量数据

**申请步骤**:
1. 访问: https://www.eia.gov/opendata/register.php
2. 填写邮箱注册
3. 在邮箱中查收API Key
4. 复制Key到 `config.py` 或 `update_free_data.py`

**使用代码**:
```python
EIA_API_KEY = "your_eia_api_key_here"
```

---

### 2. FRED API Key (推荐)

**用途**: 美元指数、宏观经济数据、标普500

**申请步骤**:
1. 访问: https://fred.stlouisfed.org/docs/api/api_key.html
2. 点击 "Request API Key"
3. 填写表单提交
4. 邮箱接收API Key

**使用代码**:
```python
FRED_API_KEY = "your_fred_api_key_here"
```

---

### 3. Alpha Vantage API Key (可选)

**用途**: VIX、黄金期货等 (Yahoo的备用方案)

**限制**: 免费版500次/天，5次/分钟

**申请步骤**:
1. 访问: https://www.alphavantage.co/support/#api-key
2. 填写邮箱注册
3. 获取免费API Key

**使用代码**:
```python
ALPHA_VANTAGE_KEY = "your_alpha_vantage_key_here"
```

---

## 使用方法

### 快速开始

1. **配置API Key**

编辑 `update_free_data.py`:
```python
EIA_API_KEY = "your_actual_eia_key"  # 填入真实Key
FRED_API_KEY = "your_actual_fred_key"  # 填入真实Key
```

2. **运行脚本**

```bash
cd /home/chrisue0319/比赛/Factors
python update_free_data.py
```

3. **查看输出**

数据将保存到 `wti_factors_free_data_YYYYMMDD.csv`

---

## 数据源详情

### CBOE (芝加哥期权交易所)

**数据类型**: VIX, OVX

**API URL**:
- VIX: https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
- OVX: https://cdn.cboe.com/api/global/us_indices/daily_prices/OVX_History.csv

**频率**: 日频

**延迟**: T+1

**限制**: 无限制

---

### EIA (美国能源信息署)

**数据类型**: WTI价格、库存、产量

**API文档**: https://www.eia.gov/opendata/

**常用Series**:
| Series ID | 说明 |
|-----------|------|
| RWTC | WTI现货价格 |
| PET_WCRFP_W41_NUS_D | WTI期货价格 |
| PET_WCRSTK1_WNU_NUS_D | 商业原油库存 |
| PET_WCRSTK11_WNU_NUS_D | 库欣库存 |

**频率**: 日频/周频/月频

**延迟**: 1-2天

**限制**: 1000次/小时

---

### Yahoo Finance

**数据类型**: 黄金期货、标普500等

**限制**:
- 未认证: 100次/小时
- 频繁请求会触发限流

**建议**: 添加延时，缓存数据

---

### CoinGecko

**数据类型**: 比特币等加密货币

**限制**: 10-30次/分钟 (免费版)

**建议**: 添加延时，避免频繁请求

---

## 故障排除

### Yahoo Finance 403错误

**原因**: IP被限流

**解决方案**:
1. 减少请求频率
2. 使用代理
3. 切换到Alpha Vantage

### EIA 403错误

**原因**: API Key无效或过期

**解决方案**:
1. 检查API Key是否正确
2. 重新申请Key

### CoinGecko 429错误

**原因**: 请求频率过高

**解决方案**:
1. 增加延时 (time.sleep(1))
2. 减少请求次数

---

## 数据覆盖预估

使用所有免费API可达到的覆盖率:

| 数据类别 | 预计覆盖率 |
|----------|-----------|
| 波动率指数 | 100% (VIX, OVX) |
| WTI价格 | 100% (EIA) |
| 黄金期货 | 80% (Yahoo/Alpha Vantage) |
| 比特币 | 100% (CoinGecko) |
| 商品指数 | 50% (DBC替代) |
| **总计** | **85-90%** |

---

## 下一步建议

1. **立即**: 申请EIA和FRED的免费API Key
2. **测试**: 运行 `update_free_data.py` 验证数据质量
3. **整合**: 将免费数据合并到主数据文件
4. **监控**: 设置定时任务定期更新

---

## 相关文件

- `fetchers/free_data_fetcher.py` - 免费数据获取模块
- `update_free_data.py` - 主更新脚本
- `config.py` - API Key配置文件
