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
    try:
        parts = pr_url.strip("/").split("/")
        if len(parts) < 7 or "github.com" not in pr_url or "pull" not in pr_url:
            print("❌ Invalid URL format!")
            return "ERROR:INVALID"
        owner = parts[3]
        repo = parts[4]
        pr_number = parts[6]
    except Exception:
        return "ERROR:INVALID"

    print(f"📦 Fetching PR #{pr_number} from {owner}/{repo}...")

    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.diff"
    }

    response = requests.get(api_url, headers=headers)

    if response.status_code == 200:
        content = response.text
        print("✅ PR diff fetched successfully!")
        if len(content) > 8000:
            print("⚠️ Large PR detected — review may be incomplete")
            return "WARNING:" + content
        return content
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
    print(f"Diff length: {len(diff)}")

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


def get_repo_files(repo_url):
    """Fetches all code files from a GitHub repo"""
    try:
        parts = repo_url.strip("/").split("/")
        if len(parts) < 5 or "github.com" not in repo_url:
            return "ERROR:INVALID"
        owner = parts[3]
        repo = parts[4].replace(".git", "")
    except Exception:
        return "ERROR:INVALID"

    print(f"📦 Fetching repo files from {owner}/{repo}...")

    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    response = requests.get(api_url, headers=headers)

    if response.status_code != 200:
        return "ERROR:404"

    tree = response.json().get("tree", [])

    # Only get code files
    code_extensions = ['.py', '.js', '.ts', '.html', '.css', '.java', '.cpp', '.c', '.go', '.rs']
    code_files = [f for f in tree if f["type"] == "blob" and any(f["path"].endswith(ext) for ext in code_extensions)]

    # Limit to first 10 files to avoid token limit
    code_files = code_files[:10]

    if not code_files:
        return "ERROR:NOFILES"

    all_code = ""
    for file in code_files:
        file_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{file['path']}"
        file_response = requests.get(file_url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        if file_response.status_code == 200:
            all_code += f"\n\n{'='*50}\nFile: {file['path']}\n{'='*50}\n"
            all_code += file_response.text[:2000]  # limit each file to 2000 chars

    print(f"✅ Fetched {len(code_files)} files!")
    return all_code


def review_repo(code):
    """Sends entire repo code to AI for review"""
    print("\n🤖 Sending repo to Groq AI for review...\n")

    prompt = f"""
You are an expert code reviewer. Analyze the following codebase and provide a detailed review.

Your review must include:
1. 📋 OVERVIEW - What does this project do?
2. 🏗️ ARCHITECTURE - How is the code structured?
3. ✅ GOOD THINGS - What is done well?
4. ⚠️ ISSUES & BUGS - Any bugs, errors, or bad practices?
5. 🔒 SECURITY - Any security concerns?
6. ⚡ OPTIMIZATIONS - How can the code be improved?
7. 📝 OVERALL VERDICT - Production ready / Needs Work / Good Start

Here is the codebase:
{code[:8000]}
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content
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