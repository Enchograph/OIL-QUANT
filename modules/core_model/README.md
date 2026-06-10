# 30 因子 WTI 原油风险预测模型

本项目是一个基于 `Python + pandas + scikit-learn + matplotlib` 的原油风险预测与策略回测原型，核心目标是利用多源宏观、市场、库存、地缘政治等因子，对 WTI 原油短期收益方向进行滚动预测，并将预测结果转换为风险分级与交易信号。

当前目录主要保存核心模型代码和一次已落地的模型输出结果，适合用于：

- 复现已有的 WTI 风险预测结果
- 理解因子筛选、滚动训练、信号生成和策略评估流程
- 在现有脚本基础上继续做参数优化或模型替换

## 项目概览

主脚本 [`final_solution.py`](./final_solution.py) 实现了完整的最终方案，包含以下流程：

1. 读取 `factors_WTI_cleaned_v2.csv`
2. 清洗字段并构造技术特征
3. 使用 ICIR 方法筛选 30 个因子
4. 对 1 天、5 天、20 天三个时间尺度做滚动预测
5. 基于多时间尺度一致性输出风险等级、风险指数和置信度
6. 在固定模型输出上做执行层参数搜索
7. 生成策略回测结果、可视化图表和文本报告

项目中还保留了两个对比版本：

- [`final_solution_5day_rebalance.py`](./final_solution_5day_rebalance.py)
  早期版本，固定每 5 个交易日调仓，逻辑相对直接
- [`final_solution_4year.py`](./final_solution_4year.py)
  使用约 4 年训练窗口（1008 天）做滚动预测的对比版本
- [`mpl_zh.py`](./mpl_zh.py)
  Matplotlib 中文字体初始化，避免中文图表乱码

## 目录结构

```text
core_model/
├─ final_solution.py
├─ final_solution_4year.py
├─ final_solution_5day_rebalance.py
├─ mpl_zh.py
├─ factors_WTI_cleaned_v2.csv
├─ final_solution/
│  ├─ analysis_charts.png
│  ├─ main_visualization.png
│  ├─ period_factors.txt
│  ├─ performance_summary.csv
│  ├─ predictions.csv
│  ├─ report.txt
│  └─ risk_signals.csv
└─ __pycache__/
```

## 建模思路

### 1. 数据输入

输入文件固定为：

- `factors_WTI_cleaned_v2.csv`

脚本默认要求该文件与 `final_solution.py` 位于同一目录。数据中至少应包含：

- 日期列：`Date`
- 目标列：
  - `WTI_Return_1d`
  - `WTI_Return_5d`
  - `WTI_Return_20d`
- 其余列作为候选因子输入

从样例数据可见，候选因子覆盖以下类别：

- WTI 价格、收益、波动率、均线、突破信号
- 波动率与风险偏好指标，如 `OVX`、`VIX`
- 股指、美元、黄金、能源 ETF、期货等跨资产变量
- 库存、供需、产量、消费等基本面变量
- 地缘政治风险指标，如 `GPR`、`GPRH` 及各国拆分指标
- 文本事件统计指标，如新闻数量、冲突强度、情绪统计等

### 2. 特征工程

脚本会对前 30 个基础因子自动扩展一批技术特征，包括：

- 1 日、5 日差分
- 5/10/20 日均线
- 5 日均线相对 20 日均线偏离
- 20 日滚动波动率
- 5 日、20 日收益率变化

缺失值处理策略为：

- 非数值字段尝试转数值
- 候选因子使用前向填充后再以 `0` 补齐
- `inf/-inf` 转为缺失后继续填充

### 3. 因子筛选

项目使用 ICIR 思路从候选特征中筛选 30 个因子：

- 以 20 个样本为一个小窗口计算因子与未来 1 日收益的相关性
- 用 `|IC 均值| / IC 标准差` 作为评分
- 每期选取得分最高的 30 个因子进入后续训练

这一步是滚动执行的，因此不同阶段的入选因子会发生变化，最终保存在 `period_factors.txt` 中。

### 4. 预测目标

模型同时对三个收益周期进行预测：

- `1d`：主预测目标，用于生成交易方向和主要风险信号
- `5d`：辅助确认
- `20d`：辅助确认

三个周期的方向一致性会被进一步转换为：

- `强一致`
- `部分一致`
- `不一致`

### 5. 模型训练

当前脚本使用的是逻辑回归方向分类模型：

- `StandardScaler` 标准化特征
- `LogisticRegression(C=0.5, class_weight='balanced', max_iter=2000, n_jobs=-1)`

输出不是直接分类标签，而是用：

```python
2 * (proba - 0.5)
```

将上涨概率映射到 `[-1, 1]` 区间，用于表示方向和强度。

### 6. 风险分级

风险等级来自以下信息的组合：

- 1 日预测强度绝对值
- 多时间尺度一致性
- 近期波动率

脚本最终输出：

- 风险等级：`高风险 / 中等风险 / 低风险`
- 风险指数：`0 ~ 100`
- 置信度：`高 / 中 / 低`

