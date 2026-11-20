import os
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from playwright.async_api import async_playwright

# ----------------- CONFIGURATION -----------------
# Reads from Render Environment Variable first, falls back to token if unset
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9022810062:AAGbTaG5G9KHMy6svkxOU0FBOSzpymo-UF0")
STATE_FILE = "musaffa_state.json"
STATE_JSON_RAW = os.getenv("MUSAFFA_STATE_JSON")

# Automatically generate musaffa_state.json if provided via Render Environment
if STATE_JSON_RAW and not os.path.exists(STATE_FILE):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(STATE_JSON_RAW)

# Default watchlist (NSE tickers)
MY_PORTFOLIO = [
    "ASIANPAINT",
    "ASTRAL",
    "HAVELLS",
    "KPITTECH",
    "PIDILITIND",
    "SUNPHARMA",
    "TATACONSUM",
    "TMCV",
    "TRENT",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ----------------- PLAYWRIGHT SCRAPING ENGINE -----------------

# ----------------- LOW-MEMORY PLAYWRIGHT ENGINE -----------------

async def fetch_musaffa_compliance(ticker: str) -> dict:
    clean_ticker = ticker.strip().upper()

    # Determine URL candidate list:
    # If the user enters an Indian stock like "TCS", Musaffa uses "TCS.NS".
    # If the user enters a US stock like "NVDA", Musaffa uses "NVDA/".
    candidates = []
    if clean_ticker.endswith(".NS") or clean_ticker.endswith(".BO"):
        candidates.append(f"https://musaffa.com/stock/{clean_ticker}/")
    else:
        # Check both: US bare ticker first, then Indian .NS ticker
        candidates.append(f"https://musaffa.com/stock/{clean_ticker}/")
        candidates.append(f"https://musaffa.com/stock/{clean_ticker}.NS/")

    if not os.path.exists(STATE_FILE):
        return {
            "ticker": clean_ticker,
            "status": "CONFIG ERROR",
            "details": f"Missing `{STATE_FILE}`. Add MUSAFFA_STATE_JSON in Render environment.",
        }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote",
                "--single-process",
            ],
        )

        try:
            context = await browser.new_context(
                storage_state=STATE_FILE,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1024, "height": 600},
            )
            page = await context.new_page()

            # Abort heavy assets to keep RAM low
            async def block_heavy_assets(route):
                if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", block_heavy_assets)

            status = "UNKNOWN"
            details = "Could not parse compliance verdict."

            for direct_url in candidates:
                logger.info(f"Checking URL: {direct_url}")
                response = await page.goto(direct_url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)

                body_text = await page.inner_text("body")
                lower_body = body_text.lower()

                # If the page 404s or shows "Stock not found", try next candidate
                if "page not found" in lower_body or "not found" in lower_body and "halal" not in lower_body:
                    continue

                if "classified as halal" in lower_body or "is halal" in lower_body:
                    status = "HALAL"
                    details = "Passed Shariah business activities and AAOIFI financial ratio screens."
                    break
                elif "classified as not halal" in lower_body or "not shariah-compliant" in lower_body:
                    status = "NOT HALAL"
                    details = "Breached financial ratios (>30% debt/cash) or failed core business screening."
                    break
                elif "doubtful" in lower_body:
                    status = "DOUBTFUL"
                    details = "Flagged as doubtful or borderline under AAOIFI screening."
                    break
                elif "sign in" in lower_body and "unlock" in lower_body:
                    status = "SESSION EXPIRED"
                    details = "Guest limit reached; update MUSAFFA_STATE_JSON in Render."
                    break

            await browser.close()
            return {"ticker": clean_ticker, "status": status, "details": details}

        except Exception as e:
            logger.error(f"Error scraping {clean_ticker}: {str(e)}")
            await browser.close()
            return {"ticker": clean_ticker, "status": "ERROR", "details": str(e)}
# ----------------- TELEGRAM BOT HANDLERS -----------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "📊 *Musaffa Shariah Screener Bot*\n\n"
        "Commands:\n"
        "• `/check <TICKER>` - Screen an Indian stock (e.g. `/check TCS`)\n"
        "• `/audit` - Screen all portfolio holdings\n"
        "• Or send any ticker symbol directly into this chat."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Please provide a ticker. Example:\n`/check INFY`", parse_mode="Markdown")
        return

    ticker = context.args[0]
    await execute_screening(update, ticker)


async def plain_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if " " not in text and len(text) <= 15:
        await execute_screening(update, text)
    else:
        await update.message.reply_text("Send a single ticker symbol, or use `/check <TICKER>`.")


async def execute_screening(update: Update, ticker: str):
    msg = await update.message.reply_text(f"⏳ Screening *{ticker.upper()}* on Musaffa...", parse_mode="Markdown")

    result = await fetch_musaffa_compliance(ticker)

    badge = result["status"]
    if badge == "HALAL":
        icon = "✅"
    elif badge == "NOT HALAL":
        icon = "❌"
    elif badge == "DOUBTFUL":
        icon = "⚠️"
    else:
        icon = "ℹ️"

    response = (
        f"{icon} *Stock:* `{result['ticker']}`\n"
        f"*Status:* *{badge}*\n"
        f"*Details:* {result['details']}\n\n"
        f"_Source: Musaffa Stock Screener_"
    )
    await msg.edit_text(response, parse_mode="Markdown")


async def audit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text(
        f"⏳ Auditing your {len(MY_PORTFOLIO)} stocks on Musaffa...\n"
        "This will take roughly 30–45 seconds.",
        parse_mode="Markdown",
    )

    results = []
    for ticker in MY_PORTFOLIO:
        res = await fetch_musaffa_compliance(ticker)
        icon = "✅" if res["status"] == "HALAL" else "❌" if res["status"] == "NOT HALAL" else "⚠️"
        results.append(f"{icon} *{ticker}*: {res['status']}")

    summary_text = (
        "📋 *Portfolio Shariah Compliance Audit Report*\n\n"
        + "\n".join(results)
        + "\n\n_Checked against Musaffa Indian Equities Screener._"
    )
    await status_msg.edit_text(summary_text, parse_mode="Markdown")


# ----------------- DUMMY SERVER FOR RENDER -----------------

class RenderHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is healthy and polling Telegram!")

    def log_message(self, format, *args):
        return  # Suppress health check spam in logs


def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), RenderHealthHandler)
    logger.info(f"✅ Render dummy health server bound to 0.0.0.0:{port}")
    server.serve_forever()


# ----------------- MAIN INITIALIZATION -----------------

def main():
    # 1. Start Render HTTP port binding server on a background daemon thread
    server_thread = threading.Thread(target=run_dummy_server, daemon=True)
    server_thread.start()

    # 2. Check if state file exists
    if not os.path.exists(STATE_FILE):
        logger.warning(f"⚠️ '{STATE_FILE}' not found. Make sure MUSAFFA_STATE_JSON is set in Render.")

    # 3. Initialize Telegram application
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("audit", audit_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), plain_text_handler))

    logger.info("🤖 Telegram Bot initialized and polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
