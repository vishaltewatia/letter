from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto('http://localhost:5173')

        # Using a new email just to be sure we can sign up again if the DB was wiped,
        # or we just try to login if it exists. Actually let's just use login.
        page.fill('input[placeholder="Email"]', 'test_user_new3@example.com')
        page.fill('input[placeholder="Password"]', 'password123')

        # Try sign up first
        page.click('button:has-text("SIGN UP")')
        try:
            page.wait_for_selector('text="Logged in successfully"', state="visible", timeout=3000)
        except:
            # Maybe already exists, try login
            page.click('button:has-text("LOGIN")')
            page.wait_for_selector('text="Logged in successfully"', state="visible", timeout=3000)

        page.wait_for_timeout(500)

        # Click on Question Bank
        page.click('text="Question Bank"')
        page.wait_for_timeout(1000)

        # take screenshot to debug
        page.screenshot(path='/home/jules/verification/question_bank.png')

        browser.close()

if __name__ == '__main__':
    run()
