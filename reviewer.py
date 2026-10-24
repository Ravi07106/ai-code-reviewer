
import os
from urllib.parse import urlparse

import click
import requests
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

GROQ_MODEL = "openai/gpt-oss-120b"
GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 30

CODE_EXTENSIONS = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css",
    ".java", ".cpp", ".c", ".h", ".hpp", ".go", ".rs",
    ".php", ".rb", ".swift", ".kt", ".sql", ".vue", ".json",
)

IGNORED_PATH_PARTS = {
    "node_modules", "vendor", ".git", "dist", "build",
    "__pycache__", ".venv", "venv", "coverage",
}

MAX_REPO_FILES = 20
MAX_FILE_CHARS = 3000
MAX_REVIEW_INPUT_CHARS = 24000
MAX_DIFF_CHARS = 12000


def _github_headers(accept="application/vnd.github+json"):
    headers = {"Accept": accept}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _parse_github_url(url, is_pr=False):
    """Validate a GitHub URL and return its owner/repository details."""
    try:
        parsed = urlparse(url.strip())
        if parsed.hostname not in {"github.com", "www.github.com"}:
            return None

        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) < 2:
            return None

        owner = parts[0]
        repo = parts[1].removesuffix(".git")

        if not owner or not repo:
            return None

        result = {"owner": owner, "repo": repo}

        if is_pr:
            if len(parts) < 4 or parts[2] != "pull":
                return None
            if not parts[3].isdigit():
                return None
            result["number"] = parts[3]

        return result
    except (ValueError, AttributeError):
        return None


def _github_error(response):
    """Return a useful error code for common GitHub API failures."""
    if response.status_code == 401:
        return "ERROR:401"
    if response.status_code == 403:
        return "ERROR:403"
    if response.status_code == 404:
        return "ERROR:404"
    return "ERROR:UNKNOWN"


def get_pr_diff(pr_url):
    """Fetch a pull request diff from GitHub."""
    details = _parse_github_url(pr_url, is_pr=True)
    if not details:
        print("Invalid GitHub pull request URL.")
        return "ERROR:INVALID"

    owner = details["owner"]
    repo = details["repo"]
    number = details["number"]

    print(f"Fetching PR #{number} from {owner}/{repo}...")

    api_url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}"

    try:
        response = requests.get(
            api_url,
            headers=_github_headers("application/vnd.github.diff"),
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            print(f"GitHub returned status {response.status_code}.")
            return _github_error(response)

        diff = response.text
        if not diff.strip():
            print("The pull request diff is empty.")
            return "ERROR:EMPTY"

        print("Pull request diff fetched successfully.")
        if len(diff) > MAX_DIFF_CHARS:
            print("Warning: the diff is large; this review will use a partial diff.")
            return "WARNING:" + diff

        return diff

    except requests.RequestException as exc:
        print(f"Could not fetch pull request: {exc}")
        return "ERROR:NETWORK"


def get_pr_info(pr_url):
    """Return basic pull request information."""
    details = _parse_github_url(pr_url, is_pr=True)
    if not details:
        return None

    owner = details["owner"]
    repo = details["repo"]
    number = details["number"]

    try:
        response = requests.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}",
            headers=_github_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            return None

        data = response.json()
        return {
            "title": data.get("title", "Untitled PR"),
            "author": data.get("user", {}).get("login", "Unknown"),
            "date": data.get("created_at", "")[:10],
            "repo": f"{owner}/{repo}",
            "number": number,
            "state": data.get("state", "unknown"),
        }

    except (requests.RequestException, ValueError, KeyError):
        return None


def _call_ai(prompt, system_message=None):
    """Call the configured Groq model and return its response text."""
    if client is None:
        raise RuntimeError(
            "GROQ_API_KEY is missing. Add it to your environment variables."
        )

    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.1,
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("The AI returned an empty response.")

    return content


