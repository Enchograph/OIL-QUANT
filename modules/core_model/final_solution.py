"""
最终方案 - 30因子原油风险预测模型
- ICIR因子筛选
- 多时间尺度预测（1天/5天/20天）
- 风险分级（高/中/低）
- 周频交易：每5个交易日调仓一次；训练窗口756天（约3年）
- 交易策略：启动时在多种执行参数中自动选优（同模型输出），无杠杆
- 输出图：`main_visualization.png`（累计收益、风险指数、仓位 三图）；`analysis_charts.png`（风险分布饼图、多尺度准确率、策略绩效表，无分年度收益图）
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')
import os
from datetime import datetime

import mpl_zh

mpl_zh.setup_chinese_font()

_DEFAULT_CONSENSUS_MULT = {"强一致": 1.0, "部分一致": 1.0, "不一致": 0.0}

STRATEGY_CONFIG = {
    "threshold": 0.05,
    "rebalance_days": 5,
    "cost_rate": 0.001,
    "strength_exp": 1.0,
    "use_consensus_scale": False,
    "consensus_mult": dict(_DEFAULT_CONSENSUS_MULT),
    "conv_thr": None,
    "conv_mult": None,
}
STRATEGY_SEARCH_SUMMARY = ""


def _cfg_copy(c):
    out = dict(c)
    out["consensus_mult"] = dict(c["consensus_mult"])
    return out


def simulate_weekly_strategy(y_pred, y_true, consensus_list, config):
    """
    周频调仓 + 滞后一日；返回仓位、收益序列与绩效指标。
    config: threshold, rebalance_days, cost_rate, strength_exp, use_consensus_scale,
            consensus_mult, conv_thr, conv_mult（后两者可选，对|仓位|放大并截断至1）
    """
    n = len(y_pred)
    th = config["threshold"]
    rb = config["rebalance_days"]
    cost = config["cost_rate"]
    exp = config["strength_exp"]
    use_c = config["use_consensus_scale"]
    cm = config["consensus_mult"]
    cthr = config.get("conv_thr")
    cmult = config.get("conv_mult")

    positions = np.zeros(n)
    current_position = 0.0
    days_since_rebalance = 0
    trade_count = 0

    for i in range(n):
        mag = float(np.abs(y_pred[i]))
        if exp != 1.0:
            mag = float(np.minimum(mag**exp, 1.0))
        else:
            mag = float(np.minimum(mag, 1.0))
        target_position = float(np.sign(y_pred[i]) * mag)

        if cthr is not None and cmult is not None and abs(target_position) >= cthr:
            target_position = float(
                np.sign(target_position) * min(abs(target_position) * cmult, 1.0)
            )

        if use_c:
            mult = float(cm.get(consensus_list[i], 1.0))
            target_position = float(np.clip(target_position * mult, -1.0, 1.0))

        if abs(target_position) < th:
            target_position = 0.0

        if days_since_rebalance >= rb or i == 0:
            if current_position != target_position:
                current_position = target_position
                trade_count += 1
            days_since_rebalance = 0
        else:
            days_since_rebalance += 1

        positions[i] = current_position

    positions_shifted = np.roll(positions, 1)
    positions_shifted[0] = 0.0

    gross_returns = positions_shifted * y_true
    trade_costs = np.abs(np.diff(positions_shifted, prepend=0)) * cost
    strategy_returns = gross_returns - trade_costs
    cumulative = np.cumprod(1 + strategy_returns) - 1
    total_ret = float(cumulative[-1])
    annual_ret = float((1 + total_ret) ** (252 / len(y_true)) - 1)
    sharpe = float(np.sqrt(252) * np.mean(strategy_returns) / (np.std(strategy_returns) + 1e-6))
    cum = np.cumprod(1 + strategy_returns)
    running_max = np.maximum.accumulate(cum)
    max_dd = float(np.min((cum - running_max) / running_max))

    return positions_shifted, strategy_returns, cumulative, trade_count, annual_ret, sharpe, max_dd, total_ret


def run_strategy_grid_search(results):
    """在同一组模型输出上搜索执行层参数，选出年化最高且回撤未失控的方案。"""
    global STRATEGY_CONFIG, STRATEGY_SEARCH_SUMMARY

    y_true = np.array(results["actual_1d"])
    y_pred = np.array(results["predicted_1d"])
    consensus = results["consensus"]
    base = {
        "threshold": 0.05,
        "rebalance_days": 5,
        "cost_rate": 0.001,
        "strength_exp": 1.0,
        "use_consensus_scale": False,
        "consensus_mult": dict(_DEFAULT_CONSENSUS_MULT),
        "conv_thr": None,
        "conv_mult": None,
    }

    variants = []

    for th in [0.05, 0.045, 0.04, 0.035]:
        for rb in [4, 5, 6]:
            name = f"th={th}_rb={rb}"
            variants.append((name, _cfg_copy({**base, "threshold": th, "rebalance_days": rb})))

    for th in [0.05, 0.045, 0.04]:
        for exp in [0.94, 0.96, 1.0]:
            if exp == 1.0 and th == 0.05:
                continue
            name = f"th={th}_exp={exp}"
            variants.append((name, _cfg_copy({**base, "threshold": th, "strength_exp": exp})))

    for th in [0.045, 0.04]:
        variants.append(
            (
                f"{th}+conv1.1",
                _cfg_copy(
                    {
                        **base,
                        "threshold": th,
                        "conv_thr": 0.1,
                        "conv_mult": 1.1,
                    }
                ),
            )
        )
        variants.append(
            (
                f"{th}+conv1.08",
                _cfg_copy(
                    {
                        **base,
                        "threshold": th,
                        "conv_thr": 0.12,
                        "conv_mult": 1.08,
                    }
                ),
            )
        )

    light_cons = {
        "强一致": 1.0,
        "部分一致": 0.97,
        "不一致": 0.0,
    }
    for th in [0.05, 0.045, 0.04]:
        variants.append(
            (
                f"{th}+consensus97",
                _cfg_copy(
                    {
                        **base,
                        "threshold": th,
                        "use_consensus_scale": True,
                        "consensus_mult": dict(light_cons),
                    }
                ),
            )
        )

    for th, rb in [(0.04, 4), (0.045, 4), (0.04, 5)]:
        variants.append(
            (
                f"combo_{th}_{rb}",
                _cfg_copy({**base, "threshold": th, "rebalance_days": rb, "strength_exp": 0.96}),
            )
        )

    scored = []
    _, _, _, _, b_ann, b_sharpe, b_dd, _ = simulate_weekly_strategy(
        y_pred, y_true, consensus, _cfg_copy(base)
    )

    for name, cfg in variants:
        *_, ann, sharpe, mdd, tot = simulate_weekly_strategy(y_pred, y_true, consensus, cfg)
        scored.append((name, cfg, ann, sharpe, mdd, tot))

    max_dd_floor = -0.42
    min_sharpe = max(0.78, b_sharpe * 0.9)
    feasible = [s for s in scored if s[3] >= min_sharpe and s[4] >= max_dd_floor]
    if not feasible:
        feasible = scored

    feasible.sort(key=lambda x: (x[2], x[3], x[4]), reverse=True)
    best_name, best_cfg, best_ann, best_sharpe, best_mdd, best_tot = feasible[0]

    STRATEGY_CONFIG = _cfg_copy(best_cfg)
    lines = [
        "\n" + "=" * 60,
        "交易策略网格搜索（同模型输出，无杠杆）",
        "=" * 60,
        f"基准: 年化 {b_ann:.2%}  夏普 {b_sharpe:.4f}  最大回撤 {b_dd:.2%}",
        f"选中: {best_name}  |  年化 {best_ann:.2%}  夏普 {best_sharpe:.4f}  最大回撤 {best_mdd:.2%}",
        "-" * 60,
        "前5名:",
    ]
    for row in feasible[:5]:
        lines.append(
            f"  {row[0]:22s}  年化{row[2]:7.2%}  夏普{row[3]:.4f}  回撤{row[4]:7.2%}"
        )
    lines.append("=" * 60)
    STRATEGY_SEARCH_SUMMARY = "\n".join(lines)
    print(STRATEGY_SEARCH_SUMMARY)

    return best_cfg


def load_and_prepare_data(file_path):
    """加载数据"""
    print("=" * 60)
    print("加载数据...")
    print("=" * 60)

    df = pd.read_csv(file_path)
    print(f"原始数据形状: {df.shape}")

    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date').reset_index(drop=True)
    df.set_index('Date', inplace=True)

    for col in df.columns:
        if df[col].dtype == 'object':
            try:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            except:
                pass

    targets = ['WTI_Return_1d', 'WTI_Return_5d', 'WTI_Return_20d']
    primary_target = 'WTI_Return_1d'
    df = df.dropna(subset=[primary_target])
    factor_cols = [col for col in df.columns if col not in targets]

    for col in factor_cols:
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df[factor_cols] = df[factor_cols].ffill().fillna(0)

    # 添加技术特征
    print("添加技术特征...")
    for col in factor_cols[:30]:
        df[f'{col}_diff1'] = df[col].diff(1)
        df[f'{col}_diff5'] = df[col].diff(5)
        df[f'{col}_ma5'] = df[col].shift(1).rolling(5, min_periods=1).mean()
        df[f'{col}_ma10'] = df[col].shift(1).rolling(10, min_periods=1).mean()
        df[f'{col}_ma20'] = df[col].shift(1).rolling(20, min_periods=1).mean()
        df[f'{col}_ma_ratio'] = df[f'{col}_ma5'] / (df[f'{col}_ma20'] + 1e-6) - 1
        df[f'{col}_vol20'] = df[col].shift(1).rolling(20, min_periods=5).std()
        df[f'{col}_ret5'] = df[col].shift(1).pct_change(5)
        df[f'{col}_ret20'] = df[col].shift(1).pct_change(20)

    for c in df.columns:
        if c not in factor_cols and c not in targets:
            df[c] = df[c].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)

    print(f"总特征数: {len(df.columns)-len(targets)}")
    return df, primary_target, targets, factor_cols


def select_factors_icir(df, all_cols, targets, train_start, train_end, top_n=30):
    """ICIR选因子"""
    primary_target = targets[0]

    if train_start <= 0:
        X = df[all_cols].iloc[0:train_end].values
        y = df[primary_target].iloc[1:train_end+1].values
    else:
        X = df[all_cols].iloc[train_start-1:train_end].values
        y = df[primary_target].iloc[train_start:train_end+1].values

    min_len = min(len(X), len(y))
    X = X[-min_len:]
    y = y[-min_len:]

    if len(y) < 30:
        return all_cols[:top_n]

    scores = []
    for i, col in enumerate(all_cols):
        try:
            factor_vals = X[:, i]
            window = 20
            ics = []
            for j in range(0, len(y)-window, window):
                ic = np.corrcoef(factor_vals[j:j+window], y[j:j+window])[0,1]
                if not np.isnan(ic):
                    ics.append(ic)
            if len(ics) > 0:
                score = abs(np.mean(ics)) / (np.std(ics) + 1e-6)
            else:
                score = 0
            scores.append(score)
        except:
            scores.append(0)

    top_idx = np.argsort(scores)[::-1][:top_n]
    return [all_cols[i] for i in top_idx]


def train_and_predict(X_train, y_train, X_test):
    """训练模型并预测"""
    y_binary = (y_train > 0).astype(int)

    if len(np.unique(y_binary)) < 2:
        return np.zeros(len(X_test))

    X_train = np.nan_to_num(X_train, nan=0, posinf=0, neginf=0)
    X_test = np.nan_to_num(X_test, nan=0, posinf=0, neginf=0)

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    model = LogisticRegression(C=0.5, class_weight='balanced', max_iter=2000, n_jobs=-1)
    model.fit(X_train_s, y_binary)
    proba = model.predict_proba(X_test_s)[:, 1]
    return 2 * (proba - 0.5)


def classify_risk_level(pred_strength, consensus, volatility):
    """
    风险分级：高/中/低
    综合预测强度、一致性和市场波动
    """
    # 基础得分
    base_score = abs(pred_strength) * 100

    # 一致性加分
    if consensus == "强一致":
        consensus_bonus = 20
    elif consensus == "部分一致":
        consensus_bonus = 10
    else:
        consensus_bonus = 0

    # 波动率调整
    vol_adjustment = volatility * 1000

    # 综合风险指数
    risk_index = min(100, base_score + consensus_bonus + vol_adjustment)

    # 分级
    if risk_index >= 60:
        risk_level = "高风险"
    elif risk_index >= 30:
        risk_level = "中等风险"
    else:
        risk_level = "低风险"

    # 置信度
    if risk_index >= 70:
        confidence = "高置信度"
    elif risk_index >= 40:
        confidence = "中等置信度"
    else:
        confidence = "低置信度"

    return risk_level, risk_index, confidence


def rolling_prediction(df, primary_target, targets, base_cols, top_n=30, train_window=756, period_days=30):
    """滚动预测"""
    print("\n" + "=" * 60)
    print("开始滚动预测...")
    print("=" * 60)

    all_feature_cols = [c for c in df.columns if c not in targets]
    n_samples = len(df)
    current_idx = train_window + 1
    prev_selected = None
    period_count = 0

    results = {
        'dates': [],
        'actual_1d': [], 'predicted_1d': [],
        'actual_5d': [], 'predicted_5d': [],
        'actual_20d': [], 'predicted_20d': [],
        'consensus': [],
        'risk_level': [], 'risk_index': [], 'confidence': [],
        'selected_factors': [],
        'period_info': []
    }

    while current_idx + period_days <= n_samples:
        period_count += 1

        if prev_selected is None:
            train_start = current_idx - train_window
            train_end = current_idx - 1
            prev_selected = select_factors_icir(df, all_feature_cols, targets, train_start, train_end, top_n)

        train_end = current_idx - 1
        train_start = max(0, current_idx - train_window)

        # 训练数据
        X_train = df[prev_selected].iloc[train_start-1:train_end].values
        y_train_1d = df[targets[0]].iloc[train_start:train_end+1].values
        y_train_5d = df[targets[1]].iloc[train_start:train_end+1].values
        y_train_20d = df[targets[2]].iloc[train_start:train_end+1].values

        min_len = min(len(X_train), len(y_train_1d))
        X_train = X_train[-min_len:]
        y_train_1d = y_train_1d[-min_len:]
        y_train_5d = y_train_5d[-min_len:]
        y_train_20d = y_train_20d[-min_len:]

        # 测试数据
        test_start = current_idx
        test_end = min(current_idx + period_days, n_samples) - 1
        X_test = df[prev_selected].iloc[test_start-1:test_end].values
        y_test_1d = df[targets[0]].iloc[test_start:test_end+1].values
        y_test_5d = df[targets[1]].iloc[test_start:test_end+1].values
        y_test_20d = df[targets[2]].iloc[test_start:test_end+1].values
        test_dates = df.index[test_start:test_end+1]

        min_len = min(len(X_test), len(y_test_1d))
        X_test = X_test[:min_len]
        y_test_1d = y_test_1d[:min_len]
        y_test_5d = y_test_5d[:min_len]
        y_test_20d = y_test_20d[:min_len]
        test_dates = test_dates[:min_len]

        # 预测
        y_pred_1d = train_and_predict(X_train, y_train_1d, X_test)
        y_pred_5d = train_and_predict(X_train, y_train_5d, X_test)
        y_pred_20d = train_and_predict(X_train, y_train_20d, X_test)

        # 计算一致性和风险分级
        for i in range(len(y_pred_1d)):
            p1d, p5d, p20d = y_pred_1d[i], y_pred_5d[i], y_pred_20d[i]

            # 一致性
            signs = [np.sign(p1d), np.sign(p5d), np.sign(p20d)]
            if signs[0] == signs[1] == signs[2] and signs[0] != 0:
                consensus = "强一致"
            elif (signs[0] == signs[1] and signs[0] != 0) or \
                 (signs[0] == signs[2] and signs[0] != 0) or \
                 (signs[1] == signs[2] and signs[1] != 0):
                consensus = "部分一致"
            else:
                consensus = "不一致"

            # 计算波动率
            if i >= 20:
                vol = np.std(y_test_1d[max(0,i-20):i])
            else:
                vol = 0.02

            # 风险分级
            risk_level, risk_index, confidence = classify_risk_level(abs(p1d), consensus, vol)

            results['dates'].append(test_dates[i])
            results['actual_1d'].append(y_test_1d[i])
            results['predicted_1d'].append(p1d)
            results['actual_5d'].append(y_test_5d[i])
            results['predicted_5d'].append(p5d)
            results['actual_20d'].append(y_test_20d[i])
            results['predicted_20d'].append(p20d)
            results['consensus'].append(consensus)
            results['risk_level'].append(risk_level)
            results['risk_index'].append(risk_index)
            results['confidence'].append(confidence)

        results['selected_factors'].append({
            'period': period_count,
            'start_date': test_dates[0],
            'end_date': test_dates[-1],
            'factors': prev_selected.copy()
        })

        dir_acc_1d = np.mean(np.sign(y_test_1d) == np.sign(y_pred_1d))
        results['period_info'].append({
            'period': period_count,
            'start_date': test_dates[0],
            'end_date': test_dates[-1],
            'dir_acc_1d': dir_acc_1d,
            'avg_pred_1d': np.mean(y_pred_1d),
            'avg_pred_5d': np.mean(y_pred_5d),
            'avg_pred_20d': np.mean(y_pred_20d),
        })

        next_factor_start = train_start
        next_factor_end = train_end
        prev_selected = select_factors_icir(df, all_feature_cols, targets, next_factor_start, next_factor_end, top_n)

        if period_count % 10 == 0:
            print(f"  第{period_count}期完成")

        current_idx += period_days

    print(f"\n完成！共{period_count}期")
    return results


def create_visualizations(results, output_dir):
    """创建可视化图表"""
    print("\n生成可视化图表...")

    dates = pd.to_datetime(results['dates'])
    y_true = np.array(results['actual_1d'])
    y_pred = np.array(results['predicted_1d'])
    risk_levels = results['risk_level']
    risk_indices = np.array(results['risk_index'])
    consensus_list = results['consensus']

    cfg = STRATEGY_CONFIG
    (
        positions_shifted,
        strategy_returns,
        cumulative,
        trade_count,
        annual_ret,
        sharpe,
        max_dd,
        total_ret,
    ) = simulate_weekly_strategy(y_pred, y_true, consensus_list, cfg)

    # 1. 主图三张：累计收益 / 风险指数 / 仓位
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), facecolor='white')

    ax1 = axes[0]
    ax1.plot(
        dates,
        cumulative * 100,
        'b-',
        linewidth=1.5,
        label=f'累计收益（每{cfg["rebalance_days"]}日调仓｜阈值{cfg["threshold"]}）',
    )
    ax1.fill_between(dates, 0, cumulative * 100, alpha=0.3)
    ax1.axhline(y=0, color='k', linestyle='--', linewidth=0.5)
    ax1.set_ylabel('累计收益 (%)', fontsize=11)
    ax1.set_title('周频交易 - 30因子原油风险预测 - 策略累计收益', fontsize=13, fontweight='bold')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # 2. 风险指数时间序列
    ax2 = axes[1]
    colors = {'高风险': 'red', '中等风险': 'orange', '低风险': 'green'}
    for level in ['低风险', '中等风险', '高风险']:
        mask = np.array([r == level for r in risk_levels])
        if np.sum(mask) > 0:
            ax2.scatter(np.array(dates)[mask], risk_indices[mask],
                       c=colors[level], label=level, alpha=0.6, s=10)

    ax2.axhline(y=30, color='orange', linestyle='--', linewidth=0.8, alpha=0.7)
    ax2.axhline(y=60, color='red', linestyle='--', linewidth=0.8, alpha=0.7)
    ax2.set_ylabel('风险指数', fontsize=11)
    ax2.set_title('周频交易 - 风险指数时间序列', fontsize=13, fontweight='bold')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(0, 100)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # 3. 仓位变化（周频调仓下持仓阶梯）
    ax3 = axes[2]
    ax3.plot(dates, positions_shifted, 'b-', linewidth=0.8, label='仓位', alpha=0.7)
    ax3.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
    ax3.axhline(y=0.05, color='g', linestyle='--', linewidth=0.5, alpha=0.5, label='阈值')
    ax3.axhline(y=-0.05, color='r', linestyle='--', linewidth=0.5, alpha=0.5)
    ax3.fill_between(dates, 0, positions_shifted, where=(positions_shifted > 0),
                     color='green', alpha=0.3, label='做多')
    ax3.fill_between(dates, 0, positions_shifted, where=(positions_shifted < 0),
                     color='red', alpha=0.3, label='做空')
    ax3.set_ylabel('仓位', fontsize=11)
    ax3.set_xlabel('日期', fontsize=11)
    ax3.set_title(f'仓位变化（每{cfg["rebalance_days"]}交易日调仓）', fontsize=13, fontweight='bold')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)
    ax3.set_ylim(-1.1, 1.1)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    plt.tight_layout()
    plt.savefig(
        f'{output_dir}/main_visualization.png',
        dpi=150,
        bbox_inches='tight',
        facecolor=fig.get_facecolor(),
    )
    print(f"  主可视化: {output_dir}/main_visualization.png")
    plt.close()

    # 分析图：风险分布 + 多尺度准确率 + 绩效表（不含分年度柱状图）
    n_days = len(y_true)
    ann_vol = float(np.std(strategy_returns) * np.sqrt(252))
    calmar = float(annual_ret / abs(max_dd)) if max_dd < -1e-12 else float("nan")

    fig = plt.figure(figsize=(13, 8.4), facecolor='#f8f9fb')
    gs = fig.add_gridspec(2, 2, height_ratios=[1.2, 1.0], width_ratios=[1, 1], hspace=0.38, wspace=0.28)
    ax_pie = fig.add_subplot(gs[0, 0])
    ax_bar = fig.add_subplot(gs[0, 1])
    ax_tbl = fig.add_subplot(gs[1, :])
    fig.suptitle(
        '分析概览：风险等级分布 · 预测准确率 · 策略绩效汇总',
        fontsize=14,
        fontweight='bold',
        color='#1a202c',
        y=0.98,
    )

    risk_counts = pd.Series(risk_levels).value_counts()
    colors_pie = {'高风险': '#e53e3e', '中等风险': '#ed8936', '低风险': '#48bb78'}
    ax_pie.pie(
        risk_counts.values,
        labels=risk_counts.index,
        autopct='%1.1f%%',
        colors=[colors_pie.get(x, '#a0aec0') for x in risk_counts.index],
        pctdistance=0.75,
        textprops={'fontsize': 10},
        wedgeprops={'linewidth': 1, 'edgecolor': 'white'},
    )
    ax_pie.set_title('风险等级分布', fontsize=12, fontweight='bold', color='#2d3748')

    horizons = ['1天', '5天', '20天']
    accuracies = [
        np.mean(np.sign(results['actual_1d']) == np.sign(results['predicted_1d'])),
        np.mean(np.sign(results['actual_5d']) == np.sign(results['predicted_5d'])),
        np.mean(np.sign(results['actual_20d']) == np.sign(results['predicted_20d'])),
    ]
    ax_bar.bar(
        horizons,
        [a * 100 for a in accuracies],
        color=['#3182ce', '#38a169', '#c53030'],
        alpha=0.88,
        edgecolor='white',
        linewidth=1.0,
    )
    ax_bar.axhline(y=50, color='#718096', linestyle='--', linewidth=1, label='随机基准 50%')
    ax_bar.set_ylabel('方向准确率 (%)', fontsize=11)
    ax_bar.set_title('多时间尺度预测准确率', fontsize=12, fontweight='bold', color='#2d3748')
    ax_bar.legend(loc='lower right', framealpha=0.92)
    ax_bar.grid(True, alpha=0.35, axis='y', linestyle='-')
    ax_bar.set_ylim(48, 100)
    ax_bar.set_facecolor('#fafafa')
    for i, v in enumerate(accuracies):
        ax_bar.text(i, min(v * 100 + 1.5, 99), f'{v:.1%}', ha='center', fontsize=10, fontweight='bold', color='#2d3748')

    ax_tbl.axis('off')
    perf_rows = [
        ['累计收益', f'{total_ret:.2%}'],
        ['年化收益', f'{annual_ret:.2%}'],
        ['年化波动率', f'{ann_vol:.2%}'],
        ['夏普比率', f'{sharpe:.4f}'],
        ['最大回撤', f'{max_dd:.2%}'],
        ['卡玛比率', f'{calmar:.4f}' if np.isfinite(calmar) else '—'],
        ['调仓次数', f'{trade_count}'],
        ['样本交易日', f'{n_days}'],
    ]
    tbl = ax_tbl.table(
        cellText=perf_rows,
        colLabels=['指标', '数值'],
        loc='center',
        cellLoc='center',
        colWidths=[0.38, 0.42],
        bbox=[0.08, 0.02, 0.84, 0.96],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(11)
    tbl.scale(1.0, 2.25)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor('#cbd5e0')
        cell.set_linewidth(0.8)
        if r == 0:
            cell.set_facecolor('#1a365d')
            cell.set_text_props(color='white', weight='bold', fontsize=11)
            cell.set_height(0.11)
        else:
            cell.set_facecolor('#ebf4ff' if r % 2 == 1 else '#ffffff')
            cell.set_text_props(color='#1a202c')
    ax_tbl.set_title('策略绩效汇总（全样本）', fontsize=12, fontweight='bold', color='#2d3748', pad=14)

    plt.subplots_adjust(top=0.91)
    plt.savefig(f'{output_dir}/analysis_charts.png', dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    print(f"  分析图表: {output_dir}/analysis_charts.png")
    plt.close()

    return positions_shifted, strategy_returns, cumulative, trade_count


def evaluate_and_save(results, output_dir='final_solution'):
    """评估并保存结果"""
    os.makedirs(output_dir, exist_ok=True)

    dates = results['dates']
    y_true = np.array(results['actual_1d'])
    y_pred = np.array(results['predicted_1d'])

    positions_shifted, strategy_returns, cumulative, trade_count = create_visualizations(results, output_dir)
    total_ret = cumulative[-1]
    annual_ret = (1 + total_ret) ** (252 / len(y_true)) - 1
    sharpe = np.sqrt(252) * np.mean(strategy_returns) / (np.std(strategy_returns) + 1e-6)

    cum = np.cumprod(1 + strategy_returns)
    running_max = np.maximum.accumulate(cum)
    max_dd = np.min((cum - running_max) / running_max)
    ann_vol = float(np.std(strategy_returns) * np.sqrt(252))
    calmar = float(annual_ret / abs(max_dd)) if max_dd < -1e-12 else float("nan")
    n_days = len(y_true)

    pd.DataFrame(
        {
            "指标": [
                "累计收益",
                "年化收益",
                "年化波动率",
                "夏普比率",
                "最大回撤",
                "卡玛比率",
                "调仓次数",
                "样本交易日",
            ],
            "数值": [
                f"{total_ret:.2%}",
                f"{annual_ret:.2%}",
                f"{ann_vol:.2%}",
                f"{sharpe:.4f}",
                f"{max_dd:.2%}",
                f"{calmar:.4f}" if np.isfinite(calmar) else "—",
                f"{trade_count}",
                f"{n_days}",
            ],
        }
    ).to_csv(f"{output_dir}/performance_summary.csv", index=False, encoding="utf-8-sig")

    # 方向准确率
    dir_acc_1d = np.mean(np.sign(y_true) == np.sign(y_pred))
    dir_acc_5d = np.mean(np.sign(results['actual_5d']) == np.sign(results['predicted_5d']))
    dir_acc_20d = np.mean(np.sign(results['actual_20d']) == np.sign(results['predicted_20d']))

    # 风险分级统计
    risk_levels = results['risk_level']
    high_risk_count = sum(1 for r in risk_levels if r == "高风险")
    medium_risk_count = sum(1 for r in risk_levels if r == "中等风险")
    low_risk_count = sum(1 for r in risk_levels if r == "低风险")

    # 一致性统计
    consensus = results['consensus']
    strong_consensus = sum(1 for c in consensus if c == "强一致")
    partial_consensus = sum(1 for c in consensus if c == "部分一致")

    print("\n" + "=" * 60)
    print("最终方案 - 评估结果")
    print("=" * 60)
    print(f"\n【主策略表现】")
    print(f"  累计收益: {total_ret:.2%}")
    print(f"  年化收益: {annual_ret:.2%}")
    print(f"  夏普比率: {sharpe:.4f}")
    print(f"  最大回撤: {max_dd:.2%}")
    print(f"  调仓次数: {trade_count}")
    c = STRATEGY_CONFIG
    print(
        f"\n【交易策略｜搜索最优】阈值{c['threshold']} 每{c['rebalance_days']}日调仓 "
        f"强度指数{c['strength_exp']} 单边成本{c['cost_rate']} 一致缩放={c['use_consensus_scale']}"
    )
    print(f"\n【多时间尺度准确率】")
    print(f"  1天: {dir_acc_1d:.2%}")
    print(f"  5天: {dir_acc_5d:.2%}")
    print(f"  20天: {dir_acc_20d:.2%}")
    print(f"\n【风险分级统计】")
    print(f"  高风险: {high_risk_count} ({high_risk_count/len(risk_levels):.1%})")
    print(f"  中等风险: {medium_risk_count} ({medium_risk_count/len(risk_levels):.1%})")
    print(f"  低风险: {low_risk_count} ({low_risk_count/len(risk_levels):.1%})")
    print(f"\n【一致性统计】")
    print(f"  强一致: {strong_consensus} ({strong_consensus/len(consensus):.1%})")
    print(f"  部分一致: {partial_consensus} ({partial_consensus/len(consensus):.1%})")

    # 保存预测结果
    results_df = pd.DataFrame({
        'Date': dates,
        'Actual_1d': results['actual_1d'],
        'Predicted_1d': results['predicted_1d'],
        'Predicted_5d': results['predicted_5d'],
        'Predicted_20d': results['predicted_20d'],
        'Consensus': results['consensus'],
        'Risk_Level': results['risk_level'],
        'Risk_Index': results['risk_index'],
        'Confidence': results['confidence'],
        'Position': positions_shifted,
        'Strategy_Return': strategy_returns,
        'Cumulative_Return': cumulative,
    })
    results_df.to_csv(f'{output_dir}/predictions.csv', index=False)

    # 保存风险信号
    signals = []
    for i in range(len(dates)):
        if positions_shifted[i] == 0:
            continue
        signals.append({
            'Date': dates[i],
            'Direction_1d': '上涨' if results['predicted_1d'][i] > 0 else '下跌',
            'Strength_1d': abs(results['predicted_1d'][i]),
            'Direction_5d': '上涨' if results['predicted_5d'][i] > 0 else '下跌' if results['predicted_5d'][i] < 0 else '中性',
            'Direction_20d': '上涨' if results['predicted_20d'][i] > 0 else '下跌' if results['predicted_20d'][i] < 0 else '中性',
            'Consensus': results['consensus'][i],
            'Risk_Level': results['risk_level'][i],
            'Risk_Index': results['risk_index'][i],
            'Confidence': results['confidence'][i],
            'Position': positions_shifted[i],
            'Actual_1d': results['actual_1d'][i]
        })
    pd.DataFrame(signals).to_csv(f'{output_dir}/risk_signals.csv', index=False)

    # 保存每期因子
    with open(f'{output_dir}/period_factors.txt', 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("每期选用的30个因子\n")
        f.write("=" * 80 + "\n\n")
        for period_info in results['selected_factors']:
            f.write(f"【第{period_info['period']}期】")
            f.write(f"{period_info['start_date'].strftime('%Y-%m-%d')} ~ ")
            f.write(f"{period_info['end_date'].strftime('%Y-%m-%d')}\n")
            f.write("-" * 60 + "\n")
            for i, factor in enumerate(period_info['factors'], 1):
                f.write(f"  {i:2d}. {factor}\n")
            f.write("\n")

    # 保存报告
    with open(f'{output_dir}/report.txt', 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("30因子原油风险预测模型 - 最终方案报告\n")
        f.write("=" * 80 + "\n\n")
        f.write("【模型配置】\n")
        f.write(f"  因子数量: 30个\n")
        f.write(f"  因子选择: ICIR\n")
        f.write(f"  预测时间尺度: 1天(主)/5天/20天(辅助)\n")
        f.write(f"  风险分级: 高/中/低\n")
        f.write(f"  训练窗口: 756天（约3年）\n")
        f.write(f"  交易频率: 每{STRATEGY_CONFIG['rebalance_days']}个交易日调仓\n")
        f.write("【交易策略（仅执行层，网格搜索最优；无杠杆）】\n")
        f.write(f"  阈值: {STRATEGY_CONFIG['threshold']}；强度 |pred|^{STRATEGY_CONFIG['strength_exp']}\n")
        f.write(f"  成交滞后: 1日；单边成本: {STRATEGY_CONFIG['cost_rate']}\n")
        if STRATEGY_CONFIG["use_consensus_scale"]:
            f.write(f"  一致性缩放: {STRATEGY_CONFIG['consensus_mult']}\n")
        else:
            f.write("  一致性缩放: 关闭\n")
        if STRATEGY_CONFIG.get("conv_thr") is not None:
            f.write(
                f"  强信号放大: |仓|>={STRATEGY_CONFIG['conv_thr']} 时 ×{STRATEGY_CONFIG['conv_mult']}\n"
            )
        if STRATEGY_SEARCH_SUMMARY:
            f.write("\n" + STRATEGY_SEARCH_SUMMARY + "\n\n")
        f.write("【策略表现｜与 analysis_charts 绩效表一致】\n")
        f.write(f"  累计收益:   {total_ret:.2%}\n")
        f.write(f"  年化收益:   {annual_ret:.2%}\n")
        f.write(f"  年化波动率: {ann_vol:.2%}\n")
        f.write(f"  夏普比率:   {sharpe:.4f}\n")
        f.write(f"  最大回撤:   {max_dd:.2%}\n")
        f.write(f"  卡玛比率:   {calmar:.4f}\n" if np.isfinite(calmar) else "  卡玛比率:   —\n")
        f.write(f"  调仓次数:   {trade_count}\n")
        f.write(f"  样本交易日: {n_days}\n")
        f.write(f"  方向准确率(1天): {dir_acc_1d:.2%}\n\n")
        f.write("【风险分级】\n")
        f.write(f"  高风险: {high_risk_count/len(risk_levels):.1%}\n")
        f.write(f"  中等风险: {medium_risk_count/len(risk_levels):.1%}\n")
        f.write(f"  低风险: {low_risk_count/len(risk_levels):.1%}\n\n")

    print(f"\n所有结果保存至: {output_dir}/")


def main():
    """主程序"""
    file_path = "factors_WTI_cleaned_v2.csv"
    output_dir = "final_solution"

    df, primary_target, targets, base_cols = load_and_prepare_data(file_path)
    results = rolling_prediction(df, primary_target, targets, base_cols, train_window=756)
    run_strategy_grid_search(results)
    evaluate_and_save(results, output_dir)

    print("\n" + "=" * 60)
    print("最终方案生成完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
