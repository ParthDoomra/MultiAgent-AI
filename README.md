# Multi-Agent Business Assistant

AI-powered multi-agent business decision and negotiation assistant.

## MVP Scope
- **Core Agents**:
  - **Orchestrator Agent**: Task decomposition, agent coordination, workflow execution
  - **Finance Agent**: Cost calculations, margins, break-even forecasting
  - **Market Agent**: Competitor analysis, market sizing, demand trends
  - **Report Agent**: Business decision synthesis, structured recommendations
- **Architecture**:
  - **Backend**: FastAPI (Python 3.12+)
  - **Frontend**: React + Vite (Vanilla CSS design system)
  - **Communication**: REST API endpoints (Foundry / A2A integration deferred to Phase 2)

---

## Project Structure

```
MultiAgent/
├── backend/
│   ├── app/
│   │   ├── api/            # API routers & endpoints for agents
│   │   ├── core/           # Configuration & settings
│   │   ├── services/       # Business logic & agent workflows
│   │   └── main.py         # FastAPI application entry & /health endpoint
│   ├── requirements.txt    # Backend dependencies
│   └── run.py              # Convenience script to start uvicorn
├── frontend/
│   ├── src/
│   │   ├── App.jsx         # Live health monitoring & MVP dashboard
│   │   ├── App.css         # Component styling & glassmorphic layout
│   │   ├── index.css       # Design tokens, typography & base styling
│   │   └── main.jsx        # React root entry
│   ├── package.json
│   └── vite.config.js      # Vite dev server & backend proxy configuration
├── PRD — Multi-Agent Business Assistant.md
└── README.md
```

---

## Getting Started

### 1. Backend Setup

```bash
cd backend
python -m venv .venv

# Activate virtual environment:
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Windows (CMD):
.\.venv\Scripts\activate.bat
# Linux/macOS:
source .venv/bin/activate

# Install dependencies:
pip install -r requirements.txt

# Run backend server:
python run.py
# or: uvicorn app.main:app --reload --port 8000
```

- API Base: `http://localhost:8000`
- Health Endpoint: `http://localhost:8000/health`
- Interactive API Docs (Swagger): `http://localhost:8000/docs`

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

- Web Dashboard: `http://localhost:5173`
- The dashboard pings the backend `/health` endpoint and displays live connectivity, response payload, and agent configuration.
