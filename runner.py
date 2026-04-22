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
        # Intercept Flow's own request and swap in our payload.
        # All original headers (including reCAPTCHA token) are preserved.
        route.continue_(post_data=json.dumps(our_payload))

    def handle_response(response):
        if "flowMedia:batchGenerateImages" in response.url:
            try:
                result_container["data"] = response.json()
            except Exception:
                result_container["error"] = response.text()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        context.add_cookies(session_cookies)

        page = context.new_page()

        # Intercept the API call Flow makes and swap our payload in
        page.route("**batchGenerateImages**", handle_route)
        page.on("response", handle_response)

        page.goto("https://labs.google/fx/tools/flow")
        page.wait_for_timeout(4000)

        # Trigger Flow's generate button so it fires its own request
        # (our route handler swaps the payload mid-flight)
        page.evaluate("""
            () => {
                // Find and click the generate button
                const buttons = Array.from(document.querySelectorAll('button'));
                const generateBtn = buttons.find(b =>
                    b.innerText.toLowerCase().includes('generate') ||
                    b.getAttribute('aria-label')?.toLowerCase().includes('generate')
                );
                if (generateBtn) generateBtn.click();
            }
        """)

        # Wait for the intercepted response
        page.wait_for_timeout(15000)
        browser.close()

    if "error" in result_container:
        raise Exception(result_container["error"])

    if "data" not in result_container:
        raise Exception("No response intercepted. The generate button may not have been found or clicked.")

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