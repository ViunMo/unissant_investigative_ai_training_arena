#!/usr/bin/env bash
# Start the backend on :8000 using the project venv (bypasses any shell alias for python).
cd "$(dirname "$0")"
exec .venv/bin/python -m uvicorn app.main:app --reload --port 8000
