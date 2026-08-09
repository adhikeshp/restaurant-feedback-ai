# Table Service — Restaurant Feedback Prioritization

A React, FastAPI, PostgreSQL application for turning customer feedback into a staff-prioritized queue.

## Run

1. Copy `.env.example` to `.env` and set `JWT_SECRET`. Add `LLM_API_KEY` to enable live analysis (an OpenAI-compatible Chat Completions endpoint is expected; set `LLM_API_BASE` if needed).
2. Run `docker compose up --build`.
3. Open `http://localhost:5173`.

The backend creates the schema, indexes, demo manager account, and representative feedback records on startup. For a production deployment, use Alembic migrations before startup.

## Demo credentials

Login ID: `manager`  
Password: `Manager@123`

If no LLM credentials are configured, the app saves submissions and uses a clearly bounded local classifier so the end-to-end demo remains functional. Configuring an LLM makes the backend use strict JSON analysis; safety terms are always escalated to CRITICAL server-side.
