#!/usr/bin/env python3
"""
测试脚本：验证输出列名与原始v2文件的一致性
"""

import pandas as pd
import sys
import os

def test_column_alignment():
    """测试列名对齐"""
    print("=" * 70)
    print("列名对齐测试")
    print("=" * 70)

    # 读取原始v2文件列名
    try:
        v2_df = pd.read_csv('factors_WTI_cleaned_v2.csv', nrows=0)
        v2_columns = set(v2_df.columns)
        print(f"\n✓ 原始v2文件列数: {len(v2_columns)}")
    except Exception as e:
        print(f"\n✗ 无法读取v2文件: {e}")
        return False

    # 检查是否有最新的输出文件
    output_files = [f for f in os.listdir('.') if f.startswith('wti_factors_') and f.endswith('.csv')]

    if not output_files:
        print("\n⚠ 未找到输出文件，仅验证v2文件结构")
        print("\nv2文件前20列:")
        for i, col in enumerate(list(v2_df.columns)[:20]):
            print(f"  {i+1}. {col}")
        return True

    # 读取最新的输出文件
    latest_file = sorted(output_files)[-1]
    try:
        output_df = pd.read_csv(latest_file, nrows=0)
        output_columns = set(output_df.columns)
        print(f"✓ 输出文件列数: {len(output_columns)} ({latest_file})")
    except Exception as e:
        print(f"✗ 无法读取输出文件: {e}")
        return False

    # 对比列名
    print("\n" + "=" * 70)
    print("列名对比结果")
    print("=" * 70)

    # v2中有但输出中没有的列
    missing_in_output = v2_columns - output_columns
    if missing_in_output:
        print(f"\n⚠ v2中有但输出中缺失的列 ({len(missing_in_output)}个):")
        for col in sorted(missing_in_output):
            print(f"  - {col}")
    else:
        print("\n✓ 所有v2列都在输出文件中")

    # 输出中有但v2中没有的列
    extra_in_output = output_columns - v2_columns
    if extra_in_output:
        print(f"\n⚠ 输出中有但v2中没有的列 ({len(extra_in_output)}个):")
        for col in sorted(extra_in_output):
            print(f"  + {col}")
    else:
        print("✓ 输出文件没有额外列")

    # 共同列
    common_columns = v2_columns & output_columns
    print(f"\n✓ 共同列数: {len(common_columns)}")
    print(f"  覆盖率: {len(common_columns)/len(v2_columns)*100:.1f}%")

    # 检查列顺序
    print("\n" + "=" * 70)
    print("列顺序检查 (前15列)")
    print("=" * 70)
    print(f"{'v2文件':<40} {'输出文件':<40}")
    print("-" * 70)

    v2_list = list(v2_df.columns)
    out_list = list(output_df.columns)

    for i in range(min(15, max(len(v2_list), len(out_list)))):
        v2_col = v2_list[i] if i < len(v2_list) else "(无)"
        out_col = out_list[i] if i < len(out_list) else "(无)"
        match = "✓" if v2_col == out_col else "✗"
        print(f"{match} {v2_col:<38} {out_col:<38}")

    return len(missing_in_output) == 0


def test_data_quality():
    """测试数据质量"""
    print("\n" + "=" * 70)
    print("数据质量测试")
    print("=" * 70)

    output_files = [f for f in os.listdir('.') if f.startswith('wti_factors_') and f.endswith('.csv')]
    if not output_files:
        print("⚠ 未找到输出文件，跳过数据质量测试")
        return True

    latest_file = sorted(output_files)[-1]

    try:
        df = pd.read_csv(latest_file)
        print(f"\n✓ 成功读取: {latest_file}")
        print(f"  行数: {len(df)}")
        print(f"  列数: {len(df.columns)}")
        print(f"  日期范围: {df['Date'].min()} ~ {df['Date'].max()}")

        # 检查关键列的数据完整性
        key_columns = ['Price', 'VIX_Price', 'DXY_Price', 'WTI_Close']
        print("\n关键列数据完整性:")
        for col in key_columns:
            if col in df.columns:
                non_null = df[col].notna().sum()
                pct = non_null / len(df) * 100
                status = "✓" if pct > 80 else "⚠"
                print(f"  {status} {col}: {non_null}/{len(df)} ({pct:.1f}%)")
            else:
                print(f"  ✗ {col}: 列不存在")

        return True
    except Exception as e:
        print(f"✗ 数据质量测试失败: {e}")
        return False


if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("WTI因子数据 - 列名对齐与质量测试")
    print("=" * 70)

    alignment_ok = test_column_alignment()
    quality_ok = test_data_quality()

    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    print(f"  列名对齐: {'✓ 通过' if alignment_ok else '✗ 失败'}")
    print(f"  数据质量: {'✓ 通过' if quality_ok else '✗ 失败'}")
    print("=" * 70)

    sys.exit(0 if (alignment_ok and quality_ok) else 1)
