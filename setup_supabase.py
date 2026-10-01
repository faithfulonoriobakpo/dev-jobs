"""One-off Supabase setup for dev-jobs. Safe to re-run.

Uses the Supabase project shared with the nurse job finder. Needs, in .env.local (git-ignored):
  SUPABASE_ACCESS_TOKEN   personal access token (https://supabase.com/dashboard/account/tokens)
  SUPABASE_PROJECT_REF    the project's reference ID
  SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY   the project's URL and API keys

It then:
  1. creates the dev_ tables and access rules in supabase/schema.sql
  2. adds this dashboard's address to the project's allowed sign-in addresses (keeping the others)
  3. stores the URL and keys as GitHub Actions secrets on the dev-jobs repo (needs the gh CLI, signed in)

Keys are never printed.
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
API = "https://api.supabase.com/v1"
REPO = "faithfulonoriobakpo/dev-jobs"
DASHBOARD_URL = "https://faithfulonoriobakpo.github.io/dev-jobs/"


def read_env():
    env = {}
    path = ROOT / ".env.local"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                env[k.strip()] = v.strip().strip('"')
    return {**env, **{k: v for k, v in os.environ.items() if k.startswith("SUPABASE_")}}


def api(method, path, token, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "User-Agent": "dev-jobs-setup"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit(f"Supabase API {method} {path} failed: {e.code} {e.read().decode('utf-8', 'replace')[:400]}")


def main():
    env = read_env()
    missing = [k for k in ("SUPABASE_ACCESS_TOKEN", "SUPABASE_PROJECT_REF", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY") if not env.get(k)]
    if missing:
        sys.exit(f"Missing in .env.local: {', '.join(missing)}")
    token, ref = env["SUPABASE_ACCESS_TOKEN"], env["SUPABASE_PROJECT_REF"]

    project = api("GET", f"/projects/{ref}", token)
    print(f"Project: {project.get('name')}, status {project.get('status')}")
    if project.get("status") != "ACTIVE_HEALTHY":
        sys.exit("The project isn't active (paused?). Restore it in the Supabase dashboard, then re-run.")

    print("Creating dev_ tables and access rules...")
    api("POST", f"/projects/{ref}/database/query", token, {"query": (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")})
    tables = api("POST", f"/projects/{ref}/database/query", token, {"query":
        "select table_name from information_schema.tables where table_schema = 'public' and table_name like 'dev\\_%' order by 1"})
    print("  tables:", ", ".join(t["table_name"] for t in tables))

    auth = api("GET", f"/projects/{ref}/config/auth", token)
    allowed = [u for u in (auth.get("uri_allow_list") or "").split(",") if u]
    if DASHBOARD_URL not in allowed:
        api("PATCH", f"/projects/{ref}/config/auth", token, {"uri_allow_list": ",".join(allowed + [DASHBOARD_URL])})
        print(f"Added {DASHBOARD_URL} to the allowed sign-in addresses")

    gh = shutil.which("gh") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "gh-cli" / "bin" / "gh.exe")
    for name in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY"):
        subprocess.run([gh, "secret", "set", name, "--repo", REPO], input=env[name].encode(), check=True, stdout=subprocess.DEVNULL)
    print(f"Stored SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY as GitHub Actions secrets on {REPO}")


if __name__ == "__main__":
    main()
