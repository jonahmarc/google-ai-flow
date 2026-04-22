import asyncio
import json
from playwright.async_api import async_playwright

async def save_session():
    bearer_token = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )

        # Remove the webdriver flag that Google checks
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = await context.new_page()

        async def handle_request(request):
            nonlocal bearer_token
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                bearer_token = auth
                print(f"✅ Captured Bearer token")

        page.on("request", handle_request)

        print("🌐 Opening Google Flow — log in when the browser opens...")
        await page.goto("https://accounts.google.com")

        print("⏳ You have 60 seconds to log in...")
        await page.wait_for_timeout(60000)

        await page.goto("https://labs.google/fx/tools/flow")

        print("⏳ Waiting 15s for token to appear...")
        await page.wait_for_timeout(15000)

        cookies = await context.cookies()

        session = {
            "cookies": cookies,
            "bearer_token": bearer_token
        }

        with open("session.json", "w") as f:
            json.dump(session, f, indent=2)

        print(f"✅ Session saved. Bearer token: {'found' if bearer_token else 'NOT FOUND'}")
        await browser.close()

asyncio.run(save_session())