# 快速开始指南

**目标**: 5分钟内完成环境配置并成功运行数据更新

---

## 第一步：安装Python依赖（1分钟）

```bash
pip install pandas numpy requests akshare xlrd openpyxl
```

**验证安装**:
```bash
python -c "import pandas; print('pandas:', pandas.__version__)"
```

---

## 第二步：申请EIA API Key（2分钟）

**必须完成！** 否则无法获取WTI价格数据。

1. 访问 https://www.eia.gov/opendata/register.php
2. 填写邮箱地址
3. 查收邮件，复制32位API Key
4. 编辑 `config.py`:

```python
EIA_API_KEY = "粘贴你的32位API Key到这里"
```

**格式示例**: `1a6486320ecc18d8ebf6d6e3c2b1303b`

---

## 第三步：运行测试（1分钟）

```bash
# 测试网络连通性
python test_network.py your_eia_api_key
```

**期望输出**:
```
✓ CBOE: 正常
✓ EIA: 正常
✓ FRED: 正常
```

---

## 第四步：运行数据更新（1分钟）

```bash
# 更新最近90天数据
python run_all_updates.py
```

**输出文件**:
- `wti_factors_YYYYMMDD.csv` - 更新的因子数据
- `coverage_report_YYYYMMDD.txt` - 覆盖情况报告

---

## 常见问题排查

### 问题1: "EIA API Key格式错误"
**原因**: Key不是32位字母数字
**解决**: 重新申请，确保复制完整的Key

### 问题2: "网络连接失败"
**原因**: 可能被防火墙拦截
**解决**: 配置代理（编辑config.py）:
```python
PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
```

### 问题3: "未获取到任何数据"
**原因**: API Key无效或过期
**解决**: 重新申请EIA API Key

---

## 数据延迟说明（重要！）

| 因子类型 | 延迟 | 示例 |
|----------|------|------|
| **日频** | T+1~2天 | VIX, WTI价格, 美元指数 |
| **周频** | 2-7天 | 原油库存, CFTC持仓 |
| **月频** | 30天 | GPR, TPU, 美国产量 |

**注意**: 月度数据月内数值不变，使用前需前向填充。

---

## 下一步

- 查看 `DATA_FRESHNESS_REPORT.md` 了解各因子延迟情况
- 查看 `FACTOR_COVERAGE_REPORT.md` 了解214个因子详情
- 根据延迟特性选择合适的因子用于模型

---

**完成！** 现在你可以自动更新WTI因子数据了。
