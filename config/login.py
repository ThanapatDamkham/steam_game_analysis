from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT: Path = Path(__file__).resolve().parent.parent
AUTH_FILE: Path = ROOT / "config" / "steam_auth.json"

AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(locale="th-TH")
    page = context.new_page()
    page.goto("https://store.steampowered.com/login/")
    print("Login ในเบราว์เซอร์ให้เสร็จ แล้วกด Enter ในนี้")
    input()
    context.storage_state(path=str(AUTH_FILE))
    print(f"เซฟ {AUTH_FILE} แล้ว")
    browser.close()