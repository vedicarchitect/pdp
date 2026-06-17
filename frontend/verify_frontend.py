from playwright.sync_api import sync_playwright

def run_cuj(page):
    page.goto("http://localhost:5173/intraday")
    page.wait_for_timeout(2000)

    # Click Kill Switch to open modal
    page.get_by_role("button", name="Kill switch").click()
    page.wait_for_timeout(1000)

    # Take screenshot of the modal with updated a11y attributes
    page.screenshot(path="/app/frontend/screenshots/kill_switch_modal.png")
    page.wait_for_timeout(1000)

    # Click Cancel (using exact=True since it complained about multiple elements matching 'Cancel')
    page.get_by_role("button", name="Cancel", exact=True).click()
    page.wait_for_timeout(1000)

    page.goto("http://localhost:5173/positional")
    page.wait_for_timeout(2000)

    # We can't easily trigger the rollover modal since it requires active positional data.
    # But we can at least screenshot the main page.
    page.screenshot(path="/app/frontend/screenshots/positional_page.png")
    page.wait_for_timeout(1000)


if __name__ == "__main__":
    import os
    os.makedirs("/app/frontend/videos", exist_ok=True)
    os.makedirs("/app/frontend/screenshots", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir="/app/frontend/videos"
        )
        page = context.new_page()
        try:
            run_cuj(page)
        finally:
            context.close()
            browser.close()
