
def review_code(diff):
    """Review a PR diff with evidence-based, conservative findings."""
    print("\n🤖 Sending code to Groq AI for review...\n")
    print(f"Diff length: {len(diff)}")

    prompt = f"""
You are a careful, evidence-driven code reviewer.

IMPORTANT RULES:
1. Review only what the supplied PR diff supports.
2. Never invent files, functions, variables, line numbers, or behavior.
3. Do not report a bug merely because something might be wrong.
4. For every issue, include:
   - Title
   - Severity: Critical, High, Medium, or Low
   - File path and changed line number, when available
   - Evidence: a short quote from the supplied diff
   - Explanation of why the evidence indicates a problem
   - Impact: what could happen if the issue is real
   - Suggested fix
   - Confidence: High, Medium, or Low
5. If the diff does not provide enough evidence, label the concern
   "Needs verification" and explain what additional context is needed.
6. Do not claim that unchanged code is defective unless the diff
   provides enough context to demonstrate the problem.
7. Do not invent security vulnerabilities, performance problems,
   or missing edge-case handling.
8. Avoid duplicate findings. Do not report style preferences as bugs.
9. If no concrete issue is supported, say so explicitly.
10. Do not claim you ran tests, executed code, or verified behavior.
    You have only the supplied diff unless other evidence is provided.

Write the review in this format:

# PR Summary
Explain the changes in simple English.

# What Looks Good
Mention only improvements supported by the diff.

# Findings
For each finding, use:
- Title:
- Severity:
- Location:
- Evidence:
- Why this is a problem:
- Real-world impact:
- Suggested fix:
- Confidence:

Separate confirmed issues from concerns needing verification.

# Missing Context
List any important files or surrounding code needed to verify concerns.
If none, say "No additional context identified."

# Tests to Consider
Suggest relevant tests without claiming they were executed.

# Final Verdict
Choose one:
- Request Changes: at least one well-supported, important defect.
- Needs Discussion: a significant concern requires more context.
- Approve: no significant defect was identified in the supplied diff.

An AI review is not proof that the code is correct or incorrect.

PR DIFF:
{diff[:8000]}
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {
                "role": "system",
                "content": (
                    "Be conservative, evidence-based, and explicit "
                    "about uncertainty. Never fabricate code evidence."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    return response.choices[0].message.content
