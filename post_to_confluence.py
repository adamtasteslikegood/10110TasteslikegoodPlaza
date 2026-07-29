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

# See generate_report.py: .env carries ATLASSIAN_API_TOKEN_BASE64, while this
# script required the longer ..._USEREMAIL name until 2026-07-28 and so raised a
# KeyError against a correctly-populated .env. Accept either name.
TOKEN_VARS = ("ATLASSIAN_API_TOKEN_BASE64", "ATLASSIAN_API_TOKEN_BASE64_USEREMAIL")
auth_token = next((env_vars[k] for k in TOKEN_VARS if env_vars.get(k)), None)
if not auth_token or not env_vars.get("ATLASSIAN_URL"):
    print(
        "Missing required configuration: "
        + " or ".join(TOKEN_VARS)
        + ", ATLASSIAN_URL. Set them as environment variables or in ./.env."
    )
    sys.exit(1)

url_base = f"https://{env_vars['ATLASSIAN_URL']}"
# Space PLZA, "10110 Tasteslikegood Plaza" — this project's own Confluence space.
# Reports previously landed under two pages in space TLG ("Tasteslikegood.org"),
# the sibling product's space: 15925249 "Sprint 0 Plan - Agile Operating System"
# and 15695959 "Scrum Bootstrap And Board Plan". Both are TLG planning documents,
# not Plaza report parents. There is no fallback now on purpose: a fallback that
# silently writes into another product's space is how the reports ended up there.
parent_page_id = "11075756"


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
    print(f"Failed to get parent page {parent_page_id} (space PLZA)")
    sys.exit(1)

space_id = page_data["spaceId"]

with open("report.md") as f:
    md = f.read()


def render_inline_markdown(text):
    rendered_parts = []
    last_index = 0
    for match in re.finditer(r"\*\*(.+?)\*\*", text):
        rendered_parts.append(html.escape(text[last_index : match.start()]))
        rendered_parts.append(f"<strong>{html.escape(match.group(1))}</strong>")
        last_index = match.end()
    rendered_parts.append(html.escape(text[last_index:]))
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
    resolved_base_url = links.get("base", url_base)
    if resolved_base_url.startswith("/"):
        resolved_base_url = urllib.parse.urljoin(url_base, resolved_base_url)
    url = (
        urllib.parse.urljoin(resolved_base_url, webui_path)
        if webui_path
        else f"{url_base}/wiki/pages/{new_page['id']}"
    )
    print(f"Successfully created Confluence page! Page URL: {url}")
else:
    print("Failed to create page")
