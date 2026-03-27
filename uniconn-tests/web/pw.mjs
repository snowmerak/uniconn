import { chromium } from 'playwright';
import fs from 'fs';

const info = JSON.parse(fs.readFileSync('./web_test_info.json', 'utf8'));

(async () => {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    console.log("Navigating to Vite dev server...");
    await page.goto("http://localhost:5173/");

    console.log("Waiting for ML-DSA keys to generate...");
    await page.waitForFunction(() => {
        const t = document.getElementById('myFp')?.textContent;
        return t && t !== 'Not Connected' && t.length > 10;
    }, { timeout: 60000 });
    
    const myFp = await page.$eval('#myFp', el => el.textContent);
    console.log("Browser Node Identity Generated! FP:", myFp?.substring(0, 16) + '...');

    console.log("Connecting to Relay WS...");
    await page.fill('#relayFp', info.relayFp);
    await page.fill('#relayAddr', 'ws://127.0.0.1:10002');
    await page.click('#connectBtn');

    console.log("Waiting for Announce...");
    await page.waitForFunction(() => {
        return document.getElementById('logs')?.textContent?.includes('Relay Connected & Announce Sent!');
    }, { timeout: 10000 });

    console.log("Dialing Python Responder...");
    await page.fill('#targetFp', info.pyFp);
    await page.click('#dialBtn');

    console.log("Awaiting PONG_FROM_WEB / PING_FROM_WEB exchange...");
    await page.waitForFunction(() => {
        return document.getElementById('logs')?.textContent?.includes('Received Reply: PONG');
    }, { timeout: 15000 });

    const full_logs = await page.$eval('#logs', el => el.textContent);
    console.log("\n=== FINAL BROWSER LOGS ===");
    console.log(full_logs);
    
    console.log("\nSUCCESS! Web E2EE Integration Test Passed.");
    await browser.close();
})().catch(e => {
    console.error("Test failed:", e);
    process.exit(1);
});
