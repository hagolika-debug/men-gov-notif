#!/usr/bin/env python3
import json
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import os

import requests

ANNOUNCEMENTS_URL = "https://www.men.gov.ma/data/announcements.json"

# --- CONFIGURATION FOR TELEGRAM BOT ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7769758682:AAH2DP9U1TK7nnwLI74Ld1DegxHnrEeUAoA")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "2035257746")
# ---------------------------------------

# File where we remember the last seen announcement id
STATE_FILE = Path(__file__).with_name("last_announcement_id.txt")

CHECK_INTERVAL_SECONDS = 10  # 10 seconds


def fetch_announcements() -> List[Dict[str, Any]]:
    """Fetch the announcements JSON from the ministry site."""
    resp = requests.get(ANNOUNCEMENTS_URL, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_latest_id(announcements: List[Dict[str, Any]]) -> Optional[str]:
    """Return the ID of the first (newest) announcement in the list."""
    if not announcements:
        return None
    return announcements[0]["id"]


def load_last_id() -> Optional[str]:
    if not STATE_FILE.exists():
        return None
    return STATE_FILE.read_text(encoding="utf-8").strip() or None


def save_last_id(last_id: str):
    STATE_FILE.write_text(str(last_id), encoding="utf-8")


def send_desktop_notification(title: str, message: str):
    """Send a Linux Mint desktop notification."""
    try:
        subprocess.run(["notify-send", title, message])
    except Exception as e:
        print(f"[WARN] notify-send error: {e}", file=sys.stderr)


def format_telegram_text_html(text: str) -> str:
    """Escape HTML reserved characters for Telegram's HTML format."""
    # Escape only '<', '>' and '&' which are required for HTML mode.
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def send_telegram_notification(message: str):
    """Sends a message directly to Telegram using the Bot API."""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        print("[WARN] Telegram configuration missing. Skipping Telegram notification.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        # CHANGED: Switched to HTML mode for easier escaping
        "parse_mode": "HTML" 
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        print(f"[INFO] Telegram message sent successfully.")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to send Telegram message: {e}", file=sys.stderr)


def notify_new_announcements(new_items: List[Dict[str, Any]]):
    """Print info + send desktop notification + trigger Telegram notification."""
    print("\n" + "=" * 50)
    print(f"🔔 {len(new_items)} new announcement(s) found!") 
    print("=" * 50 + "\n")

    base_url = "https://www.men.gov.ma/"

    # Display items from oldest new to newest new (reversed order for chronological print)
    items_to_display = list(reversed(new_items)) 

    # Prepare message for Telegram using HTML
    newest_item = new_items[0]
    first_title = newest_item.get("title_fr", "New Announcement") 
    
    # Start message with a bold HTML header
    telegram_message = f"<b>📢 {len(new_items)} New MEN Announcement(s)!</b>\n"
    
    # Concatenate details for the Telegram body
    for a in items_to_display:
        title_fr = a.get('title_fr', 'Announcement')
        item_id = a['id']
        
        # Start a new block with HTML bold tags
        telegram_message += f"\n\n- <b>ID: {item_id}</b>" 
        # Escape the text content using the new HTML function
        telegram_message += f"\n  <b>{format_telegram_text_html(title_fr)}</b>"
        
        pdfs = a.get('pdf')
        if pdfs and pdfs[0].get('url'):
             # Link format: <a href="URL">Text</a>
             link_text = format_telegram_text_html(pdfs[0].get("label_fr", "View Document"))
             url = base_url + pdfs[0]['url']
             
             # Create the HTML link tag
             telegram_message += f"\n  <a href='{url}'>{link_text}</a>"
        
    # 1. Terminal Output (Unchanged)
    for a in items_to_display:
        print("====================================")
        print(f"🆔 ID       : {a['id']}")
        print(f"📅 Date     : {a.get('date', 'N/A')}")
        print(f"🇫🇷 Title   : {a.get('title_fr', '')}") 
        print(f"🇲🇦 العنوان : {a.get('title_ar', '')}")
        print(f"\nSummary EN : {a.get('description_fr', '')}") 
        print(f"الملخص AR : {a.get('description_ar', '')}\n")

        pdfs = a.get("pdf", [])
        if pdfs:
            print("📄 PDF :")
            for p in pdfs:
                print("  -", p.get("label_fr", "Link"), "→", base_url + p["url"])
        print("====================================\n")

    # 2. Desktop Notification (Kept)
    send_desktop_notification("MEN – New Announcement", first_title)
    
    # 3. Telegram Notification
    send_telegram_notification(telegram_message)


def check_once(last_seen_id: Optional[str]):
    try:
        announcements = fetch_announcements()
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Error: {e}", file=sys.stderr) 
        return last_seen_id

    latest_id = get_latest_id(announcements)

    if latest_id is None:
        print(f"[{datetime.now()}] ⚠️ No results in the JSON.") 
        return last_seen_id

    # --- Step 1: Initialization ---
    if last_seen_id is None:
        save_last_id(latest_id)
        print(f"[{datetime.now()}] Initialization : ID = {latest_id}") 
        return latest_id

    # --- Step 2: Check for new announcements using list index ---
    
    if latest_id == last_seen_id:
        print(f"[{datetime.now()}] No new announcement.") 
        return last_seen_id

    try:
        # Find the index of the last seen ID.
        index_of_last_seen = next(
            i for i, a in enumerate(announcements) if a["id"] == last_seen_id
        )
        
        # All items from the start of the list up to (but not including) the last seen index are new.
        new_items = announcements[:index_of_last_seen]

    except StopIteration:
        # The last seen ID was not found.
        print(f"[{datetime.now()}] ⚠️ Last seen ID ({last_seen_id}) not found. Assuming the new latest items are new.", file=sys.stderr)
        new_items = announcements 

    if not new_items:
        print(f"[{datetime.now()}] No new announcement found based on index.")
        return last_seen_id

    # Notify
    notify_new_announcements(new_items)

    # Update last seen to the newest ID
    save_last_id(latest_id)
    print(f"[{datetime.now()}] 🔄 ID updated: {last_seen_id} → {latest_id}") 

    return latest_id


def main():
    print("==== MEN Announcement Monitor (Linux Mint) ====") 
    print("Checking every 10 seconds…")
    print("Press Ctrl + C to stop.\n")

    last_seen_id = load_last_id()

    while True:
        last_seen_id = check_once(last_seen_id)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Program stopped. See you soon!")