### 7. 交易与回测

`final_solution.py` 的执行层不是固定参数，而是对同一批预测结果做一轮参数搜索，搜索内容包括：

- 开仓阈值
- 调仓频率
- 仓位强度指数
- 强信号放大
- 一致性缩放

在回撤和夏普约束下选出更优组合，再生成最终策略表现。

核心回测假设包括：

- 无杠杆
- 仓位范围 `[-1, 1]`
- 信号滞后 1 个交易日执行
- 默认单边交易成本 `0.001`

## 运行环境

### Python 版本

建议使用：

- Python 3.10 及以上

### 依赖库

按源码实际导入，最少需要以下库：

```bash
pip install numpy pandas matplotlib scikit-learn
```

如果图表存在中文乱码，需要保证系统安装了中文字体。项目已经通过 [`mpl_zh.py`](./mpl_zh.py) 自动尝试以下字体：

- Microsoft YaHei
- SimHei
- PingFang SC
- Noto Sans CJK SC
- Source Han Sans SC

## 快速开始

在当前目录执行：

```bash
python final_solution.py
```

如果你想运行对比脚本，也可以执行：

```bash
python final_solution_5day_rebalance.py
python final_solution_4year.py
```

## 运行后输出

`final_solution.py` 默认会在 [`final_solution/`](./final_solution) 目录下生成以下文件：

### 1. `main_visualization.png`

主可视化图，通常包含三部分：

- 策略累计收益曲线
- 风险指数时间序列
- 仓位变化图

### 2. `analysis_charts.png`

辅助分析图，包含：

- 风险等级分布
- 多时间尺度准确率或对比图
- 策略绩效表

### 3. `predictions.csv`

逐日预测结果明细，主要字段包括：

- `Date`
- `Actual_1d`
- `Predicted_1d`
- `Predicted_5d`
- `Predicted_20d`
- `Consensus`
- `Risk_Level`
- `Risk_Index`
- `Confidence`
- `Position`
- `Strategy_Return`
- `Cumulative_Return`

### 4. `risk_signals.csv`

只保留实际产生仓位的风险/交易信号，适合直接查看有效信号样本。

### 5. `period_factors.txt`

每个滚动阶段实际选中的 30 个因子，用于解释模型在不同时间段关注的因子变化。

### 6. `performance_summary.csv`

策略汇总表现表，便于后续汇报或导入其他分析工具。

### 7. `report.txt`

文本版总报告，汇总模型配置、最优执行层参数和回测指标。

## 脚本差异说明

### `final_solution.py`

当前推荐阅读和复现的主版本，特点是：

- 训练窗口约 3 年（756 个交易日）
- 多时间尺度预测
- 风险分级
- 执行层网格搜索
- 输出文件最完整

### `final_solution_5day_rebalance.py`

适合看“固定 5 日调仓”这一思路的实现，特点是：

- 逻辑更直观
- 固定调仓频率
- 早期图表里仍保留年度收益展示
- 更适合作为简化版参考

### `final_solution_4year.py`

适合做训练窗口长度对比，特点是：

- 训练窗口增加到 1008 天
- 核心建模思路与主版本一致
- 用于评估长窗口是否优于 3 年窗口设定

## 适合继续改进的方向

如果后续要继续开发，优先建议从这些方向入手：

- 将数据路径、输出路径、训练窗口、调仓参数改成命令行参数
- 补充 `requirements.txt` 或 `pyproject.toml`
- 将特征工程、因子筛选、训练、评估拆成独立模块
- 引入时间序列交叉验证，避免只看单一路径回测结果
- 将逻辑回归替换为树模型、线性回归或集成模型做对比
- 增加结果缓存，减少重复跑全量数据的耗时

## 已知限制

当前项目更像研究原型，而不是可直接上线的生产系统，主要限制包括：

- 脚本参数基本写死在源码里
- 缺少依赖清单文件
- 没有自动化测试
- 没有统一的日志与配置管理
- 数据字典尚未单独整理
- 输出目录与输入文件名是硬编码的

## 常见问题

### 1. 运行时报中文乱码

优先检查系统是否安装中文字体。项目会自动尝试常见字体，但如果系统本身没有相关字体，Matplotlib 仍可能显示异常。

### 2. 运行时报缺少依赖

先安装：

```bash
pip install numpy pandas matplotlib scikit-learn
```

### 3. 图表或结果没有生成

重点检查：

- 当前工作目录是否就是本目录
- `factors_WTI_cleaned_v2.csv` 是否存在
- 运行过程中是否有中断或权限问题

### 4. 想替换成自己的数据

至少需要保证：

- 有 `Date` 列
- 有 `WTI_Return_1d / WTI_Return_5d / WTI_Return_20d` 三个目标列
- 其余因子列尽量为可转数值的时间序列

## 说明

本次整理 README 时，仓库内未找到规则中提到的 `docs/用户最初需求.md`，因此本文档是基于现有源码、数据文件和已生成结果反向梳理得出。若后续补齐原始需求文档，建议再对 README 做一次对照修订。
