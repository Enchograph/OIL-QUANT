# 花旗油价量化分析平台

一个面向企业银行场景的油价风险分析与展示平台，整合市场行情、因子数据、新闻洞察、量化预测与 AI 分析。

## 项目简介

本项目围绕 WTI 原油价格构建数据分析网站，目标是帮助业务团队快速理解油价驱动因子、市场新闻变化与未来风险区间。

## 核心能力

- 全局仪表盘：展示市场行情、关键指标与概览信号
- 因子集页面：展示模型使用的因子表数据
- 市场资讯：抓取新闻并生成摘要、情绪和风险相关分析
- 量化预测：基于既有模型输出未来价格区间与风险提示
- AI 分析：提供企业侧与银行侧两种视角的解释性分析
- 管理台：支持刷新行情、同步因子、同步新闻、运行模型和重生成 AI 分析

## 目录结构

```text
.
├─ frontend/     React 前端
├─ backend/      Flask 后端、SQLite 数据与任务脚本
└─ modules/     子模块脚本与参考实现
```

## 技术栈

- Frontend: React 19, react-scripts
- Backend: Flask 3
- Data: SQLite (`backend/data/platform.sqlite3`)
- Analytics: pandas, scikit-learn, yfinance, akshare, OpenAI-compatible API

## 环境要求

- Node.js 18+
- Python 3.10+
- npm

建议同时准备可访问的 AI 接口与市场数据网络环境。

## 快速开始

### 1. 安装前端依赖

```bash
cd frontend
npm install
```

### 2. 安装后端依赖

Windows PowerShell:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置环境变量

常用变量：

```env
BACKEND_HOST=127.0.0.1
BACKEND_PORT=5001
BACKEND_DEBUG=0
BACKEND_ALLOWED_ORIGIN=*
BACKEND_ADMIN_KEY=
AI_CHAT_API_KEY=
AI_CHAT_BASE_URL=
AI_OPENAI_API_KEY=
AI_OPENAI_BASE_URL=
```

说明：

- 前端默认通过 `frontend/package.json` 代理到 `http://localhost:5001`
- 也可通过 `REACT_APP_API_BASE_URL` 自定义前端 API 前缀
- AI 相关变量至少配置一组可用密钥与 Base URL

### 4. 启动后端

后端通常包含两个进程：

- API 服务：提供前端访问接口
- 调度服务：拉起守护 worker，并按计划执行行情、新闻、因子、模型与 AI 分析任务

#### 4.1 启动 API 服务

Windows PowerShell:

```powershell
cd backend
.venv\Scripts\Activate.ps1
python run.py
```

macOS / Linux:

```bash
cd backend
source .venv/bin/activate
python run.py
```

默认地址：

```text
http://127.0.0.1:5001
```

健康检查：

```text
GET /healthz
```

#### 4.2 启动调度服务

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m backend.orchestrator_service
```

macOS / Linux:

```bash
source .venv/bin/activate
python -m backend.orchestrator_service
```

调度服务会启动并维护以下任务：

- 行情快照守护进程
- 新闻同步守护进程
- 因子日任务
- 模型日任务
- AI 分析日任务

### 5. 启动前端

```bash
cd frontend
npm start
```

默认地址：

```text
http://localhost:3000
```

## 构建与部署

### 前端构建

```bash
cd frontend
npm run build
```

构建产物位于 `frontend/build/`，可部署到任意静态文件服务。

### 后端部署

本仓库当前至少需要两个后端进程：

- API 服务：`python run.py`
- 调度服务：`python -m backend.orchestrator_service`

最小部署方式是在目标机器上安装依赖后分别运行这两个进程。

Windows PowerShell:

```powershell
cd backend
.venv\Scripts\Activate.ps1
python run.py
python -m backend.orchestrator_service
```

macOS / Linux:

```bash
cd backend
source .venv/bin/activate
python run.py
python -m backend.orchestrator_service
```

如需生产化接入进程管理、反向代理或容器化，可在此基础上自行扩展。

## 数据说明

- 后端会在 `backend/data/` 下维护 SQLite 数据库和生成结果
- 因子、新闻、模型与 AI 分析均由后端任务流驱动
- `modules/` 保存了历史算法与参考材料，当前后端会复用其中的部分数据来源和模型资产

## 管理台操作

后端提供管理接口，用于：

- 刷新行情数据
- 刷新因子数据
- 执行模型推演
- 执行 AI 分析
- 同步新闻与导入历史新闻

如设置了 `BACKEND_ADMIN_KEY`，调用管理接口时需要附带认证信息。
