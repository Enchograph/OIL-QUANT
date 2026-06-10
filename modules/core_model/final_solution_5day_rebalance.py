"""
最终方案 - 5天调仓版本
交易频次改为每5天一次调仓，降低交易成本
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


def load_and_prepare_data(file_path):
    """加载数据"""
    print("=" * 60)
    print("加载数据（5天调仓版）...")
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
    """风险分级"""
    base_score = abs(pred_strength) * 100

    if consensus == "强一致":
        consensus_bonus = 20
    elif consensus == "部分一致":
        consensus_bonus = 10
    else:
        consensus_bonus = 0

    vol_adjustment = volatility * 1000
    risk_index = min(100, base_score + consensus_bonus + vol_adjustment)

    if risk_index >= 60:
        risk_level = "高风险"
    elif risk_index >= 30:
        risk_level = "中等风险"
    else:
        risk_level = "低风险"

    if risk_index >= 70:
        confidence = "高置信度"
    elif risk_index >= 40:
        confidence = "中等置信度"
    else:
        confidence = "低置信度"

    return risk_level, risk_index, confidence


def rolling_prediction(df, primary_target, targets, base_cols, top_n=30, train_window=756, period_days=30):
    """滚动预测 - 5天调仓"""
    print("\n" + "=" * 60)
    print(f"30因子滚动预测 - 5天调仓版")
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

            signs = [np.sign(p1d), np.sign(p5d), np.sign(p20d)]
            if signs[0] == signs[1] == signs[2] and signs[0] != 0:
                consensus = "强一致"
            elif (signs[0] == signs[1] and signs[0] != 0) or \
                 (signs[0] == signs[2] and signs[0] != 0) or \
                 (signs[1] == signs[2] and signs[1] != 0):
                consensus = "部分一致"
            else:
                consensus = "不一致"

            if i >= 20:
                vol = np.std(y_test_1d[max(0,i-20):i])
            else:
                vol = 0.02

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

    # 计算策略收益 - 5天调仓
    threshold = 0.05
    rebalance_freq = 5  # 每5天调仓一次

    positions = np.zeros(len(y_pred))
    current_position = 0
    days_since_rebalance = 0
    trade_count = 0

    for i in range(len(y_pred)):
        # 计算目标仓位
        target_position = np.sign(y_pred[i]) * np.minimum(np.abs(y_pred[i]), 1.0)
        if np.abs(target_position) < threshold:
            target_position = 0

        # 判断是否需要调仓
        if days_since_rebalance >= rebalance_freq or i == 0:
            if current_position != target_position:
                current_position = target_position
                trade_count += 1
            days_since_rebalance = 0
        else:
            days_since_rebalance += 1

        positions[i] = current_position

    # 延迟一期执行
    positions_shifted = np.roll(positions, 1)
    positions_shifted[0] = 0

    gross_returns = positions_shifted * y_true

    # 计算交易成本 - 只在调仓时产生
    position_changes = np.diff(positions_shifted, prepend=0)
    trade_costs = np.abs(position_changes) * 0.001  # 0.1%单边成本
    strategy_returns = gross_returns - trade_costs

    cumulative = np.cumprod(1 + strategy_returns) - 1

    # 1. 累计收益曲线
    fig, axes = plt.subplots(3, 1, figsize=(14, 12))

    ax1 = axes[0]
    ax1.plot(dates, cumulative * 100, 'b-', linewidth=1.5, label='策略累计收益（5天调仓）')
    ax1.fill_between(dates, 0, cumulative * 100, alpha=0.3)
    ax1.axhline(y=0, color='k', linestyle='--', linewidth=0.5)
    ax1.set_ylabel('累计收益 (%)', fontsize=11)
    ax1.set_title('5天调仓 - 30因子原油风险预测模型 - 策略累计收益', fontsize=13, fontweight='bold')
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
    ax2.set_title('5天调仓 - 风险指数时间序列', fontsize=13, fontweight='bold')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(0, 100)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # 3. 仓位变化图
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
    ax3.set_title('5天调仓 - 仓位变化图', fontsize=13, fontweight='bold')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)
    ax3.set_ylim(-1.1, 1.1)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    plt.tight_layout()
    plt.savefig(f'{output_dir}/main_visualization.png', dpi=150, bbox_inches='tight')
    print(f"  主可视化: {output_dir}/main_visualization.png")
    plt.close()

    # 4. 分析图表
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    # 风险分级分布
    risk_counts = pd.Series(risk_levels).value_counts()
    colors_pie = {'高风险': '#ff6b6b', '中等风险': '#ffd93d', '低风险': '#6bcf7f'}
    axes[0].pie(risk_counts.values, labels=risk_counts.index, autopct='%1.1f%%',
                colors=[colors_pie.get(x, 'gray') for x in risk_counts.index])
    axes[0].set_title('5天调仓 - 风险等级分布', fontsize=12, fontweight='bold')

    # 年度收益柱状图
    yearly_data = pd.DataFrame({'Date': dates, 'Return': strategy_returns})
    yearly_data['Year'] = yearly_data['Date'].dt.year
    yearly_returns = yearly_data.groupby('Year')['Return'].apply(lambda x: (1 + x).prod() - 1)

    colors_bar = ['green' if r > 0 else 'red' for r in yearly_returns.values]
    axes[1].bar(yearly_returns.index.astype(str), yearly_returns.values * 100, color=colors_bar, alpha=0.7)
    axes[1].axhline(y=0, color='k', linestyle='-', linewidth=0.5)
    axes[1].set_ylabel('年化收益 (%)', fontsize=11)
    axes[1].set_title('5天调仓 - 年度收益表现', fontsize=12, fontweight='bold')
    axes[1].grid(True, alpha=0.3, axis='y')
    axes[1].tick_params(axis='x', rotation=45)

    # 预测准确率对比
    horizons = ['1天', '5天', '20天']
    accuracies = [
        np.mean(np.sign(results['actual_1d']) == np.sign(results['predicted_1d'])),
        np.mean(np.sign(results['actual_5d']) == np.sign(results['predicted_5d'])),
        np.mean(np.sign(results['actual_20d']) == np.sign(results['predicted_20d']))
    ]
    axes[2].bar(horizons, [a * 100 for a in accuracies], color=['#3498db', '#2ecc71', '#e74c3c'], alpha=0.7)
    axes[2].axhline(y=50, color='k', linestyle='--', linewidth=0.8, label='随机基准')
    axes[2].set_ylabel('方向准确率 (%)', fontsize=11)
    axes[2].set_title('5天调仓 - 多时间尺度预测准确率', fontsize=12, fontweight='bold')
    axes[2].legend()
    axes[2].grid(True, alpha=0.3, axis='y')
    axes[2].set_ylim(40, 100)

    for i, v in enumerate(accuracies):
        axes[2].text(i, v * 100 + 1, f'{v:.1%}', ha='center', fontsize=10)

    plt.tight_layout()
    plt.savefig(f'{output_dir}/analysis_charts.png', dpi=150, bbox_inches='tight')
    print(f"  分析图表: {output_dir}/analysis_charts.png")
    plt.close()

    return positions_shifted, strategy_returns, cumulative, trade_count


def evaluate_and_save(results, output_dir='final_solution_5day'):
    """评估并保存结果"""
    os.makedirs(output_dir, exist_ok=True)

    dates = results['dates']
    y_true = np.array(results['actual_1d'])
    y_pred = np.array(results['predicted_1d'])

    # 生成可视化和计算收益
    positions_shifted, strategy_returns, cumulative, trade_count = create_visualizations(results, output_dir)

    total_ret = cumulative[-1]
    annual_ret = (1 + total_ret) ** (252 / len(y_true)) - 1
    sharpe = np.sqrt(252) * np.mean(strategy_returns) / (np.std(strategy_returns) + 1e-6)

    cum = np.cumprod(1 + strategy_returns)
    running_max = np.maximum.accumulate(cum)
    max_dd = np.min((cum - running_max) / running_max)

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
    print("5天调仓版 - 评估结果")
    print("=" * 60)
    print(f"\n【主策略表现】")
    print(f"  累计收益: {total_ret:.2%}")
    print(f"  年化收益: {annual_ret:.2%}")
    print(f"  夏普比率: {sharpe:.4f}")
    print(f"  最大回撤: {max_dd:.2%}")
    print(f"  调仓次数: {trade_count}")
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

    # 对比每日调仓
    print("\n" + "=" * 60)
    print("对比分析（每日调仓 vs 5天调仓）")
    print("=" * 60)
    print("| 指标       | 每日调仓 | 5天调仓 | 变化 |")
    print("|------------|----------|---------|------|")
    print(f"| 年化收益   |  8.06%   | {annual_ret:6.2%} | {'↑' if annual_ret > 0.0806 else '↓'} |")
    print(f"| 夏普比率   |  0.7167  | {sharpe:7.4f} | {'↑' if sharpe > 0.7167 else '↓'} |")
    print(f"| 最大回撤   | -31.12%  | {max_dd:7.2%} | {'↑' if max_dd > -0.3112 else '↓'} |")
    print(f"| 调仓次数   |  1659    | {trade_count:5}   | -{1659-trade_count} |")

    # 保存结果
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

    # 保存报告
    with open(f'{output_dir}/report.txt', 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("30因子原油风险预测模型 - 5天调仓版报告\n")
        f.write("=" * 80 + "\n\n")
        f.write("【模型配置】\n")
        f.write(f"  训练窗口: 756天（3年）\n")
        f.write(f"  调仓频率: 每5天一次\n")
        f.write(f"  因子数量: 30个\n\n")
        f.write("【策略表现】\n")
        f.write(f"  累计收益: {total_ret:.2%}\n")
        f.write(f"  年化收益: {annual_ret:.2%}\n")
        f.write(f"  夏普比率: {sharpe:.4f}\n")
        f.write(f"  最大回撤: {max_dd:.2%}\n")
        f.write(f"  调仓次数: {trade_count}\n")
        f.write(f"  方向准确率(1天): {dir_acc_1d:.2%}\n\n")
        f.write("【与每日调仓对比】\n")
        f.write(f"  每日调仓年化: 8.06%\n")
        f.write(f"  5天调仓年化:  {annual_ret:.2%}\n")
        f.write(f"  差异: {annual_ret - 0.0806:.2%}\n\n")

    print(f"\n结果保存至: {output_dir}/")


def main():
    """主程序"""
    file_path = "factors_WTI_cleaned_v2.csv"
    output_dir = "final_solution_5day"

    df, primary_target, targets, base_cols = load_and_prepare_data(file_path)
    results = rolling_prediction(df, primary_target, targets, base_cols, train_window=756)
    evaluate_and_save(results, output_dir)

    print("\n" + "=" * 60)
    print("5天调仓版生成完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
