"""
配置文件
"""
import os
from pathlib import Path

# 数据文件路径
DATA_FILE = "factors_WTI_cleaned_v2.csv"
RAW_DIR = "./raw_data"

# API Keys
EIA_API_KEY = os.getenv("EIA_API_KEY", "yQOOaSWdrykVEtH8zfkIItOFLuyHoyc6HfKebVcx").strip()
FRED_API_KEY = os.getenv("FRED_API_KEY", "").strip()

# 日期设置
START_DATE = "2016-01-01"

# 创建目录
def init_dirs():
    Path(RAW_DIR).mkdir(exist_ok=True)
    for subdir in ["market", "eia", "cftc", "gdelt", "gpr", "china", "macro"]:
        Path(f"{RAW_DIR}/{subdir}").mkdir(exist_ok=True)
