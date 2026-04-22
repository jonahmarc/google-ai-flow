import base64
import os
import sys
import json
import asyncio
import subprocess

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Google Flow Image Generator")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    session_exists = os.path.exists("session.json")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"has_session": session_exists}
    )


@app.post("/generate")
async def generate(
    prompt: str = Form(...),
    aspect_ratio: str = Form("landscape"),
    image: UploadFile = File(None)
):
    if not os.path.exists("session.json"):
        return JSONResponse(status_code=401, content={
            "error": "No session found. Run save_session.py first."
        })

    with open("session.json") as f:
        session_data = json.load(f)

    try:
        image_b64 = None
        mime_type = "image/jpeg"

        if image and image.filename:
            image_bytes = await image.read()
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            mime_type = image.content_type or "image/jpeg"

        image_url = await generate_image(
            prompt, session_data, aspect_ratio, image_b64, mime_type
        )
        return {"success": True, "image_url": image_url}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


async def generate_image(
    prompt: str,
    session_data: dict,
    aspect_ratio: str = "landscape",
    image_base64: str = None,
    mime_type: str = "image/jpeg"
) -> str:
    params = {
        "prompt": prompt,
        "session_cookies": session_data.get("cookies", session_data),
        "bearer_token": session_data.get("bearer_token", ""),
        "aspect_ratio": aspect_ratio,
        "image_base64": image_base64,
        "mime_type": mime_type,
    }

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            [sys.executable, "runner.py", json.dumps(params)],
            capture_output=True,
            text=True
        )
    )

    # Forward runner.py logs to uvicorn output
    if result.stdout:
        print(result.stdout, flush=True)
    if result.stderr:
        print("[RUNNER STDERR]", result.stderr, flush=True)

    if result.returncode != 0:
        raise Exception(result.stderr)

    # runner.py prints debug logs + final JSON on the last line
    # Scan lines in reverse to find the last valid JSON with image_url
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    for line in reversed(lines):
        try:
            data = json.loads(line)
            if isinstance(data, dict) and "image_url" in data:
                return data["image_url"]
        except Exception:
            continue

    raise Exception(f"Could not find image_url in runner output:\n{result.stdout}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)