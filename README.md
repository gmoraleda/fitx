# FitX Course Schedule to ICS (Local, Dockerized)

A lightweight local service that fetches FitX gym course schedules and publishes a subscribable iCalendar (ICS) feed you can add to your iPhone Calendar. Runs entirely on your Raspberry Pi (arm64) with Docker — no cloud dependencies.

## Features
- FastAPI + Uvicorn server serving `text/calendar` at `/calendar.ics`
- Background refresh loop with persisted cache in `/data`
- Robust parsing of JSON or HTML-embedded JSON using BeautifulSoup
- Manual ICS generation (RFC 5545) including `VTIMEZONE` for Europe/Berlin
- Optional cookie support (never logged), optional refresh token for `/refresh`

## Endpoints
- `GET /calendar.ics` → returns ICS feed
- `GET /health` → returns `OK` (200)
- `POST /refresh` → triggers immediate refresh (requires `X-Refresh-Token` header if `REFRESH_TOKEN` is set)

## Requirements
- Raspberry Pi OS (Debian) on arm64
- Docker and Docker Compose

## Quick Start
1) Install Docker and Compose on Raspberry Pi (arm64). For Raspberry Pi OS, follow official Docker docs or convenience script.

2) Clone or copy this repository onto your Pi.

3) Create your environment file:
   - Copy `.env.example` to `.env`
   - Adjust values as needed. Defaults work for most cases.
   - If you have a valid FitX cookie, set `FITX_COOKIE` (optional). Do not share it and note cookies expire.

4) Start the service:
   - `docker compose up -d`

5) Verify health:
   - `curl http://<pi-ip>:<PORT>/health` → should return `OK`

6) Subscribe on iPhone:
   - Open: Settings → Calendar → Accounts → Add Account → Other → Add Subscribed Calendar
   - URL: `http://<pi-ip>:<PORT>/calendar.ics`

## Configuration (Environment Variables)
- `FITX_COURSE_ID` (default: `53`)
- `PORT` (default: `8787`) – host port; container always listens on 8787
- `REFRESH_INTERVAL_SECONDS` (default: `900`)
- `FITX_COOKIE` (optional; NEVER logged)
- `REFRESH_TOKEN` (optional; protects `/refresh`)
- `TZ` (default: `Europe/Berlin`)
- `FITX_EXCLUDE_KEYWORDS` (default: `booty x,xamba,x step,fatburn x`) – comma-separated list of case-insensitive title substrings to filter out from the calendar
 - `CLOUDFLARED_TOKEN` (optional) – Cloudflare Tunnel token used by the `cloudflared` sidecar.

## Exposing via Cloudflare Tunnel
This repo includes an optional `cloudflared` sidecar in `docker-compose.yml`.

Two modes are supported:
- Quick Tunnel (no domain needed): default when `CLOUDFLARED_TOKEN` is not set. Start with `docker compose up -d`, then run `docker compose logs -f cloudflared` and copy the `https://<random>.trycloudflare.com` URL. Use that URL for `/calendar.ics` and `/health`.
- Named Tunnel (requires a Cloudflare-managed domain): set up a Tunnel + Public Hostname in the Cloudflare dashboard pointing to `http://localhost:8787` (or `http://fitx-calendar:8787`), set `CLOUDFLARED_TOKEN=...` in `.env`, then `docker compose up -d`. Use your chosen hostname.

## Data Persistence
- The container uses `/data` for persistence and stores:
  - `/data/cache.ics` – last known good calendar
  - `/data/cache.json` – normalized parsed events
- In `docker-compose.yml`, this is mounted as a named volume: `fitx_data:/data`.
- On startup, the server loads any existing cache immediately, then refreshes in the background.

## Refresh Behavior
- On startup: loads cache (if present), starts HTTP server, and runs a refresh.
- Background loop repeats every `REFRESH_INTERVAL_SECONDS`.
- On success: updates disk and in-memory cache atomically.
- On failure: logs error and keeps serving last known good ICS.

## Troubleshooting
- Cookie expired: If FitX requires authentication, set a fresh `FITX_COOKIE` in `.env`.
- Parsing fails: Logs (DEBUG) indicate keys searched and counts. The service continues serving the last good cache.
- Stale cache: Trigger a manual refresh via `POST /refresh`. If `REFRESH_TOKEN` is set, include header `X-Refresh-Token: <token>`.
- Connectivity: Ensure your Raspberry Pi can reach `https://www.fitx.de` and your iPhone can reach the Pi over LAN.

## Development Notes
- Stack: Python 3.11, FastAPI, Uvicorn, httpx, beautifulsoup4.
- Manual ICS generation; no heavy calendar libraries.
- Binds to `0.0.0.0` inside the container so LAN devices can reach it.