def review_code(diff):
    """Review a PR diff with evidence-based and beginner-friendly findings."""
    print("\nSending pull request diff to the AI reviewer...")
    print(f"Diff length: {len(diff)} characters")

    if diff.startswith("ERROR:"):
        return f"PR review could not start. GitHub returned: {diff}"

    was_truncated = len(diff) > MAX_DIFF_CHARS
    if diff.startswith("WARNING:"):
        diff = diff[len("WARNING:"):]

    truncated_diff = len(diff) > MAX_DIFF_CHARS
    was_truncated = was_truncated or truncated_diff
    diff_for_review = diff[:MAX_DIFF_CHARS]

    completeness_note = (
        "IMPORTANT: The supplied diff is partial because it exceeded the "
        "review input limit. Do not treat the review as complete. Mention "
        "that some changes may not have been examined."
        if was_truncated
        else "The diff was within the configured character limit. This does "
        "not guarantee that all relevant repository context is available."
    )

    prompt = f"""
You are a conservative, evidence-driven code reviewer who explains
software problems to beginners.

Your job is to identify real, actionable problems—not to invent findings.

REVIEW RULES:
1. Base every finding on evidence in the supplied diff.
2. Never invent filenames, functions, variables, line numbers, or code.
3. Cite the actual file path and changed line number when they can be
   determined from the diff. If the exact line is unavailable, say so.
4. Include a short, exact quote from the diff as evidence for each finding.
5. Explain why that evidence demonstrates a defect. A suspicious-looking
   line by itself is not proof that the program is broken.
6. Distinguish confirmed defects from concerns that need more context.
7. If a concern cannot be verified from the diff, place it under
   "Needs Verification", not under confirmed bugs.
8. Do not claim that tests were run or code was executed.
9. Avoid duplicate findings and purely stylistic complaints.
10. Do not label normal design choices as bugs without evidence.
11. Do not recommend a fix unless it addresses the stated problem.
12. Use simple English. Explain technical terms the first time they appear.
13. For each finding, explain what the code does, what could go wrong,
    why it matters to a user or developer, and how to fix it.
14. Do not invent security, performance, or edge-case problems.
15. If no concrete bug is supported, say that no confirmed bug was
    identified in the supplied diff. Do not claim the code is bug-free.

{completeness_note}

OUTPUT FORMAT:

# 1. PR Summary
Explain what the changes appear to do in simple English.

# 2. What Looks Good
Mention only improvements that are supported by the diff.

# 3. Confirmed Findings
For each supported defect, provide:

### Finding: [short descriptive title]
- Severity: Critical / High / Medium / Low
- Location: file and changed line, if available
- Evidence: exact short quote from the supplied diff
- What this code does: explain the relevant behavior simply
- Why it is a problem: explain the specific reasoning
- Real-world impact: describe what could happen
- Suggested fix: give a practical correction
- Confidence: High / Medium / Low

Do not include a finding here unless the supplied evidence supports it.

# 4. Needs Verification
For each plausible but unconfirmed concern, explain what is suspicious,
what is not yet known, and which surrounding code or test would verify it.
Do not present these as confirmed bugs.

# 5. Tests to Consider
Suggest specific tests relevant to the changed behavior.
Do not claim these tests were executed.

# 6. Final Verdict
Choose Request Changes, Needs Discussion, or Approve.
Explain the verdict briefly and state the limitations of this review.
An Approve verdict means no significant issue was identified in the
available evidence; it does not guarantee correctness.

PULL REQUEST DIFF:
{diff_for_review}
"""

    system_message = (
        "You are a careful reviewer. Evidence must support each finding. "
        "State uncertainty openly. Explain technical concepts in plain "
        "English. Never fabricate evidence or claim unperformed tests."
    )

    try:
        return _call_ai(prompt, system_message)
    except Exception as exc:
        print(f"AI review failed: {exc}")
        return (
            "The AI review could not be completed. Check the Render logs "
            "for the underlying error and verify the Groq configuration."
        )


def save_review(pr_url, review):
    """Save a pull request review as a Markdown file."""
    details = _parse_github_url(pr_url, is_pr=True)
    if not details:
        raise ValueError("Cannot save review: invalid GitHub pull request URL.")

    owner = details["owner"]
    repo = details["repo"]
    number = details["number"]
    filename = f"review_{owner}_{repo}_PR{number}.md"

    with open(filename, "w", encoding="utf-8") as file:
        file.write(f"# AI Code Review — {owner}/{repo} PR #{number}\n\n")
        file.write(review)

    print(f"Review saved to: {filename}")
    return filename


