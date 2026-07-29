import datetime
import html
import json
import os
import urllib.request
import sys

env_vars = dict(os.environ)
env_file = "./.env"
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                key, val = line.strip().split("=", 1)
                if key not in env_vars:
                    env_vars[key] = val

# The credential is base64("email:token"). Two names for it are in circulation:
# ATLASSIAN_API_TOKEN_BASE64 is what .env actually carries; the longer
# ..._USEREMAIL name is what this script required until 2026-07-28, which meant
# a correctly-populated .env still failed with a KeyError. Accept either.
TOKEN_VARS = ("ATLASSIAN_API_TOKEN_BASE64", "ATLASSIAN_API_TOKEN_BASE64_USEREMAIL")
auth_token = next((env_vars[k] for k in TOKEN_VARS if env_vars.get(k)), None)

missing_vars = [key for key in ("ATLASSIAN_URL", "ATLASSIAN_JIRA_PROJECT_KEY") if not env_vars.get(key)]
if not auth_token:
    missing_vars.insert(0, " or ".join(TOKEN_VARS))
if missing_vars:
    print(
        "Missing required configuration: "
        + ", ".join(missing_vars)
        + ". Set them as environment variables"
        + (" or provide them in ./.env." if not os.path.exists(env_file) else ".")
    )
    sys.exit(1)

url_base = f"https://{env_vars['ATLASSIAN_URL']}"
# Read the board from config rather than hard-coding it. This was pinned to "TO"
# until 2026-07-28 -- the other site's service board -- so the report was headed
# "10110 Tasteslikegood Plaza" while every row in it was recipe-app work.
project_key = env_vars["ATLASSIAN_JIRA_PROJECT_KEY"]


def jira_request(method, endpoint, payload=None):
    url = f"{url_base}{endpoint}"
    headers = {
        "Authorization": f"Basic {auth_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"Error calling {url}: {e}")
        return None


# Get issues
jql = f'project = "{project_key}" AND updated >= -7d ORDER BY status, priority DESC'
payload = {
    "jql": jql,
    "maxResults": 100,
    "fields": [
        "summary",
        "status",
        "priority",
        "assignee",
        "updated",
        "created",
        "resolutiondate",
    ],
}
# /rest/api/3/search was retired by Atlassian and now answers 410 Gone; the
# replacement is /rest/api/3/search/jql. It still returns an "issues" array, so
# nothing below changes -- it drops "total"/"startAt" for "isLast"/"nextPageToken",
# neither of which this script reads. Verified against the live site 2026-07-28.
issues_data = jira_request("POST", "/rest/api/3/search/jql", payload)

if not issues_data or "issues" not in issues_data:
    print("No issues found or error occurred.")
    sys.exit(1)

issues = issues_data["issues"]
done = []
in_progress = []
blocked = []
todo = []

for issue in issues:
    status = issue["fields"]["status"]["name"].lower()
    if status == "done":
        done.append(issue)
    elif status == "blocked":
        blocked.append(issue)
    elif status in ["in progress", "in review"]:
        in_progress.append(issue)
    else:
        todo.append(issue)

# Build Markdown
today = datetime.date.today().strftime("%B %d, %Y")
md = f"## Status Report - 10110 Tasteslikegood Plaza - {today}\n\n"
md += f"**Total Issues Updated This Week**: {len(issues)}\n"
md += f"**Completed**: {len(done)} | "
md += f"**In Progress**: {len(in_progress)} | "
md += f"**Blocked**: {len(blocked)} | "
md += f"**To Do / Other**: {len(todo)}\n\n"


def format_issue(issue):
    key = issue["key"]
    summary = html.escape(issue["fields"]["summary"])
    assignee = (
        html.escape(issue["fields"]["assignee"]["displayName"])
        if issue["fields"]["assignee"]
        else "Unassigned"
    )
    priority = html.escape(issue["fields"]["priority"]["name"])
    safe_key = html.escape(key)
    return f"- [{safe_key}]({url_base}/browse/{key}): {summary} (Assignee: {assignee}, Priority: {priority})"


if done:
    md += "### Completed Issues\n"
    for i in done:
        md += format_issue(i) + "\n"
    md += "\n"

if in_progress:
    md += "### In Progress\n"
    for i in in_progress:
        md += format_issue(i) + "\n"
    md += "\n"

if blocked:
    md += "### Blocked Issues\n"
    for i in blocked:
        md += format_issue(i) + "\n"
    md += "\n"

if todo:
    md += "### To Do / Other Updates\n"
    for i in todo:
        md += format_issue(i) + "\n"
    md += "\n"

with open("report.md", "w") as f:
    f.write(md)

print("Report generated in report.md")
