import os, json, urllib.request, urllib.parse, datetime, re

env_vars = {}
with open('./.env') as f:
    for line in f:
        if line.strip() and not line.startswith('#'):
            key, val = line.strip().split('=', 1)
            env_vars[key] = val

auth_token = env_vars['ATLASSIAN_API_TOKEN_BASE64_USEREMAIL']
url_base = f"https://{env_vars['ATLASSIAN_URL']}"
parent_page_id = "15925249"

def confluence_request(method, endpoint, payload=None):
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
        if hasattr(e, 'read'):
            print(f"Error response: {e.read().decode('utf-8')}")
        print(f"Error calling {url}: {e}")
        return None

page_data = confluence_request("GET", f"/wiki/api/v2/pages/{parent_page_id}")
if not page_data:
    parent_page_id = "15695959"
    page_data = confluence_request("GET", f"/wiki/api/v2/pages/{parent_page_id}")
    if not page_data:
        print("Failed to get both parent pages")
        exit(1)

space_id = page_data['spaceId']

with open('report.md') as f:
    md = f.read()

html = md
html = html.replace('## Status Report', '<h2>Status Report')
html = re.sub(r'<h2>Status Report(.*)\n', r'<h2>Status Report\1</h2>', html)
html = html.replace('### Completed Issues', '<h3>Completed Issues</h3>')
html = html.replace('### In Progress', '<h3>In Progress</h3>')
html = html.replace('### Blocked Issues', '<h3>Blocked Issues</h3>')
html = html.replace('### To Do / Other Updates', '<h3>To Do / Other Updates</h3>')
html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html)
html = re.sub(r'- \[([^\]]+)\]\(([^\)]+)\):\s*(.*)', r'<li><a href="\2">\1</a>: \3</li>', html)

first_li = html.find('<li>')
if first_li != -1:
    html = html[:first_li] + '<ul>' + html[first_li:]
last_li = html.rfind('</li>')
if last_li != -1:
    html = html[:last_li+5] + '</ul>' + html[last_li+5:]

html = html.replace('\n\n', '<br/><br/>').replace('\n', ' ')

today = datetime.date.today().strftime("%B %d, %Y")
now = datetime.datetime.now().strftime("%H:%M:%S")
title = f"10110 Tasteslikegood Plaza - Status Report - {today} {now}"

payload = {
    "spaceId": space_id,
    "status": "current",
    "title": title,
    "parentId": parent_page_id,
    "body": {
        "representation": "storage",
        "value": f"<div>{html}</div>"
    }
}

new_page = confluence_request("POST", "/wiki/api/v2/pages", payload)
if new_page and 'id' in new_page:
    page_id = new_page['id']
    url = f"{url_base}/wiki/spaces/{space_id}/pages/{page_id}"
    print(f"Successfully created Confluence page! Page URL: {url}")
else:
    print("Failed to create page")
