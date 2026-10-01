# PocketSmart AI: Smart Budget & Recommendation Assistant

A FastAPI + Gemini web app with three budget planners:

| Planner | What it does |
|---|---|
| **Home interior** | Splits a budget across lights, fans, furniture, dining tables and decor, with priced items and store links (Amazon, Flipkart, IKEA, Pepperfry). |
| **Party** | Splits a budget across venue, catering, decoration, entertainment and a contingency buffer (Swiggy, Zomato, BookMyShow, OYO, Google Maps ...). |
| **Jewelry** | Recommends pieces for an occasion and style. Optionally reads an outfit photo (Gemini vision) to match colours and formality. |

Also included: registration and login (bcrypt + JWT cookie), sessions, saved history, print view, and offline tests.

**Works without an API key.** With no `GEMINI_API_KEY` the app runs in *demo mode* using a built-in planner, so you can test everything first. The same built-in planner is the safety net if the AI is down or returns unusable output. Every AI answer is validated and scaled down if it goes over budget.

---

## 1. Folder layout

```
pocketsmart-ai/
├── main.py              FastAPI app: pages, auth, sessions, planner + history APIs
├── gemini_utils.py      Prompts, Gemini calls, JSON validation, fallbacks, store links
├── models.py            Pydantic input schemas
├── auth.py              Password hashing, JWT, user store
├── storage.py           JSON-file persistence (users, history)
├── config.py            Loads .env settings
├── requirements.txt
├── .env / .env.example  Settings (put your Gemini key in .env)
├── templates/           base, index, login, register, dashboard, home/party/jewelry planners, history
├── static/              styles.css, app.js, uploads/ (outfit photos)
├── data/                users.json + history.json are created here
└── tests/test_app.py    End-to-end tests (run offline)
```

## 2. Set up in VS Code (Windows, macOS, Linux)

**Prerequisite:** Python 3.10 or newer (`python --version`). Install the VS Code *Python* extension.

1. Unzip the project and open it: **File → Open Folder… → `pocketsmart-ai`**.
2. Open a terminal: **Terminal → New Terminal**.
3. Create and activate a virtual environment.

   Windows (PowerShell):
   ```powershell
   python -m venv venv
   venv\Scripts\Activate.ps1
   ```
   If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use Command Prompt: `venv\Scripts\activate.bat`.

   macOS / Linux:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
5. Pick the interpreter: press `Ctrl+Shift+P` → **Python: Select Interpreter** → choose the one inside `venv` (on macOS/Linux this overrides the Windows path preset in `.vscode/settings.json`).

## 3. Add your Gemini API key (optional but recommended)

1. Go to <https://aistudio.google.com/app/apikey> and click **Create API key**.
2. Open `.env` in VS Code and paste it: `GEMINI_API_KEY=your_key_here`
3. Save. Never share or commit this file (`.gitignore` already excludes it).

The default model is `gemini-2.5-flash`. The original project brief names Gemini 1.5 Flash, but Google has retired the 1.5 family, so the app uses a current model. To change it, edit `GEMINI_MODEL` (and `GEMINI_FALLBACK_MODELS`) in `.env`. If the first model fails, the app tries the next ones automatically. Check <https://ai.google.dev/gemini-api/docs/models> for current names.

## 4. Run

```bash
python main.py
```
Open <http://127.0.0.1:8000>. (Alternatives: `uvicorn main:app --reload`, or press **F5** in VS Code to run with the debugger.)
Interactive API docs are at <http://127.0.0.1:8000/docs>. The top bar of every result shows whether it came from **AI plan** or the **Built-in planner**.

## 5. Try it

1. Click **Create account**, register, then sign in.
2. **Home**: keep the defaults and press *Generate plan*.
3. **Party**: try 20 guests, Banquet hall, all needs ticked.
4. **Jewelry**: choose *Wedding* and upload any outfit photo (JPG/PNG/WEBP, ≤ 5 MB).
5. Open **History** and press *View details* on a past plan.

## 6. Run the automated tests

```bash
pytest -v
```
They create a throwaway account and data folder, run offline, and cover registration, login, redirects, all three planners (including an image upload and a fake-image rejection), validation errors, history, sessions and logout.

## 7. API summary

| Method & path | Purpose |
|---|---|
| `GET /` `/login` `/register` | Public pages |
| `POST /register` | Create account (JSON) |
| `POST /token` | Log in (form fields `username`, `password`), sets an HTTP-only cookie |
| `POST /logout` | Invalidate the token, redirect to `/login` |
| `GET /dashboard` `/home-planner` `/party-planner` `/jewelry-planner` `/history` | Protected pages |
| `POST /generate-home` | JSON body → home plan |
| `POST /generate-party` | JSON body → party plan |
| `POST /generate-jewelry` | multipart form (`total_budget`, `occasion`, `preferences`, `image`) → picks |
| `GET /history-data` | List of saved plans |
| `GET /recommendation-details/{id}` | One full saved plan |
| `GET /session-info` · `POST /session-data` | Read / update session data |
| `GET /health` | Status + whether AI is enabled |

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Activate the venv, then `pip install -r requirements.txt`. |
| Results say *Built-in planner* even with a key | Check `GEMINI_API_KEY` in `.env`, restart the server, and read the terminal log for the Gemini error (bad key, quota, or unknown model name). |
| Port 8000 busy | Set `PORT=8001` in `.env`, and add that origin to `CORS_ORIGINS`. |
| Logged out unexpectedly | Tokens last 60 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`). Sign in again. |
| Reset all users and history | Stop the server and delete `data/users.json` and `data/history.json`. |
| Store links show "no results" | Links are plain search URLs built from the item name; stores may change their URL format. Edit `PLATFORMS` in `gemini_utils.py`. |

## 9. Production notes

Set a long random `SECRET_KEY`, serve over HTTPS and add `secure=True` to the cookie in `main.py`, restrict `CORS_ORIGINS`, and replace the JSON files in `storage.py` with a real database if you expect many users. Prices are AI estimates, not live store prices.
