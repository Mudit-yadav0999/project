# Kisan Sathi (working core, v0.1)

## Run on Windows
1. Install Python 3.11+ from python.org (tick "Add to PATH").
2. In PowerShell, inside this folder:
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
3. Open `.env` and set `AI_API_KEY` (needed for crop scanning only).
4. Start: `uvicorn backend.app.main:app --reload`
5. Open http://localhost:8000 (API docs: http://localhost:8000/docs, health: /api/health).

Camera needs `localhost` or https. On a phone, use a tunnel such as ngrok.

## What works
Crop scanner (live camera, camera switch, flashlight, upload, retake, up to 4 photos, vision-model diagnosis, saved to history), history (search, favorite, notes, delete), farms CRUD, task calendar, water calculator (transparent formula), live weather (Open-Meteo, no key), health check.

## Not built yet
AI chat, disease library, mandi prices, government schemes, equipment/waste marketplaces, login, translations, recovery comparison, React/TypeScript/Tailwind port.
