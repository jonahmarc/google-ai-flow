# Google Flow Image Generator

A reverse-engineered API wrapper for Google Flow's image generation, built with FastAPI and Playwright.

---

## Requirements

- Python 3.11+
- Google Chrome installed
- A Google account with access to [Google Flow](https://labs.google/fx/tools/flow)

---

## Installation

**1. Clone the repo and create a virtual environment**

```bash
python -m venv venv
```

**2. Activate the virtual environment**

```bash
# Windows (Git Bash)
source venv/Scripts/activate

# Windows (CMD)
venv\Scripts\activate.bat

# macOS / Linux
source venv/bin/activate
```

**3. Install dependencies**

```bash
pip install fastapi uvicorn playwright python-dotenv httpx python-multipart
playwright install chromium
```

---

## Project Structure

```
google-ai-flow/
├── main.py              # FastAPI app
├── runner.py            # Playwright subprocess — handles browser automation
├── save_session.py      # One-time script to save your Google session
├── session.json         # Auto-generated after running save_session.py
└── templates/
    └── index.html       # Web UI
```

---

## Setup (First Time Only)

### Step 1 — Launch Chrome with remote debugging

Google Flow requires a real Chrome session with reCAPTCHA. You need to launch Chrome with remote debugging enabled and log in once.

Open **CMD** (not Git Bash) and run:

```cmd
taskkill /F /IM chrome.exe
```

Then launch Chrome with a dedicated debug profile:

```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\chrome-cdp-profile
```

> This opens a separate Chrome window using a fresh profile at `C:\chrome-cdp-profile`.
> Do **not** close this window — keep it running in the background whenever you use the app.

### Step 2 — Log in to Google

In the Chrome window that opened:

1. Go to [https://accounts.google.com](https://accounts.google.com)
2. Log in with the Google account that has access to Flow
3. Go to [https://labs.google/fx/tools/flow](https://labs.google/fx/tools/flow) and confirm you can see the editor

You only need to do this once. The profile saves your session permanently.

### Step 3 — Save your session

Run the session saver script to capture your cookies and bearer token:

```bash
python save_session.py
```

This will save a `session.json` file in your project folder.

---

## Running the App

### Step 1 — Make sure the debug Chrome is running

Every time you restart your machine, relaunch Chrome with the debug flag before starting the app:

```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\chrome-cdp-profile
```

Verify it's running by opening this URL in any browser:

```
http://127.0.0.1:9222/json/version
```

You should see a JSON response with Chrome version info.

### Step 2 — Start the FastAPI server

```bash
python main.py
```

The server will start at [http://localhost:8000](http://localhost:8000).

### Step 3 — Generate an image

Open [http://localhost:8000](http://localhost:8000) in your browser, type a prompt, select an aspect ratio, and click **Generate**.

Generation typically takes 20–40 seconds.

---

## API Usage

You can also call the API directly:

```bash
curl -X POST http://localhost:8000/generate \
  -F "prompt=A futuristic city at sunset" \
  -F "aspect_ratio=landscape"
```

**Response:**

```json
{
  "success": true,
  "image_url": "https://flow-content.google/image/..."
}
```

**Aspect ratio options:** `landscape`, `portrait`, `square`

---

## Troubleshooting

**`Could not connect to Chrome`**
Chrome is not running with the debug flag. Follow Step 1 under Running the App above.

**`reCAPTCHA evaluation failed`**
Your session has expired or Chrome is not running with the correct profile. Re-launch Chrome with `--user-data-dir=C:\chrome-cdp-profile` and try again.

**`No session found`**
Run `python save_session.py` to generate `session.json`.

**`Generate button not found`**
The Flow UI may have changed. Check `debug_screenshot.png` in the project folder for a screenshot of what the browser sees.

**Port 8000 already in use**
```bash
# Find and kill the process using port 8000
netstat -ano | findstr :8000
taskkill /F /PID <PID>
```

---

## Notes

- The debug Chrome window must stay open while the app is running
- You only need to log in once — the profile remembers your session
- Bearer tokens expire periodically; re-run `save_session.py` if you get auth errors
- Generated image URLs are temporary and expire after a few hours

---

## How It Works: Reverse Engineering Google Flow's API

### How the API Was Reverse Engineered

The Google Flow image generation platform (`labs.google/fx/tools/flow`) has no public API. To understand how it works, Chrome DevTools' **Network tab** was used to capture live traffic while submitting a prompt through the UI. This revealed a `POST` request to:

```
https://aisandbox-pa.googleapis.com/v1/projects/{projectId}/flowMedia:batchGenerateImages
```

The full request headers, payload structure, and response format were logged in [`request_response-details.json`](request_response-details.json). Key observations from inspection:
- The image model is internally called `NARWHAL`, and the tool context is `PINHOLE`
- The request requires a live `Authorization: Bearer` token and a `recaptchaContext.token` — both generated dynamically by the browser session
- Responses may be prefixed with an XSSI guard string (`)]}'\n`) that must be stripped before JSON parsing

### Tools Used

- **Chrome DevTools** — network inspection to capture the request/response contract
- **Playwright (Python)** — browser automation to drive the Flow UI and intercept outbound requests
- **Chrome Remote Debugging Protocol (CDP)** — connects Playwright to an existing Chrome session (port 9222) without launching a new browser, which preserves the user's authenticated session

### Limitations and Challenges

**Authentication (the main challenge):** The API cannot be called directly. It requires a `Bearer` token and a `reCAPTCHA` token that are generated dynamically by the browser. Replicating these externally is not feasible. The approach works around this by piggybacking on an already-authenticated browser session — Playwright connects to Chrome via CDP and intercepts the request *as the browser is about to send it*, swapping in the real prompt while preserving the auth tokens the browser generated.

**Required setup:** Before running the script, the user must:
1. Launch Chrome with remote debugging enabled:
   ```
   chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\chrome-cdp-profile
   ```
2. Manually log into their Google account in that browser window

After that, the script can reuse the authenticated session for all subsequent requests without prompting for credentials again. This does mean the tool only works on the machine where the user is already logged in, and the session will eventually expire.

**Other limitations:**
- The `reCAPTCHA` token is consumed per-request and re-generated by the browser on each submission, so the script triggers an actual UI interaction (typing a dummy prompt, clicking send) on every call
- The approach relies on UI element selectors (Material icons like `add_2`, `arrow_forward`, Slate editor attributes) that could break if Google updates the Flow frontend