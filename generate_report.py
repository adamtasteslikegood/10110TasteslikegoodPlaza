import os, json, urllib.request, urllib.parse, datetime

env_vars = {}
with open('./.env') as f:
    for line in f:
        if line.strip() and not line.startswith('#'):
            key, val = line.strip().split('=', 1)
            env_vars[key] = val

auth_token = env_vars['ATLASSIAN_API_TOKEN_BASE64_USEREMAIL']
url_base = f"https://{env_vars['ATLASSIAN_URL']}"

def jira_request(method, endpoint, payload=None):
    url = f"{url_base}{endpoint}"
    headers = {
        "Authorization": f"Basic {auth_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    data = json.dumps(payload).encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error calling {url}: {e}")
        return None

# Get issues
jql = 'project = "TO" AND updated >= -7d ORDER BY status, priority DESC'
payload = {
    "jql": jql,
    "maxResults": 100,
    "fields": ["summary", "status", "priority", "assignee", "updated", "created", "resolutiondate"]
}
issues_data = jira_request("POST", "/rest/api/3/search/jql", payload)

if not issues_data or 'issues' not in issues_data:
    print("No issues found or error occurred.")
    exit(1)

issues = issues_data['issues']
done = []
in_progress = []
blocked = []
todo = []

for issue in issues:
    status = issue['fields']['status']['name'].lower()
    if status == 'done':
        done.append(issue)
    elif status == 'blocked':
        blocked.append(issue)
    elif status in ['in progress', 'in review']:
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
    key = issue['key']
    summary = issue['fields']['summary']
    assignee = issue['fields']['assignee']['displayName'] if issue['fields']['assignee'] else 'Unassigned'
    priority = issue['fields']['priority']['name']
    return f"- [{key}]({url_base}/browse/{key}): {summary} (Assignee: {assignee}, Priority: {priority})"

if done:
    md += "### Completed Issues\n"
    for i in done: md += format_issue(i) + "\n"
    md += "\n"

if in_progress:
    md += "### In Progress\n"
    for i in in_progress: md += format_issue(i) + "\n"
    md += "\n"

if blocked:
    md += "### Blocked Issues\n"
    for i in blocked: md += format_issue(i) + "\n"
    md += "\n"

if todo:
    md += "### To Do / Other Updates\n"
    for i in todo: md += format_issue(i) + "\n"
    md += "\n"

with open('report.md', 'w') as f:
    f.write(md)

print("Report generated in report.md")
