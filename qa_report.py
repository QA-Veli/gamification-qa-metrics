#!/usr/bin/env python3
"""
QA Bug Report Script
Reads bugs from Google Sheets and test results from Slack, then sends weekly report
"""

import os
import json
import re
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
SLACK_REPORT_CHANNEL = "#gamification-qa-metrics"
SLACK_TEST_CHANNEL = "#gamification-tests"

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

def create_slack_message(bugs_by_sheet, test_aggregation):
    """Create formatted Slack message with bugs and test results"""
    total_bugs = sum(bugs_by_sheet.values())

    # Build message blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📊 Weekly QA Report"
            }
        }
    ]

    # Section 1: Bug Report
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*🐛 Bugs Found This Week: {total_bugs}*"
        }
    })

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

    blocks.append({"type": "divider"})

    # Section 2: Test Results
    if test_aggregation:
        pass_rate_emoji = "🟢" if test_aggregation['pass_rate'] >= 95 else "🟡" if test_aggregation['pass_rate'] >= 80 else "🔴"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🧪 Test Results Summary*\n{pass_rate_emoji} *Pass Rate: {test_aggregation['pass_rate']:.1f}%*"
            }
        })

        test_details = (
            f"*Test Runs:* {test_aggregation['total_runs']}\n"
            f"• Successful: {test_aggregation['successful_runs']}\n"
            f"• Failed: {test_aggregation['failed_runs']}\n\n"
            f"*Overall Stats:*\n"
            f"• Total Tests: {test_aggregation['total_tests']}\n"
            f"• Passed: {test_aggregation['total_passed']}\n"
            f"• Failed: {test_aggregation['total_failed']}\n"
            f"• Flaky: {test_aggregation['total_flaky']}"
        )

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": test_details
            }
        })
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🧪 Test Results:* No test runs found this week"
            }
        })

    blocks.append({"type": "divider"})

    # Footer
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

def get_test_results_from_slack(slack_client):
    """Read test result messages from Slack private channel for the last 7 days"""
    try:
        # Get messages from last 7 days
        seven_days_ago = datetime.now() - timedelta(days=7)
        oldest_timestamp = seven_days_ago.timestamp()

        channel_name = SLACK_TEST_CHANNEL.lstrip('#')

        try:
            # Try to list private groups (old API but still supported)
            groups = slack_client.groups_list()
            group_id = None

            for group in groups.get('groups', []):
                if group['name'] == channel_name:
                    group_id = group['id']
                    break

            if not group_id:
                print(f"⚠️  Private channel '{channel_name}' not found or bot not member")
                return []

            # Get history from private channel
            messages = slack_client.groups_history(
                channel=group_id,
                oldest=oldest_timestamp,
                count=100
            )

        except SlackApiError as e:
            if 'unknown_method' in str(e):
                # If groups API doesn't work, try conversations_list with public channels
                print(f"⚠️  groups API not available, trying alternative method...")
                try:
                    conversations = slack_client.conversations_list()
                    channel_id = None

                    for conv in conversations.get('channels', []):
                        if conv['name'] == channel_name:
                            channel_id = conv['id']
                            break

                    if not channel_id:
                        print(f"⚠️  Channel '{channel_name}' not found")
                        return []

                    messages = slack_client.conversations_history(
                        channel=channel_id,
                        oldest=oldest_timestamp,
                        limit=100
                    )
                except Exception as e2:
                    print(f"❌ Could not read channel {SLACK_TEST_CHANNEL}: {e2}")
                    return []
            else:
                print(f"❌ Error: {e}")
                return []

        test_results = []

        for message in messages.get('messages', []):
            # Skip messages without text
            if 'text' not in message:
                continue

            text = message['text']

            # Parse test result if it contains test info
            if 'tests' in text.lower() and ('passed' in text.lower() or 'failed' in text.lower()):
                parsed = parse_test_message(text)
                if parsed:
                    parsed['timestamp'] = message.get('ts')
                    test_results.append(parsed)

        return test_results
    except SlackApiError as e:
        print(f"Error reading Slack test channel: {e}")
        return []

def parse_test_message(message_text):
    """Parse test results from message text"""
    try:
        # Pattern: "X tests from Y shards: Z passed, W failed, V flaky"
        pattern = r'(\d+)\s+tests?\s+from\s+\d+\s+shards?:\s+(\d+)\s+passed,\s+(\d+)\s+failed,?\s+(\d+)\s+flaky'
        match = re.search(pattern, message_text, re.IGNORECASE)

        if match:
            total_tests = int(match.group(1))
            passed = int(match.group(2))
            failed = int(match.group(3))
            flaky = int(match.group(4))

            # Parse test runtime
            runtime_pattern = r'Test runtime:\s+([\d.]+[smh]+)'
            runtime_match = re.search(runtime_pattern, message_text, re.IGNORECASE)
            runtime = runtime_match.group(1) if runtime_match else "N/A"

            # Calculate pass rate
            pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0

            # Get status
            status = "✅ Succeeded" if failed == 0 else "❌ Failed"

            return {
                'total': total_tests,
                'passed': passed,
                'failed': failed,
                'flaky': flaky,
                'pass_rate': pass_rate,
                'runtime': runtime,
                'status': status
            }
    except Exception as e:
        print(f"Error parsing test message: {e}")

    return None

def aggregate_test_results(test_results_list):
    """Aggregate test results from multiple runs"""
    if not test_results_list:
        return None

    total_passed = sum(r['passed'] for r in test_results_list)
    total_failed = sum(r['failed'] for r in test_results_list)
    total_flaky = sum(r['flaky'] for r in test_results_list)
    total_tests = sum(r['total'] for r in test_results_list)

    overall_pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0

    # Count successes vs failures
    successes = sum(1 for r in test_results_list if r['failed'] == 0)
    failures = len(test_results_list) - successes

    return {
        'total_runs': len(test_results_list),
        'total_tests': total_tests,
        'total_passed': total_passed,
        'total_failed': total_failed,
        'total_flaky': total_flaky,
        'pass_rate': overall_pass_rate,
        'successful_runs': successes,
        'failed_runs': failures
    }

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

    print("🚀 Starting QA Report...")

    # Initialize clients
    try:
        gc = get_google_sheets_client(google_credentials)
        slack_client = get_slack_client(slack_token)
        print("✅ Clients initialized")
    except Exception as e:
        print(f"❌ Failed to initialize clients: {e}")
        exit(1)

    # Collect bugs from all sheets
    print("\n📊 Collecting bug data...")
    bugs_by_sheet = {}
    for sheet_name in SHEET_NAMES:
        print(f"📄 Reading '{sheet_name}'...")
        bug_count = get_bugs_from_sheet(gc, sheet_name)
        bugs_by_sheet[sheet_name] = bug_count
        print(f"   Found {bug_count} bug{'s' if bug_count != 1 else ''}")

    # Collect test results from Slack
    print("\n🧪 Collecting test results...")
    test_results = get_test_results_from_slack(slack_client)
    print(f"   Found {len(test_results)} test run(s)")

    test_aggregation = aggregate_test_results(test_results)
    if test_aggregation:
        print(f"   Pass rate: {test_aggregation['pass_rate']:.1f}%")
        print(f"   Successful runs: {test_aggregation['successful_runs']}")
        print(f"   Failed runs: {test_aggregation['failed_runs']}")

    # Create and send message
    print("\n📤 Creating report...")
    blocks = create_slack_message(bugs_by_sheet, test_aggregation)
    send_slack_message(slack_client, SLACK_REPORT_CHANNEL, blocks)
    
    print("✅ Report completed!")

if __name__ == "__main__":
    main()