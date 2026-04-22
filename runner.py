import sys
import json
import uuid
import time
from playwright.sync_api import sync_playwright


def parse_response_text(text):
    """
    Google sometimes returns null\n{...} or )]}'\n{...}
    Strip XSSI prefix and find the last valid JSON object in the response.
    """
    # Strip XSSI protection prefix
    if text.startswith(")]}'"):
        text = text.split("\n", 1)[1]

    # Try parsing the whole thing first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Fall back: find the last line that is a valid JSON object
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
    params = json.loads(sys.argv[1])

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

    image_inputs = []
    if image_base64:
        image_inputs = [{
            "encodedImage": {
                "mimeType": mime_type,
                "encodedBytes": image_base64
            }
        }]

    result_container = {}

    def handle_route(route):
        try:
            original = json.loads(route.request.post_data)
        except Exception:
            route.continue_()
            return

        # Extract the live reCAPTCHA token and session info from Flow's request
        recaptcha_context = original.get("clientContext", {}).get("recaptchaContext", {})
        session_id = original.get("clientContext", {}).get("sessionId", "")
        batch_id = original.get("mediaGenerationContext", {}).get("batchId", str(uuid.uuid4()))

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

        # Intercept Flow's request and swap our prompt in while keeping
        # the live reCAPTCHA token from the original request intact
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

        # Click into the Slate editor
        print("[2] Clicking prompt input...", flush=True)
        try:
            page.click('[data-slate-editor="true"]')
        except Exception as e:
            print(f"[2] Slate click failed: {e}", flush=True)
        page.wait_for_timeout(500)

        # Type a minimal dummy prompt — handle_route swaps it with the real one
        print("[3] Typing dummy prompt to trigger request...", flush=True)
        page.keyboard.type("x")
        page.wait_for_timeout(1000)

        # Register response listener BEFORE clicking send
        print("[4] Clicking send button...", flush=True)
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
                print("[4] Button not found, pressing Enter", flush=True)
                page.keyboard.press("Enter")
            else:
                print("[4] Send button clicked", flush=True)

        response = response_info.value
        print(f"[5] Response received! Status: {response.status}", flush=True)

        raw = response.text()
        print(f"[5] Raw response (first 100 chars): {repr(raw[:100])}", flush=True)

        result = parse_response_text(raw)
        page.close()

    media = result.get("media", [])
    if not media:
        raise Exception(f"No media returned. Full response: {result}")

    print(json.dumps({
        "success": True,
        "image_url": media[0]["image"]["generatedImage"]["fifeUrl"]
    }))


if __name__ == "__main__":
    main()