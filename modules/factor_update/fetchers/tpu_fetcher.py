"""
TPU (Trade Policy Uncertainty) 数据获取器
从本地Excel文件读取TPU数据
"""

import pandas as pd
import os


class TPUFetcher:
    """TPU贸易政策不确定性数据获取器"""

    def __init__(self, data_file=None):
        """
        初始化

        Args:
            data_file: TPU数据文件路径，默认查找常见位置
        """
        if data_file:
            self.data_file = data_file
        else:
            # 查找可能的文件位置
            possible_paths = [
                "geopolitical_data/TPU原始数据.xlsx",
                "../geopolitical_data/TPU原始数据.xlsx",
                "TPU原始数据.xlsx",
            ]
            self.data_file = None
            for path in possible_paths:
                if os.path.exists(path):
                    self.data_file = path
                    break

    def fetch(self, start_date=None, end_date=None):
        """
        获取TPU数据

        Args:
            start_date: 开始日期 (可选)
            end_date: 结束日期 (可选)

        Returns:
            pd.DataFrame: TPU数据
        """
        if not self.data_file or not os.path.exists(self.data_file):
            print("⚠ TPU数据文件不存在")
            return pd.DataFrame()

        try:
            df = pd.read_excel(self.data_file)

            # 标准化列名
            if 'date' in df.columns:
                df['Date'] = pd.to_datetime(df['date'])
            elif 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
            else:
                # 假设第一列是日期
                df.columns = ['Date'] + list(df.columns[1:])
                df['Date'] = pd.to_datetime(df['Date'])

            df = df.set_index('Date')

            # 标准化TPU列名
            column_mapping = {
                'TPU': 'TPUD_index',
                'TPU_MA7': 'TPUD_index_MA7',
                'TPU_MA30': 'TPUD_index_MA30',
                'articles': 'NUMBER_ARTICLES',
                'tpu_articles': 'TPUD_ARTICLES',
            }

            for old_col, new_col in column_mapping.items():
                if old_col in df.columns and new_col not in df.columns:
                    df = df.rename(columns={old_col: new_col})

            # 过滤日期范围
            if start_date:
                df = df[df.index >= start_date]
            if end_date:
                df = df[df.index <= end_date]

            print(f"✓ TPU数据: {len(df)} 行 x {len(df.columns)} 列")
            return df

        except Exception as e:
            print(f"✗ TPU数据读取失败: {e}")
            return pd.DataFrame()


if __name__ == '__main__':
    fetcher = TPUFetcher()
    df = fetcher.fetch()
    if not df.empty:
        print(df.head())