def get_repo_files(repo_url):
    """Fetch a limited, documented sample of source files from a repository."""
    details = _parse_github_url(repo_url)
    if not details:
        print("Invalid GitHub repository URL.")
        return "ERROR:INVALID"

    owner = details["owner"]
    repo = details["repo"]
    print(f"Fetching repository files from {owner}/{repo}...")

    try:
        repo_response = requests.get(
            f"{GITHUB_API}/repos/{owner}/{repo}",
            headers=_github_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        if repo_response.status_code != 200:
            print(f"Could not access repository: {repo_response.status_code}")
            return _github_error(repo_response)

        default_branch = repo_response.json().get("default_branch", "main")

        tree_response = requests.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/"
            f"{default_branch}?recursive=1",
            headers=_github_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        if tree_response.status_code != 200:
            print(f"Could not fetch repository tree: {tree_response.status_code}")
            return _github_error(tree_response)

        tree_data = tree_response.json()
        tree = tree_data.get("tree", [])

        code_files = [
            item for item in tree
            if item.get("type") == "blob"
            and item.get("path", "").lower().endswith(CODE_EXTENSIONS)
            and not any(
                part in IGNORED_PATH_PARTS
                for part in item.get("path", "").split("/")
            )
        ]

        # Prioritize application code over generated or documentation files.
        code_files.sort(
            key=lambda item: (
                item.get("path", "").lower().endswith(
                    (".html", ".css", ".json")
                ),
                item.get("path", "").count("/"),
                item.get("path", ""),
            )
        )

        selected_files = code_files[:MAX_REPO_FILES]
        if not selected_files:
            return "ERROR:NOFILES"

        sections = [
            f"Repository: {owner}/{repo}\n"
            f"Default branch: {default_branch}\n"
            f"Source files found: {len(code_files)}\n"
            f"Files selected for review: {len(selected_files)}\n"
            f"File selection limit: {MAX_REPO_FILES}\n"
            "IMPORTANT: This is a partial repository sample, not the full "
            "codebase. Findings must not assume unprovided files are absent."
        ]

        total_chars = sum(len(section) for section in sections)
        fetched_count = 0

        for item in selected_files:
            path = item["path"]
            raw_url = (
                f"https://raw.githubusercontent.com/{owner}/{repo}/"
                f"{default_branch}/{path}"
            )

            file_response = requests.get(
                raw_url,
                headers=_github_headers("application/vnd.github.raw+json"),
                timeout=REQUEST_TIMEOUT,
            )
            if file_response.status_code != 200:
                print(f"Skipping inaccessible file: {path}")
                continue

            content = file_response.text
            is_truncated = len(content) > MAX_FILE_CHARS
            content = content[:MAX_FILE_CHARS]

            section = (
                f"\n\n{'=' * 60}\n"
                f"FILE: {path}\n"
                f"File content truncated: {is_truncated}\n"
                f"{'=' * 60}\n"
                f"{content}\n"
            )

            if total_chars + len(section) > MAX_REVIEW_INPUT_CHARS:
                sections.append(
                    "\nRepository sample limit reached. Additional files "
                    "were not included; do not assume they are missing."
                )
                break

            sections.append(section)
            total_chars += len(section)
            fetched_count += 1

        if fetched_count == 0:
            return "ERROR:NOFILES"

        print(
            f"Fetched {fetched_count} source files "
            f"from {owner}/{repo}."
        )
        return "\n".join(sections)

    except requests.RequestException as exc:
        print(f"Repository fetch failed: {exc}")
        return "ERROR:NETWORK"
    except (ValueError, KeyError) as exc:
        print(f"Could not process repository response: {exc}")
        return "ERROR:UNKNOWN"



    prompt = f"""
You are a careful software reviewer and a patient programming mentor.
Your audience may be a beginner who does not understand the code yet.

Your goal is not only to find bugs. You must first teach the reader
what the supplied code is about, what it does, and how it works.

IMPORTANT LIMITATIONS:
The supplied input is only a sample of the repository. Some files may
be omitted and some file contents may be truncated. The metadata in
the input identifies the files and truncation where available.
Never conclude that a function, validation check, security control, or
configuration is missing from the entire project just because it does
not appear in this sample.

EVIDENCE RULES:
1. Every confirmed finding must quote a short, exact piece of supplied
   source code and name the file it came from.
2. Include a line number only when it can be reliably established.
   Otherwise say "line number not available".
3. Explain why the quoted code causes a specific problem.
4. A possible risk is not automatically a bug. Put unverified concerns
   in the Needs Verification section.
5. Do not invent code, filenames, dependencies, execution results, or tests.
6. Do not claim the project is production-ready or unsafe without
   enough evidence.
7. Do not report missing security controls unless the provided context
   supports the claim.
8. Explain what the code does, why it matters, and how to improve it.
9. Avoid duplicates, vague advice, and style-only issues.
10. If the evidence is insufficient, state the limitation explicitly.
11. Use simple English and explain technical terms when first introduced.
12. Never assume the reader already understands the project's code.
13. Clearly distinguish confirmed bugs from possible risks and suggestions.
14. Give practical fixes, with corrected code when the supplied context
    is sufficient. Explain what the change accomplishes.
15. Do not repeat the same issue in multiple sections unnecessarily.

OUTPUT FORMAT:

# 1. What Is This Project or Code About?
Start with a clear, beginner-friendly explanation BEFORE listing bugs.
Explain:
- What the project or supplied code is intended to do.
- The main topic or purpose of the code.
- Who might use it and what problem it solves, if supported by evidence.
- The programming languages, frameworks, and technologies visible
  in the supplied sample.
- What is known versus what cannot be determined from the sample.

Use a simple real-world analogy when it genuinely helps.
Do not guess the purpose when the evidence does not support it.

# 2. How Does the Code Work?
Explain the main flow in simple steps:
- Where the process starts, if identifiable.
- What the important files, functions, or components do.
- How those parts interact, when supported by evidence.
- How data moves through the code, when visible.

Explain unfamiliar technical terms briefly.
Do not invent missing steps or claim to understand omitted code.

# 3. How Is the Project Organized?
Describe only files and relationships supported by the sample.
Explain the role of important folders and files in plain English.
Mention that not all files may have been included or fully inspected.

# 4. Issues Found
Start with a short summary such as:
"The review found N confirmed issues and M potential risks."
Count findings accurately. Do not call an unverified concern a confirmed bug.

For every confirmed finding, use:

### Finding N — [clear, simple title]
- Severity: Critical / High / Medium / Low
- File:
- Line: if reliably known; otherwise "line number not available"
- Evidence: exact short code quote
- What this means: explain the issue in simple English
- Real-world example: show when a user might encounter it
- Why it matters: explain the concrete consequence
- Suggested fix: provide an actionable solution
- Corrected code: include when enough context is available
- Confidence: High / Medium / Low

Prioritize problems that can cause incorrect results, crashes, data loss,
security weaknesses, or broken features. Do not exaggerate severity.

If no confirmed issues can be established, say so explicitly.

# 5. Potential Issues — Needs Verification
List concerns that cannot be confirmed from the supplied sample.
For each one, explain:
- What might be wrong.
- Why it matters.
- Which file, code, or test is needed to verify it.

Do not present these concerns as confirmed bugs.

# 6. Good Practices Observed
Mention only good practices actually visible in the supplied code.
Explain why each practice is useful.
Do not invent praise just to fill this section.

# 7. Recommended Improvements
Give a prioritized action plan:
1. Fix confirmed high-impact issues first.
2. Address lower-priority confirmed issues next.
3. Investigate unverified risks.
4. Consider optional improvements afterward.

Explain the purpose of each step in simple English.
Clearly label optional suggestions.

# 8. Tests to Consider
Suggest practical tests that could check the findings.
Explain what each test checks and what a successful result looks like.
Never claim a test was run unless the input provides evidence of that.

# 9. Overall Assessment
Summarize:
- What the code appears to do.
- The most important confirmed findings.
- The most important unknowns.
- The best next action for the developer.

Use clear, direct language. Do not overwhelm beginners with jargon.
Do not declare the entire project safe, unsafe, or production-ready
based only on a partial sample.

REPOSITORY SAMPLE:
{code[:MAX_REVIEW_INPUT_CHARS]}
"""


    try:
        return _call_ai(
            prompt,
            "Be evidence-based, cautious about incomplete context, "
            "and beginner-friendly. Never invent findings.",
        )
    except Exception as exc:
        print(f"Repository AI review failed: {exc}")
        return (
            "The repository review could not be completed. Check the "
            "Render logs for the underlying error and verify Groq settings."
        )


@click.command()
@click.option("--url", prompt="Paste a GitHub PR URL", help="GitHub PR URL to review")
def main(url):
    """AI Code Review Assistant — reviews a GitHub pull request."""
    print("=== AI Code Review Assistant ===\n")

    diff = get_pr_diff(url)

    if not diff or diff.startswith("ERROR:"):
        print(f"Could not review this pull request: {diff}")
        return

    review = review_code(diff)

    print("=" * 50)
    print("AI CODE REVIEW RESULTS")
    print("=" * 50)
    print(review)
    print("=" * 50)

    try:
        save_review(url, review)
    except (OSError, ValueError) as exc:
        print(f"Could not save review: {exc}")


if __name__ == "__main__":
    main()
