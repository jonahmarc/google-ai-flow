import sys
import json
import time
from playwright.sync_api import sync_playwright


def main():
    params = json.loads(sys.argv[1])

    prompt = params["prompt"]
    aspect_ratio = params["aspect_ratio"]

    result_container = {}

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

        # Only capture the response — do NOT intercept/swap the payload
        # reCAPTCHA is bound to Flow's own request body, swapping it breaks auth
        page.on("response", handle_response)

        print("[1] Navigating to project...", flush=True)
        page.goto(
            "https://labs.google/fx/tools/flow/project/0c5ebc9f-bc1f-4159-b613-6328056b8602",
            wait_until="domcontentloaded",
            timeout=60000
        )
        page.wait_for_timeout(4000)

        # Dismiss any popup
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

        # Click into the Slate editor prompt input
        print("[2] Clicking prompt input...", flush=True)
        try:
            page.click('[data-slate-editor="true"]')
        except Exception as e:
            print(f"[2] Slate editor click failed: {e}", flush=True)

        page.wait_for_timeout(500)

        # Type the prompt
        print(f"[3] Typing prompt: {prompt}", flush=True)
        page.keyboard.type(prompt)
        page.wait_for_timeout(1000)

        # Click the send button (arrow_forward icon)
        print("[4] Clicking send button...", flush=True)
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

        # Wait for generation to complete
        print("[5] Waiting for generation...", flush=True)
        page.wait_for_timeout(30000)
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