# Citi Oil Platform

An oil-price intelligence platform for corporate banking scenarios, combining market data, factor analytics, news insights, quantitative forecasting, and AI-generated analysis.

## Overview

This project is a web platform built around WTI crude oil analysis. It helps teams understand price drivers, market-moving news, and short-term risk signals.

## Core Features

- Dashboard: market tickers, summary indicators, and overview signals
- Factors: tabular factor data used by the prediction pipeline
- News: ingests articles and generates summaries, sentiment, and risk-related analytics
- Prediction: produces forecast ranges and risk signals from the existing model pipeline
- AI advisory: generates both corporate-view and bank-view narrative analysis
- Admin console: supports market sync, factor sync, news sync, model runs, and AI regeneration

## Repository Layout

```text
.
├─ frontend/     React frontend
├─ backend/      Flask backend, SQLite data, and worker scripts
└─ modules/     Submodule scripts and reference materials
```

## Tech Stack

- Frontend: React 19, react-scripts
- Backend: Flask 3
- Data: SQLite (`backend/data/platform.sqlite3`)
- Analytics: pandas, scikit-learn, yfinance, akshare, OpenAI-compatible API

## Requirements

- Node.js 18+
- Python 3.10+
- npm

An accessible AI API endpoint and stable outbound network access are recommended.

## Quick Start

### 1. Install Frontend Dependencies

```bash
cd frontend
npm install
```

### 2. Install Backend Dependencies

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

### 3. Configure Environment Variables

Common variables:

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

Notes:

- The frontend proxies to `http://localhost:5001` by default through `frontend/package.json`
- You can override the frontend API prefix with `REACT_APP_API_BASE_URL`
- Configure at least one valid AI key and base URL pair for AI-related features

### 4. Run Backend

The backend normally consists of two processes:

- API service: serves requests from the frontend
- Orchestrator service: supervises daemon workers and scheduled jobs for market, news, factors, models, and AI analysis

#### 4.1 Run the API Service

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

Default backend URL:

```text
http://127.0.0.1:5001
```

Health check:

```text
GET /healthz
```

#### 4.2 Run the Orchestrator Service

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

The orchestrator is responsible for:

- Market snapshot daemon
- News sync daemon
- Daily factor job
- Daily model job
- Daily AI analysis job

### 5. Run Frontend

```bash
cd frontend
npm start
```

Default frontend URL:

```text
http://localhost:3000
```

## Build & Deploy

### Frontend Build

```bash
cd frontend
npm run build
```

The production bundle is generated in `frontend/build/` and can be served by any static web server.

### Backend Deployment

This repository currently needs at least two backend processes:

- API service: `python run.py`
- Orchestrator service: `python -m backend.orchestrator_service`

The minimum deployment path is to install dependencies and run both processes on the target machine.

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python run.py
python -m backend.orchestrator_service
```

macOS / Linux:

```bash
source .venv/bin/activate
python run.py
python -m backend.orchestrator_service
```

If you need process managers, reverse proxies, or containers for production, extend from this baseline setup.

## Data Notes

- The backend stores SQLite data and generated outputs under `backend/data/`
- Factors, news, model runs, and AI analysis are driven by backend task pipelines
- `modules/` contains legacy algorithms and reference assets reused by the current backend

## Admin Operations

The admin APIs support:

- Syncing market data
- Syncing factor data
- Running the prediction pipeline
- Regenerating AI advisory output
- Syncing news and importing historical news

If `BACKEND_ADMIN_KEY` is configured, admin requests must include valid authentication headers.
