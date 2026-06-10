"""
GDELT数据获取器
获取全球事件、语言和语调数据库的地缘政治事件数据
基于现有的download.py和process.py重构
"""
import pandas as pd
import os
import requests
import zipfile
import time
import gc
from datetime import datetime, timedelta
from pathlib import Path
from .base_fetcher import BaseFetcher


class GDELTFetcher(BaseFetcher):
    """
    获取GDELT地缘政治事件数据:
    - total_events: 总事件数
    - conflict_count: 冲突事件数
    - conflict_intensity_mean: 冲突强度均值
    - conflict_intensity_sum: 冲突强度总和
    - mentions_mean: 提及数均值
    - mentions_sum: 提及数总和
    - tone_mean: 语调均值
    """

    BASE_URL = "http://data.gdeltproject.org/events"

    # GDELT列名定义
    COLUMNS = [
        "GlobalEventID", "SQLDATE", "MonthYear", "Year", "FractionDate",
        "Actor1Code", "Actor1Name", "Actor1CountryCode", "Actor1KnownGroupCode", "Actor1EthnicCode",
        "Actor1Religion1Code", "Actor1Religion2Code", "Actor1Type1Code", "Actor1Type2Code", "Actor1Type3Code",
        "Actor2Code", "Actor2Name", "Actor2CountryCode", "Actor2KnownGroupCode", "Actor2EthnicCode",
        "Actor2Religion1Code", "Actor2Religion2Code", "Actor2Type1Code", "Actor2Type2Code", "Actor2Type3Code",
        "IsRootEvent", "EventCode", "EventBaseCode", "EventRootCode", "QuadClass",
        "GoldsteinScale", "NumMentions", "NumSources", "NumArticles", "AvgTone",
        "Actor1Geo_Type", "Actor1Geo_FullName", "Actor1Geo_CountryCode", "Actor1Geo_ADM1Code", "Actor1Geo_Lat", "Actor1Geo_Long", "Actor1Geo_FeatureID",
        "Actor2Geo_Type", "Actor2Geo_FullName", "Actor2Geo_CountryCode", "Actor2Geo_ADM1Code", "Actor2Geo_Lat", "Actor2Geo_Long", "Actor2Geo_FeatureID",
        "ActionGeo_Type", "ActionGeo_FullName", "ActionGeo_CountryCode", "ActionGeo_ADM1Code", "ActionGeo_Lat", "ActionGeo_Long", "ActionGeo_FeatureID",
        "DATEADDED", "SOURCEURL"
    ]

    def __init__(self):
        super().__init__("gdelt")
        self.temp_dir = self.raw_dir / "temp"
        self.temp_dir.mkdir(exist_ok=True)

    def _download_file(self, date_str: str) -> bool:
        """下载单日数据文件"""
        zip_name = f"{date_str}.export.CSV.zip"
        zip_path = self.temp_dir / zip_name
        url = f"{self.BASE_URL}/{zip_name}"

        # 检查是否已存在
        if zip_path.exists():
            return True

        try:
            with requests.get(url, stream=True, timeout=60) as r:
                if r.status_code == 200:
                    with open(zip_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    return True
                else:
                    self.logger.warning(f"下载失败 {zip_name}: HTTP {r.status_code}")
                    return False
        except Exception as e:
            self.logger.error(f"下载异常 {zip_name}: {e}")
            return False

    def _process_file(self, date_str: str) -> dict:
        """处理单日数据文件"""
        zip_name = f"{date_str}.export.CSV.zip"
        zip_path = self.temp_dir / zip_name
        csv_name = f"{date_str}.export.CSV"
        csv_path = self.temp_dir / csv_name

        if not zip_path.exists():
            return None

        try:
            # 解压
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(self.temp_dir)

            if not csv_path.exists():
                return None

            # 读取CSV
            df = pd.read_csv(
                csv_path,
                sep="\t",
                header=None,
                dtype=str,
                low_memory=False
            )

            # 检查列数
            if df.shape[1] != 58:
                self.logger.warning(f"{date_str}: 列数异常 ({df.shape[1]})")
                return None

            df.columns = self.COLUMNS

            # 转换为数值
            df["QuadClass"] = pd.to_numeric(df["QuadClass"], errors="coerce")
            df["GoldsteinScale"] = pd.to_numeric(df["GoldsteinScale"], errors="coerce")
            df["NumMentions"] = pd.to_numeric(df["NumMentions"], errors="coerce")
            df["AvgTone"] = pd.to_numeric(df["AvgTone"], errors="coerce")

            # 统计指标
            total_events = len(df)
            conflict_df = df[df["QuadClass"].isin([3, 4])]

            result = {
                "date": date_str,
                "total_events": total_events,
                "conflict_count": len(conflict_df),
                "conflict_intensity_mean": conflict_df["GoldsteinScale"].mean(),
                "conflict_intensity_sum": conflict_df["GoldsteinScale"].sum(),
                "mentions_mean": df["NumMentions"].mean(),
                "mentions_sum": df["NumMentions"].sum(),
                "tone_mean": df["AvgTone"].mean()
            }

            # 清理
            del df
            del conflict_df
            gc.collect()

            # 删除解压后的CSV
            try:
                csv_path.unlink()
            except:
                pass

            return result

        except Exception as e:
            self.logger.error(f"处理失败 {date_str}: {e}")
            return None

    def fetch(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取GDELT数据"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        results = []
        current = start

        while current <= end:
            date_str = current.strftime("%Y%m%d")

            # 下载并处理
            if self._download_file(date_str):
                result = self._process_file(date_str)
                if result:
                    results.append(result)
                    self.logger.info(f"{date_str}: 处理完成")
            else:
                self.logger.warning(f"{date_str}: 下载失败，跳过")

            current += timedelta(days=1)

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        df = df.sort_index()

        return df

    def cleanup(self):
        """清理临时文件"""
        try:
            for f in self.temp_dir.glob("*"):
                f.unlink()
            self.logger.info("临时文件已清理")
        except Exception as e:
            self.logger.warning(f"清理临时文件失败: {e}")


if __name__ == "__main__":
    fetcher = GDELTFetcher()
    # 只获取最近7天的数据作为测试
    end = datetime.now()
    start = end - timedelta(days=7)
    df = fetcher.fetch(start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
    print(df)
    print(f"\n共获取 {len(df)} 天数据")
