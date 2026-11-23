#!/usr/bin/env bash
# Build the frontend and start the API + app on http://localhost:8000
set -e
cd "$(dirname "$0")"
python3 -m pip install -q -r backend/requirements.txt
(cd frontend && npm install --silent && npx vite build)
cd backend && python3 -m uvicorn structural.api:app --port 8000
