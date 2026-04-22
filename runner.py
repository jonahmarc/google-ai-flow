import sys
import json
import uuid
import time
from playwright.sync_api import sync_playwright


def main():
    params = json.loads(sys.argv[1])

    prompt = params["prompt"]
    session_cookies = params["session_cookies"]
    bearer_token = params.get("bearer_token", "")
    aspect_ratio = params["aspect_ratio"]
    image_base64 = params.get("image_base64")
    mime_type = params.get("mime_type", "image/jpeg")

    PROJECT_ID = "0c5ebc9f-bc1f-4159-b613-6328056b8602"
    API_URL = f"https://aisandbox-pa.googleapis.com/v1/projects/{PROJECT_ID}/flowMedia:batchGenerateImages"

    ASPECT_RATIOS = {
        "landscape": "IMAGE_ASPECT_RATIO_LANDSCAPE",
        "portrait":  "IMAGE_ASPECT_RATIO_PORTRAIT",
        "square":    "IMAGE_ASPECT_RATIO_SQUARE",
    }

    batch_id = str(uuid.uuid4())
    session_id = f";{int(time.time() * 1000)}"
    seed = int(time.time()) % 999999
    ratio = ASPECT_RATIOS.get(aspect_ratio, ASPECT_RATIOS["landscape"])

    image_inputs = []
    if image_base64:
        image_inputs = [{
            "encodedImage": {
                "mimeType": mime_type,
                "encodedBytes": image_base64
            }
        }]

    client_context = {
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
                "imageAspectRatio": ratio,
                "structuredPrompt": {
                    "parts": [{"text": prompt}]
                },
                "seed": seed,
                "imageInputs": image_inputs
            }
        ]
    }

    result_container = {}

    def handle_route(route):
        print(f"[ROUTE INTERCEPTED] {route.request.url}", flush=True)
        route.continue_(post_data=json.dumps(our_payload))

    def handle_response(response):
        if "flowMedia:batchGenerateImages" in response.url:
            print(f"[RESPONSE INTERCEPTED] status={response.status}", flush=True)
            try:
                result_container["data"] = response.json()
            except Exception:
                result_container["error"] = response.text()

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        except Exception as e:
            raise Exception(
                "Could not connect to Chrome. Make sure Chrome is running with: "
                "chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\chrome-cdp-profile\n"
                f"Original error: {e}"
            )

        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = browser.new_context()

        page = context.new_page()

        page.route("**batchGenerateImages**", handle_route)
        page.on("response", handle_response)

        print("[1] Navigating to project...", flush=True)
        page.goto(
            "https://labs.google/fx/tools/flow/project/0c5ebc9f-bc1f-4159-b613-6328056b8602",
            wait_until="domcontentloaded",
            timeout=60000
        )
        page.wait_for_timeout(4000)
        page.screenshot(path="debug_1_loaded.png")
        print("[1] Screenshot saved: debug_1_loaded.png", flush=True)

        # Dismiss any popup
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        page.screenshot(path="debug_2_after_escape.png")
        print("[2] Screenshot saved: debug_2_after_escape.png", flush=True)

        # Click into the Slate editor
        print("[3] Clicking prompt input...", flush=True)
        try:
            page.click('[data-slate-editor="true"]')
            print("[3] Clicked slate editor", flush=True)
        except Exception as e:
            print(f"[3] Failed to click slate editor: {e}", flush=True)
            try:
                page.click('textarea')
                print("[3] Clicked textarea fallback", flush=True)
            except Exception as e2:
                print(f"[3] Textarea fallback also failed: {e2}", flush=True)

        page.wait_for_timeout(500)
        page.screenshot(path="debug_3_after_click.png")
        print("[3] Screenshot saved: debug_3_after_click.png", flush=True)

        # Type the prompt
        print(f"[4] Typing prompt: {prompt}", flush=True)
        page.keyboard.type(prompt)
        page.wait_for_timeout(1000)
        page.screenshot(path="debug_4_after_type.png")
        print("[4] Screenshot saved: debug_4_after_type.png", flush=True)

        # Try to click the Create/arrow button
        print("[5] Clicking create button...", flush=True)
        clicked = page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));
                // Match specifically the arrow_forward icon, not add_2
                const sendBtn = buttons.find(b => {
                    const icon = b.querySelector('i');
                    return icon && icon.innerText.trim() === 'arrow_forward';
                });
                if (sendBtn) { sendBtn.click(); return true; }
                return false;
            }
        """)

        print(f"[5] Button clicked: {clicked}", flush=True)

        if not clicked:
            print("[5] Falling back to Enter key", flush=True)
            page.keyboard.press("Enter")

        page.wait_for_timeout(2000)
        page.screenshot(path="debug_5_after_submit.png")
        print("[5] Screenshot saved: debug_5_after_submit.png", flush=True)

        # Wait for generation
        print("[6] Waiting 30s for generation...", flush=True)
        page.wait_for_timeout(30000)
        page.screenshot(path="debug_6_after_wait.png")
        print("[6] Screenshot saved: debug_6_after_wait.png", flush=True)

        page.close()

    if "error" in result_container:
        raise Exception(result_container["error"])

    if "data" not in result_container:
        raise Exception("No response intercepted from Google Flow.")

    result = result_container["data"]
    media = result.get("media", [])
    if not media:
        raise Exception(f"No media returned. Full response: {result}")

    print(json.dumps({
        "success": True,
        "image_url": media[0]["image"]["generatedImage"]["fifeUrl"]
    }))


if __name__ == "__main__":
    main()