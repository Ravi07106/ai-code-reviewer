from flask import Flask, render_template, request, make_response
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit
from xml.sax.saxutils import escape

from reviewer import (
    get_pr_diff,
    review_code,
    save_review,
    get_pr_info,
    get_repo_files,
    review_repo
)

import os
import json
import io
from datetime import datetime

app = Flask(__name__)

HISTORY_FILE = "history.json"


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

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

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# --------------------------------------------------
# HOME PAGE: Landing page
# --------------------------------------------------

@app.route("/")
def home():
    return render_template("landing.html")


# --------------------------------------------------
# REVIEW SELECTION PAGE
# --------------------------------------------------

@app.route("/review")
def review_options():
    return render_template("review_options.html")


# --------------------------------------------------
# PULL REQUEST REVIEW
# --------------------------------------------------

@app.route("/pr-review", methods=["GET", "POST"])
def index():
    review = None
    error = None
    pr_url = None
    pr_info = None
    large_pr = False

    history = load_history()

    if request.method == "POST":
        pr_url = (request.form.get("pr_url") or "").strip()

        if not pr_url:
            error = "Please enter a GitHub pull request URL."

        else:
            diff = get_pr_diff(pr_url)

            if diff == "ERROR:404":
                error = (
                    "❌ PR not found! Make sure the URL is correct "
                    "and the pull request exists."
                )

            elif diff == "ERROR:401":
                error = (
                    "❌ Invalid GitHub token! Please check your "
                    ".env file."
                )

            elif diff == "ERROR:403":
                error = (
                    "❌ Access forbidden! You don't have permission "
                    "to access this pull request."
                )

            elif diff == "ERROR:UNKNOWN":
                error = "❌ Something went wrong! Please try again."

            elif diff == "ERROR:INVALID":
                error = (
                    "❌ Invalid URL! Please use this format: "
                    "https://github.com/owner/repo/pull/123"
                )

            elif diff:
                large_pr = diff.startswith("WARNING:")

                if large_pr:
                    diff = diff[8:]

                review = review_code(diff)
                pr_info = get_pr_info(pr_url)

                save_review(pr_url, review)
                save_history(pr_info, review)

                history = load_history()

            else:
                error = (
                    "❌ Could not retrieve the pull request changes. "
                    "Please verify the URL and try again."
                )

    return render_template(
        "pr_review.html",
        review=review,
        error=error,
        pr_url=pr_url,
        pr_info=pr_info,
        history=history,
        large_pr=large_pr
    )


# --------------------------------------------------
# REPOSITORY REVIEW
# --------------------------------------------------

@app.route("/repo-review", methods=["GET", "POST"])
def repo_review():
    review = None
    error = None
    repo_url = None

    if request.method == "POST":
        repo_url = (request.form.get("repo_url") or "").strip()

        if not repo_url:
            error = "Please enter a GitHub repository URL."

        else:
            code = get_repo_files(repo_url)

            if code == "ERROR:INVALID":
                error = (
                    "❌ Invalid URL! Please use this format: "
                    "https://github.com/owner/repo"
                )

            elif code == "ERROR:404":
                error = (
                    "❌ Repository not found! Make sure the URL "
                    "is correct and the repository is accessible."
                )

            elif code == "ERROR:NOFILES":
                error = "❌ No code files found in this repository!"

            elif code:
                review = review_repo(code)

            else:
                error = (
                    "❌ Could not retrieve the repository files. "
                    "Please verify the URL and try again."
                )

    return render_template(
        "repo_review.html",
        review=review,
        error=error,
        repo_url=repo_url
    )


# --------------------------------------------------
# DOWNLOAD PULL REQUEST REVIEW AS PDF
# --------------------------------------------------

@app.route("/download-pdf", methods=["POST"])
def download_pdf():
    review = request.form.get("review", "")
    pr_title = request.form.get("pr_title", "PR Review")
    pr_repo = request.form.get("pr_repo", "")

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(
        Paragraph("AI Code Review", styles["Title"])
    )

    story.append(Spacer(1, 0.2 * inch))

    story.append(
        Paragraph(escape(pr_title), styles["Heading2"])
    )

    story.append(
        Paragraph(escape(pr_repo), styles["Normal"])
    )

    story.append(Spacer(1, 0.3 * inch))

    # Preserve line breaks and safely escape HTML characters.
    for line in review.split("\n"):
        if line.strip():
            story.append(
                Paragraph(escape(line), styles["Normal"])
            )
            story.append(Spacer(1, 0.08 * inch))

    doc.build(story)
    buffer.seek(0)

    response = make_response(buffer.getvalue())

    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        'attachment; filename="review.pdf"'
    )

    return response


# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
