# GPR 数据说明

## 来源与概念

GPR（Geopolitical Risk Index）由 Caldara 与 Iacoviello 构建，通过统计主要报纸中与地缘政治紧张、战争、恐怖主义相关的报道频率来衡量地缘政治风险。该数据包含全球指数与国家分项指数，并提供“历史版（1900 起）”与“近期版（1985 起）”的系列。citeturn0search0turn0search1
GPR 进一步拆分为“威胁（Threats）”与“行动/事件（Acts）”两个子指数，用于刻画不同来源的地缘政治冲击。citeturn0search0

## 文件

- `data_gpr_export.xls`

## 字段含义（按列名约定）

说明：以下字段说明基于官方 GPR 数据的命名习惯与公开说明整理；若需精确口径，请以官方数据说明为准。citeturn0search0turn0search1

- `month`: 月度时间标记（YYYY-MM）。
- `GPR`: 全球 GPR 指数（近期版，基于 10 份报纸，1985 起）。citeturn0search0
- `GPRT`: 全球 GPR Threats（威胁）子指数。citeturn0search0
- `GPRA`: 全球 GPR Acts（行动/事件）子指数。citeturn0search0
- `GPRH`: 全球 GPR 历史版指数（1900 起）。citeturn0search0
- `GPRHT`: 全球历史版 Threats 子指数（推断为历史版 Threats）。citeturn0search0
- `GPRHA`: 全球历史版 Acts 子指数（推断为历史版 Acts）。citeturn0search0
- `SHARE_GPR`: 与 `GPR` 同口径的原始“份额/占比”字段（推断为文章占比）。citeturn0search0
- `SHARE_GPRH`: 与 `GPRH` 同口径的原始“份额/占比”字段（推断为文章占比）。citeturn0search0
- `GPR_NOEW`, `GPRH_NOEW`: 官方关键词筛选的稳健性变体列（推断）。citeturn0search0
- `GPR_AND`, `GPRH_AND`: 官方关键词筛选的稳健性变体列（推断）。citeturn0search0
- `GPR_BASIC`, `GPRH_BASIC`: 官方关键词筛选的稳健性变体列（推断）。citeturn0search0
- `GPRC_XXX`: 国家分项 GPR 指数（近期版），`XXX` 为国家/地区三位代码；计算口径为“满足 GPR 条件且提及该国家/主要城市的文章占比”，体现美媒视角下对该国相关风险的衡量。citeturn0search1
- `GPRHC_XXX`: 国家分项 GPR 指数（历史版），`XXX` 为国家/地区三位代码（推断为历史版对应系列）。citeturn0search1turn0search0

当前文件中出现的 `XXX` 代码包括：
ARG, AUS, BEL, BRA, CAN, CHE, CHL, CHN, COL, DEU, DNK, EGY, ESP, FIN, FRA, GBR, HKG, HUN, IDN, IND, ISR, ITA, JPN, KOR, MEX, MYS, NLD, NOR, PER, PHL, POL, PRT, RUS, SAU, SWE, THA, TUN, TUR, TWN, UKR, USA, VEN, VNM, ZAF.
