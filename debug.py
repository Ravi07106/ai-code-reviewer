import requests
import os
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

api_url = "https://api.github.com/repos/pallets/flask/pulls/5627"
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3.diff"
}
response = requests.get(api_url, headers=headers)
print(f"Status: {response.status_code}")
print(f"Response: {response.text[:300]}")