from flask import Flask, render_template, request, make_response
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
from reviewer import get_pr_diff, review_code, save_review, get_pr_info, get_repo_files, review_repo
import os
import json
import io
from datetime import datetime

app = Flask(__name__)

HISTORY_FILE = "history.json"


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_history(pr_info, review):
    history = load_history()
    history.insert(0, {
        "title": pr_info["title"] if pr_info else "Unknown PR",
        "repo": pr_info["repo"] if pr_info else "Unknown",
        "number": pr_info["number"] if pr_info else "?",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "review": review
    })
    history = history[:10]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)


@app.route("/", methods=["GET", "POST"])
def index():
    review = None
    error = None
    pr_url = None
    pr_info = None
    large_pr = False
    history = load_history()

    if request.method == "POST":
        pr_url = request.form.get("pr_url")
        diff = get_pr_diff(pr_url)

        if diff == "ERROR:404":
            error = "❌ PR not found! Make sure the URL is correct and the PR exists."
        elif diff == "ERROR:401":
            error = "❌ Invalid GitHub token! Please check your .env file."
        elif diff == "ERROR:403":
            error = "❌ Access forbidden! You don't have permission to access this PR."
        elif diff == "ERROR:UNKNOWN":
            error = "❌ Something went wrong! Please try again."
        elif diff == "ERROR:INVALID":
            error = "❌ Invalid URL! Please use format: https://github.com/owner/repo/pull/123"
        elif diff:
            large_pr = diff.startswith("WARNING:")
            if large_pr:
                diff = diff[8:]
            review = review_code(diff)
            pr_info = get_pr_info(pr_url)
            save_review(pr_url, review)
            save_history(pr_info, review)
            history = load_history()

    return render_template("index.html", review=review, error=error,
                           pr_url=pr_url, pr_info=pr_info,
                           history=history, large_pr=large_pr)


# 🔹 New route for repo review
@app.route("/repo-review", methods=["GET", "POST"])
def repo_review():
    review = None
    error = None
    repo_url = None

    if request.method == "POST":
        repo_url = request.form.get("repo_url")
        code = get_repo_files(repo_url)

        if code == "ERROR:INVALID":
            error = "❌ Invalid URL! Please use format: https://github.com/owner/repo"
        elif code == "ERROR:404":
            error = "❌ Repo not found! Make sure the URL is correct."
        elif code == "ERROR:NOFILES":
            error = "❌ No code files found in this repo!"
        elif code:
            review = review_repo(code)

    return render_template("repo_review.html", review=review,
                           error=error, repo_url=repo_url)


@app.route("/download-pdf", methods=["POST"])
def download_pdf():
    review = request.form.get("review")
    pr_title = request.form.get("pr_title")
    pr_repo = request.form.get("pr_repo")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            rightMargin=inch, leftMargin=inch,
                            topMargin=inch, bottomMargin=inch)

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("AI Code Review", styles['Title']))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(f"PR: {pr_title}", styles['Heading2']))
    story.append(Paragraph(f"Repo: {pr_repo}", styles['Normal']))
    story.append(Spacer(1, 0.3 * inch))

    for line in review.split('\n'):
        if line.strip():
            story.append(Paragraph(line, styles['Normal']))
            story.append(Spacer(1, 0.1 * inch))

    doc.build(story)
    buffer.seek(0)

    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=review.pdf'
    return response


if __name__ == "__main__":
    app.run(debug=True)