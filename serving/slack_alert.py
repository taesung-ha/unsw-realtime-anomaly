import requests
import os
from dotenv import load_dotenv
load_dotenv()

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

def send_slack_alert(message: str):
    if not SLACK_WEBHOOK_URL:
        print("Slack webhook URL is not set.")
        return
    
    payload = {
        "text": message
    }
    
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        print("Alert sent to Slack successfully.")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send alert to Slack: {e}")
    