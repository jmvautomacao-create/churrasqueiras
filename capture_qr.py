import os, time
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
b = p.chromium.launch(
    headless=False,
    args=["--no-sandbox", "--disable-gpu", "--disable-software-rasterizer"]
)
page = b.new_page()
page.set_viewport_size({"width": 800, "height": 600})
page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=30000)

os.makedirs("/tmp/qr", exist_ok=True)
for i in range(20):
    page.screenshot(path=f"/tmp/qr/qr_{i:02d}.png")
    print(f"Screenshot {i}")
    time.sleep(3)

b.close()
p.stop()
print("Fim")
