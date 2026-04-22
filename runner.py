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
        # Preserve all original headers (including reCAPTCHA token),
        # only swap out the request body with our payload
        route.continue_(post_data=json.dumps(our_payload))

    def handle_response(response):
        if "flowMedia:batchGenerateImages" in response.url:
            try:
                result_container["data"] = response.json()
            except Exception:
                result_container["error"] = response.text()

    with sync_playwright() as p:
        # Connect to your already-running Chrome instance via CDP.
        # This uses your real Chrome with real fingerprint and active
        # Google session — reCAPTCHA passes naturally.
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        except Exception as e:
            raise Exception(
                "Could not connect to Chrome. Make sure Chrome is running with: "
                "chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\chrome-debug-profile\n"
                f"Original error: {e}"
            )

        # Use the first existing browser context (your real logged-in session)
        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = browser.new_context()

        page = context.new_page()

        # Intercept the API call and swap our payload in
        page.route("**batchGenerateImages**", handle_route)
        page.on("response", handle_response)

        page.goto("https://labs.google/fx/tools/flow")
        page.wait_for_timeout(3000)

        # Click "Create with Flow" to enter the actual editor
        page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button, a'));
                const createBtn = buttons.find(b =>
                    b.innerText.toLowerCase().includes('create with flow')
                );
                if (createBtn) createBtn.click();
            }
        """)

        page.wait_for_timeout(4000)

        # Type prompt into the input field
        page.evaluate("""
            (prompt) => {
                const inputs = Array.from(document.querySelectorAll(
                    'textarea, input[type="text"], [contenteditable="true"]'
                ));
                if (inputs.length > 0) {
                    inputs[0].focus();
                    inputs[0].value = prompt;
                    inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
                    inputs[0].dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
        """, prompt)

        page.wait_for_timeout(1000)

        # Click the generate button
        clicked = page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));
                const generateBtn = buttons.find(b =>
                    b.innerText.toLowerCase().includes('generate') ||
                    b.getAttribute('aria-label')?.toLowerCase().includes('generate') ||
                    b.getAttribute('data-testid')?.toLowerCase().includes('generate')
                );
                if (generateBtn) {
                    generateBtn.click();
                    return true;
                }
                return false;
            }
        """)

        if not clicked:
            page.screenshot(path="debug_screenshot.png")
            page.close()
            raise Exception(
                "Generate button not found. Check debug_screenshot.png to see the page state."
            )

        # Wait for intercepted response
        page.wait_for_timeout(15000)
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