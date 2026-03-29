import requests
import os
from dotenv import load_dotenv
from groq import Groq
import click

# Load your secret keys from .env file
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Setup Groq
client = Groq(api_key=GROQ_API_KEY)


def get_pr_diff(pr_url):
    parts = pr_url.strip("/").split("/")
    owner = parts[3]
    repo = parts[4]
    pr_number = parts[6]

    print(f"📦 Fetching PR #{pr_number} from {owner}/{repo}...")

    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.diff"
    }

    response = requests.get(api_url, headers=headers)

    if response.status_code == 200:
        print("✅ PR diff fetched successfully!")
        return response.text
    elif response.status_code == 404:
        print("❌ PR not found!")
        return "ERROR:404"
    elif response.status_code == 401:
        print("❌ Invalid GitHub token!")
        return "ERROR:401"
    elif response.status_code == 403:
        print("❌ Access forbidden!")
        return "ERROR:403"
    else:
        print(f"❌ Error: {response.status_code}")
        return "ERROR:UNKNOWN"


def get_pr_info(pr_url):
    """Gets PR title, author and date"""
    parts = pr_url.strip("/").split("/")
    owner = parts[3]
    repo = parts[4]
    pr_number = parts[6]

    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    response = requests.get(api_url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        return {
            "title": data["title"],
            "author": data["user"]["login"],
            "date": data["created_at"][:10],
            "repo": f"{owner}/{repo}",
            "number": pr_number,
            "state": data["state"]
        }
    return None


def review_code(diff):
    print("\n🤖 Sending code to Groq AI for review...\n")

    prompt = f"""
You are an expert code reviewer. Analyze the following GitHub Pull Request diff and provide a detailed review.

Your review must include:
1. 📋 SUMMARY - What does this PR do?
2. ✅ GOOD THINGS - What is done well?
3. ⚠️ ISSUES & BUGS - Any bugs, errors, or bad practices?
4. 🔲 EDGE CASES - What edge cases are not handled?
5. ⚡ OPTIMIZATIONS - How can the code be improved or made faster?
6. 🔒 SECURITY - Any security concerns?
7. 📝 FINAL VERDICT - Approve / Request Changes / Needs Discussion

Here is the PR diff:
{diff[:8000]}
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content


def save_review(pr_url, review):
    parts = pr_url.strip("/").split("/")
    owner = parts[3]
    repo = parts[4]
    pr_number = parts[6]
    filename = f"review_{owner}_{repo}_PR{pr_number}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# AI Code Review — {owner}/{repo} PR #{pr_number}\n\n")
        f.write(review)

    print(f"\n💾 Review saved to: {filename}")
    return filename


@click.command()
@click.option("--url", prompt="Paste a GitHub PR URL", help="GitHub PR URL to review")
def main(url):
    """🔍 AI Code Review Assistant — reviews any GitHub PR using AI"""
    print("=== 🔍 AI Code Review Assistant ===\n")

    diff = get_pr_diff(url)

    if diff:
        review = review_code(diff)
        print("=" * 50)
        print("📊 AI CODE REVIEW RESULTS")
        print("=" * 50)
        print(review)
        print("=" * 50)
        save_review(url, review)


if __name__ == "__main__":
    main()