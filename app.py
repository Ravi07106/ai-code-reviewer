from flask import Flask, render_template, request
from reviewer import get_pr_diff, review_code, save_review, get_pr_info

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    review = None
    error = None
    pr_url = None

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
        elif diff:
            review = review_code(diff)
            save_review(pr_url, review)
            pr_info = get_pr_info(pr_url)
        else:
            error = "❌ Could not fetch PR. Check the URL and try again."

    return render_template("index.html", review=review, error=error, pr_url=pr_url, pr_info=pr_info)


if __name__ == "__main__":
    app.run(debug=True)