import sys
import json
import uuid
import time
import base64
import tempfile
import os
from playwright.sync_api import sync_playwright


def parse_response_text(text):
    """
    Google sometimes returns null\n{...} or )]}'\n{...}
    Strip XSSI prefix and find the last valid JSON object in the response.
    """
    if text.startswith(")]}'"):
        text = text.split("\n", 1)[1]

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    for line in reversed(lines):
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    raise Exception(f"Could not parse any JSON object from response: {text[:500]}")


def main():
    params = json.loads(sys.stdin.read())

    prompt = params["prompt"]
    aspect_ratio = params.get("aspect_ratio", "landscape")
    image_base64 = params.get("image_base64")
    mime_type = params.get("mime_type", "image/jpeg")

    PROJECT_ID = "0c5ebc9f-bc1f-4159-b613-6328056b8602"

    ASPECT_RATIOS = {
        "landscape": "IMAGE_ASPECT_RATIO_LANDSCAPE",
        "portrait":  "IMAGE_ASPECT_RATIO_PORTRAIT",
        "square":    "IMAGE_ASPECT_RATIO_SQUARE",
    }

    def handle_route(route):
        try:
            original = json.loads(route.request.post_data)
        except Exception:
            route.continue_()
            return

        recaptcha_context = original.get("clientContext", {}).get("recaptchaContext", {})
        session_id = original.get("clientContext", {}).get("sessionId", "")
        batch_id = original.get("mediaGenerationContext", {}).get("batchId", str(uuid.uuid4()))

        # When image was uploaded via UI, Flow's own request already has the
        # server-assigned reference UUID in imageInputs — preserve it as-is.
        # Without an image, send an empty list.
        if image_base64:
            original_requests = original.get("requests", [])
            image_inputs = original_requests[0].get("imageInputs", []) if original_requests else []
            print(f"[ROUTE] Preserving imageInputs from original request: {image_inputs}", flush=True)
        else:
            image_inputs = []

        client_context = {
            "recaptchaContext": recaptcha_context,
            "projectId": PROJECT_ID,
            "tool": "PINHOLE",
            "sessionId": session_id
        }

        our_payload = {
            "clientContext": client_context,
            "mediaGenerationContext": {"batchId": batch_id},
            "useNewMedia": True,
            "requests": [
                {
                    "clientContext": client_context,
                    "imageModelName": "NARWHAL",
                    "imageAspectRatio": ASPECT_RATIOS.get(aspect_ratio, "IMAGE_ASPECT_RATIO_LANDSCAPE"),
                    "structuredPrompt": {
                        "parts": [{"text": prompt}]
                    },
                    "seed": int(time.time()) % 999999,
                    "imageInputs": image_inputs
                }
            ]
        }

        print("[ROUTE] Swapping payload with our prompt", flush=True)
        route.continue_(post_data=json.dumps(our_payload))

    # Decode and save image to a temp file so Playwright's file chooser can use it
    tmp_path = None
    if image_base64:
        ext_map = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
        ext = ext_map.get(mime_type, ".jpg")
        img_bytes = base64.b64decode(image_base64)
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name
        print(f"[IMG] Saved temp image: {tmp_path}", flush=True)

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            except Exception as e:
                raise Exception(
                    "Could not connect to Chrome. Make sure Chrome is running with:\n"
                    "chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\chrome-cdp-profile\n"
                    f"Original error: {e}"
                )

            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = browser.new_context()

            page = context.new_page()
            page.route("**batchGenerateImages**", handle_route)

            print("[1] Navigating to project...", flush=True)
            page.goto(
                f"https://labs.google/fx/tools/flow/project/{PROJECT_ID}",
                wait_until="domcontentloaded",
                timeout=60000
            )
            page.wait_for_timeout(4000)

            # Dismiss any popup
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)

            # Upload reference image via the Flow UI if provided
            if tmp_path:
                print("[2] Attaching reference image via UI...", flush=True)

                # Register the file chooser handler up front so it fires whenever
                # the native dialog would appear — more reliable than expect_file_chooser()
                # with a CDP-connected browser.
                def on_file_chooser(fc):
                    print("[2] File chooser intercepted, setting file...", flush=True)
                    fc.set_files(tmp_path)

                page.on("filechooser", on_file_chooser)

                # Click the attach button — identified by the 'add_2' material icon
                # (not 'arrow_forward' which is the send button)
                attach_clicked = page.evaluate("""
                    () => {
                        const buttons = Array.from(document.querySelectorAll('button'));
                        const btn = buttons.find(b => {
                            const icon = b.querySelector('i');
                            return icon && icon.innerText.trim() === 'add_2';
                        });
                        if (btn) { btn.click(); return true; }
                        return false;
                    }
                """)

                if not attach_clicked:
                    raise Exception("Could not find attach button (add_2 icon)")
                print("[2] Attach button clicked", flush=True)
                page.wait_for_timeout(1000)

                # Click "Upload image" in the attachment type modal
                page.get_by_text("Upload image", exact=True).click()
                print("[2] 'Upload image' option clicked", flush=True)
                page.wait_for_timeout(1500)

                # Accept the terms notice — only appears once per session
                try:
                    page.wait_for_selector('button:has-text("I agree")', timeout=3000)
                    page.evaluate("""
                        () => {
                            const btn = Array.from(document.querySelectorAll('button'))
                                .find(b => b.innerText.trim() === 'I agree');
                            if (btn) btn.click();
                        }
                    """)
                    print("[2] 'I agree' clicked", flush=True)
                except Exception:
                    print("[2] No terms dialog (already accepted), continuing...", flush=True)

                # Wait for Flow to upload and process the image
                page.wait_for_timeout(4000)
                print("[2] Image upload complete", flush=True)

                page.remove_listener("filechooser", on_file_chooser)

            # Click into the Slate editor
            print("[3] Clicking prompt input...", flush=True)
            try:
                page.click('[data-slate-editor="true"]')
            except Exception as e:
                print(f"[3] Slate click failed: {e}", flush=True)
            page.wait_for_timeout(500)

            # Type a minimal dummy prompt — handle_route swaps it with the real one
            print("[4] Typing dummy prompt to trigger request...", flush=True)
            page.keyboard.type("x")
            page.wait_for_timeout(1000)

            # Register response listener BEFORE clicking send
            print("[5] Clicking send button...", flush=True)
            with page.expect_response(
                lambda r: "flowMedia:batchGenerateImages" in r.url,
                timeout=60000
            ) as response_info:
                clicked = page.evaluate("""
                    () => {
                        const buttons = Array.from(document.querySelectorAll('button'));
                        const sendBtn = buttons.find(b => {
                            const icon = b.querySelector('i');
                            return icon && icon.innerText.trim() === 'arrow_forward';
                        });
                        if (sendBtn) { sendBtn.click(); return true; }
                        return false;
                    }
                """)

                if not clicked:
                    print("[5] Button not found, pressing Enter", flush=True)
                    page.keyboard.press("Enter")
                else:
                    print("[5] Send button clicked", flush=True)

            response = response_info.value
            print(f"[6] Response received! Status: {response.status}", flush=True)

            raw = response.text()
            print(f"[6] Raw response (first 100 chars): {repr(raw[:100])}", flush=True)

            result = parse_response_text(raw)
            page.close()

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
            print("[IMG] Temp file cleaned up", flush=True)

    media = result.get("media", [])
    if not media:
        raise Exception(f"No media returned. Full response: {result}")

    print(json.dumps({
        "success": True,
        "image_url": media[0]["image"]["generatedImage"]["fifeUrl"]
    }))


if __name__ == "__main__":
    main()
