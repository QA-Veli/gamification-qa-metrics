#!/usr/bin/env python3
"""
QA Bug Report Script
Reads bugs from Google Sheets and sends weekly report to Slack
"""

import os
import json
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
import gspread
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Constants
SPREADSHEET_ID = "1u4fHAIdRckZDo9psDoJA3uVYC__aiZWmo7OlZpJctRc"
SHEET_NAMES = ["Tournaments", "Loyalty Program", "Rakeback", "Secretbox", "Boosters", "Widget Settings", "Media Library"]
DATE_COLUMN = "Date"
SLACK_CHANNEL = "#gamification-qa-metrics"

def get_google_sheets_client(credentials_json):
    """Initialize Google Sheets client"""
    credentials_dict = json.loads(credentials_json)
    credentials = Credentials.from_service_account_info(
        credentials_dict,
        scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
    )
    return gspread.authorize(credentials)

def get_slack_client(token):
    """Initialize Slack client"""
    return WebClient(token=token)

def parse_date(date_str):
    """Parse date from MM/DD/YYYY format"""
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y")
    except ValueError:
        return None

def get_bugs_from_sheet(gc, sheet_name):
    """Get bugs from a specific sheet for the last 7 days"""
    try:
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # Get all records
        records = worksheet.get_all_records()
        
        if not records:
            return 0
        
        # Get today's date and 7 days ago
        today = datetime.now()
        seven_days_ago = today - timedelta(days=7)
        
        # Count bugs from last 7 days
        bug_count = 0
        for record in records:
            date_str = record.get(DATE_COLUMN, "")
            if date_str:
                bug_date = parse_date(date_str)
                if bug_date and seven_days_ago <= bug_date <= today:
                    bug_count += 1
        
        return bug_count
    except Exception as e:
        print(f"Error reading sheet '{sheet_name}': {e}")
        return 0

def create_slack_message(bugs_by_sheet):
    """Create formatted Slack message"""
    total_bugs = sum(bugs_by_sheet.values())
    
    # Build message blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📊 Weekly QA Bug Report"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Total bugs found this week: {total_bugs}*"
            }
        },
        {
            "type": "divider"
        }
    ]
    
    # Add breakdown by sheet
    if bugs_by_sheet:
        breakdown_text = "*Breakdown by feature:*\n"
        for sheet_name, count in bugs_by_sheet.items():
            breakdown_text += f"• {sheet_name}: {count} bug{'s' if count != 1 else ''}\n"
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": breakdown_text
            }
        })
    
    # Add timestamp
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            }
        ]
    })
    
    return blocks

def send_slack_message(slack_client, channel, blocks):
    """Send message to Slack channel"""
    try:
        response = slack_client.chat_postMessage(
            channel=channel,
            blocks=blocks
        )
        print(f"✅ Message sent successfully to {channel}")
        return True
    except SlackApiError as e:
        print(f"❌ Error sending message to Slack: {e}")
        return False

def main():
    # Get credentials from environment variables
    google_credentials = os.getenv('GOOGLE_CREDENTIALS_JSON')
    slack_token = os.getenv('SLACK_BOT_TOKEN')
    
    if not google_credentials or not slack_token:
        print("❌ Missing environment variables:")
        if not google_credentials:
            print("  - GOOGLE_CREDENTIALS_JSON")
        if not slack_token:
            print("  - SLACK_BOT_TOKEN")
        exit(1)
    
    print("🚀 Starting QA Bug Report...")
    
    # Initialize clients
    try:
        gc = get_google_sheets_client(google_credentials)
        slack_client = get_slack_client(slack_token)
        print("✅ Clients initialized")
    except Exception as e:
        print(f"❌ Failed to initialize clients: {e}")
        exit(1)
    
    # Collect bugs from all sheets
    bugs_by_sheet = {}
    for sheet_name in SHEET_NAMES:
        print(f"📄 Reading '{sheet_name}'...")
        bug_count = get_bugs_from_sheet(gc, sheet_name)
        bugs_by_sheet[sheet_name] = bug_count
        print(f"   Found {bug_count} bug{'s' if bug_count != 1 else ''}")
    
    # Create and send message
    blocks = create_slack_message(bugs_by_sheet)
    send_slack_message(slack_client, SLACK_CHANNEL, blocks)
    
    print("✅ Report completed!")

if __name__ == "__main__":
    main()