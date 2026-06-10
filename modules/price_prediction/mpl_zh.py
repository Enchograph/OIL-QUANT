"""Matplotlib 中文字体初始化（Windows / macOS / Linux）。"""
import os
import matplotlib.pyplot as plt
from matplotlib import font_manager


def setup_chinese_font():
    plt.rcParams["axes.unicode_minus"] = False
    prefer = [
        "Microsoft YaHei",
        "Microsoft YaHei UI",
        "SimHei",
        "PingFang SC",
        "Heiti SC",
        "Noto Sans CJK SC",
        "Noto Sans CJK JP",
        "Source Han Sans SC",
        "STHeiti",
        "Arial Unicode MS",
    ]
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in prefer:
        if name in installed:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            return

    windir = os.environ.get("WINDIR", r"C:\Windows")
    for fn in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "msyhl.ttc"):
        path = os.path.join(windir, "Fonts", fn)
        if not os.path.isfile(path):
            continue
        try:
            font_manager.fontManager.addfont(path)
            fp = font_manager.FontProperties(fname=path)
            plt.rcParams["font.sans-serif"] = [fp.get_name(), "DejaVu Sans"]
            return
        except OSError:
            continue

    noto = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    if os.path.isfile(noto):
        try:
            font_manager.fontManager.addfont(noto)
            fp = font_manager.FontProperties(fname=noto)
            plt.rcParams["font.sans-serif"] = [fp.get_name(), "DejaVu Sans"]
        except OSError:
            pass
