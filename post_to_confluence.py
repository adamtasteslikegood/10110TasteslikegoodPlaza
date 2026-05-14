import datetime
import html
import json
import re
import sys
import urllib.parse
import urllib.request

env_vars = {}
with open("./.env") as f:
    for line in f:
        if line.strip() and not line.startswith("#"):
            key, val = line.strip().split("=", 1)
            env_vars[key] = val

auth_token = env_vars["ATLASSIAN_API_TOKEN_BASE64_USEREMAIL"]
url_base = f"https://{env_vars['ATLASSIAN_URL']}"
parent_page_id = "15925249"


def confluence_request(method, endpoint, payload=None):
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
        if hasattr(e, "read"):
            print(f"Error response: {e.read().decode('utf-8')}")
        print(f"Error calling {url}: {e}")
        return None


page_data = confluence_request("GET", f"/wiki/api/v2/pages/{parent_page_id}")
if not page_data:
    parent_page_id = "15695959"
    page_data = confluence_request("GET", f"/wiki/api/v2/pages/{parent_page_id}")
    if not page_data:
        print("Failed to get both parent pages")
        sys.exit(1)

space_id = page_data["spaceId"]

with open("report.md") as f:
    md = f.read()


def render_inline_markdown(text):
    parts = text.split("**")
    rendered_parts = []
    for idx, part in enumerate(parts):
        escaped_part = html.escape(part)
        if idx % 2 == 1:
            rendered_parts.append(f"<strong>{escaped_part}</strong>")
        else:
            rendered_parts.append(escaped_part)
    return "".join(rendered_parts)


rendered_lines = []
in_list = False
for line in md.splitlines():
    if not line.strip():
        if in_list:
            rendered_lines.append("</ul>")
            in_list = False
        continue

    if line.startswith("## "):
        if in_list:
            rendered_lines.append("</ul>")
            in_list = False
        rendered_lines.append(f"<h2>{render_inline_markdown(line[3:])}</h2>")
        continue

    if line.startswith("### "):
        if in_list:
            rendered_lines.append("</ul>")
            in_list = False
        rendered_lines.append(f"<h3>{render_inline_markdown(line[4:])}</h3>")
        continue

    match = re.match(r"- \[([^\]]+)\]\(([^)]+)\):\s*(.*)", line)
    if match:
        if not in_list:
            rendered_lines.append("<ul>")
            in_list = True
        key, issue_url, detail = match.groups()
        safe_url = html.escape(issue_url, quote=True)
        rendered_lines.append(
            f'<li><a href="{safe_url}">{render_inline_markdown(key)}</a>: {render_inline_markdown(detail)}</li>'
        )
        continue

    if in_list:
        rendered_lines.append("</ul>")
        in_list = False
    rendered_lines.append(f"<p>{render_inline_markdown(line)}</p>")

if in_list:
    rendered_lines.append("</ul>")

html_output = "".join(rendered_lines)

today = datetime.date.today().strftime("%B %d, %Y")
now = datetime.datetime.now().strftime("%H:%M:%S")
title = f"10110 Tasteslikegood Plaza - Status Report - {today} {now}"

payload = {
    "spaceId": space_id,
    "status": "current",
    "title": title,
    "parentId": parent_page_id,
    "body": {"representation": "storage", "value": f"<div>{html_output}</div>"},
}

new_page = confluence_request("POST", "/wiki/api/v2/pages", payload)
if new_page and "id" in new_page:
    links = new_page.get("_links", {})
    webui_path = links.get("webui")
    base_url = links.get("base", url_base)
    if base_url.startswith("/"):
        base_url = urllib.parse.urljoin(url_base, base_url)
    url = (
        urllib.parse.urljoin(base_url, webui_path)
        if webui_path
        else f"{url_base}/wiki/pages/{new_page['id']}"
    )
    print(f"Successfully created Confluence page! Page URL: {url}")
else:
    print("Failed to create page")
