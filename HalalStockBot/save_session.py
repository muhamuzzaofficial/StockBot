import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        # Launch browser in visible mode
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("Opening Musaffa login page. Please log in manually...")
        await page.goto("https://musaffa.com/stock-screener/in/")

        # Wait 60 seconds to allow you to log into your Musaffa account
        await page.wait_for_timeout(60000)

        # Save the session cookies and storage
        await context.storage_state(path="musaffa_state.json")
        print("Session saved successfully to musaffa_state.json!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())