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

required_vars = ["ATLASSIAN_API_TOKEN_BASE64_USEREMAIL", "ATLASSIAN_URL"]
missing_vars = [key for key in required_vars if not env_vars.get(key)]
if missing_vars:
    print(
        "Missing required configuration: "
        + ", ".join(missing_vars)
        + ". Set them as environment variables"
        + (" or provide them in ./.env." if not os.path.exists(env_file) else ".")
    )
    sys.exit(1)

auth_token = env_vars["ATLASSIAN_API_TOKEN_BASE64_USEREMAIL"]
url_base = f"https://{env_vars['ATLASSIAN_URL']}"


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
jql = 'project = "TO" AND updated >= -7d ORDER BY status, priority DESC'
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
issues_data = jira_request("POST", "/rest/api/3/search", payload)

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
