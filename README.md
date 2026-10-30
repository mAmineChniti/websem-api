# websem-api

FastAPI backend boilerplate for the **Web Semantique** mini-project.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Getting started

### With uv

```bash
cd websem-api
cp .env.example .env
uv sync
uv run fastapi dev app/main.py
```

### Without uv (pip)

```bash
cd websem-api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
fastapi dev app/main.py
```

The API is available at:

- API root: http://localhost:8000/
- Health check: http://localhost:8000/api/health
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project structure

```
websem-api/
├── app/
│   ├── main.py            # FastAPI application factory
│   ├── api/
│   │   ├── router.py      # Main API router
│   │   └── routes/        # Route modules (health, ...)
│   └── core/
│       └── config.py      # Settings loaded from environment
├── tests/                 # Pytest suite
├── .env.example
└── pyproject.toml
```

## Development

```bash
uv run pytest        # run tests
uv run ruff check .  # lint
uv run ruff format . # format
```

Without uv:

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
ruff format .
```

## Configuration

Settings are read from environment variables or a `.env` file (see `.env.example`).
`CORS_ORIGINS` accepts a comma-separated list; the default allows the Next.js
front-end running on `http://localhost:3000`.
