import asyncio
from playwright.async_api import async_playwright

async def manual_login():
    print("🚀 Opening browser for one-time manual login...")
    async with async_playwright() as p:
        # Yeh `./chrome_profile` folder aapke login data ko save karega
        browser = await p.chromium.launch_persistent_context(
            user_data_dir="./chrome_profile",
            headless=False
        )
        page = await browser.new_page()
        
        # Flipkart kholein
        await page.goto("https://www.flipkart.com")
        print("👉 Flipkart khul gaya hai! Agar login nahi hai toh apna mobile number/OTP dalkar login kar lein.")
        
        # 2 minute ka time diya hai login karne ke liye
        await asyncio.sleep(120) 
        await browser.close()
        print("✅ Login session saved successfully in ./chrome_profile folder!")

asyncio.run(manual_login())