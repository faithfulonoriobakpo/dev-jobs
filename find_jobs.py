"""Find software engineering jobs a Nigeria-based senior frontend / full-stack developer can actually take:

  - remote roles open to candidates in Nigeria (worldwide, Africa/EMEA, or a time-zone window that covers Lagos)
  - roles in Nigeria
  - roles abroad that offer visa sponsorship or relocation

Sources (no keys needed): Himalayas, Remotive, Jobicy, We Work Remotely, Working Nomads, Remote OK, Arbeitnow,
Hacker News "Who is hiring", Hot Nigerian Jobs, Jobs in Nigeria. Optional: Adzuna (ADZUNA_APP_ID / ADZUNA_APP_KEY).

Each job gets a score against profile.json and a label, following the claude-job-agent rules:
  APPLY   strong match, location accessible
  REVIEW  worth a look, but something needs checking (unclear remote restriction, seniority, stack...)
  (SKIP)  inaccessible location, no sponsorship, poor fit, below minimum pay: not shown

State lives in Supabase (dev_jobs / dev_job_status, see supabase/schema.sql) when SUPABASE_URL and
SUPABASE_SERVICE_KEY are set, otherwise in output/*.json.

Usage:
  python find_jobs.py            search, update state, write output/dashboard/index.html
  python find_jobs.py --open     ...and open the dashboard
"""

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "output"
UA = {"User-Agent": "dev-jobs/1.0 (personal job search; daily)"}


def fetch(url, headers=None, data=None, retries=2, timeout=40):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})}, data=data)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if attempt == retries:
                print(f"  ! failed {url[:90]}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))


def fetch_json(url, headers=None):
    raw = fetch(url, headers)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        print(f"  ! not JSON: {url[:90]}", file=sys.stderr)
        return None


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def text_of(s):
    """Plain text from an HTML fragment."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def iso_date(value):
    """ISO date from an epoch, ISO string or RFC 822 date; '' if unknown."""
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            v = float(value)
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc).date().isoformat()
        s = str(value)
        if re.match(r"\d{4}-\d{2}-\d{2}", s):
            return s[:10]
        return parsedate_to_datetime(s).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return ""


def job(source, jid, title, company, url, *, restriction="", location="", remote=None, salary="", usd_year=None,
        job_type="", posted="", closes="", description=""):
    return {"source": source, "id": f"{source.lower().replace(' ', '')}:{jid}", "title": text_of(title),
            "company": text_of(company), "url": url, "restriction": text_of(restriction), "location": text_of(location),
            "remote": remote, "salary": salary, "usd_year": usd_year, "job_type": job_type, "posted": posted,
            "closes": closes, "description": text_of(description)}


# ---------------------------------------------------------------- salary

USD_RATE = {"USD": 1, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "AUD": 0.66, "CHF": 1.13, "SEK": 0.095, "NOK": 0.093,
            "DKK": 0.145, "PLN": 0.25, "INR": 0.012, "BRL": 0.18, "NGN": 0.00065, "ZAR": 0.055, "SGD": 0.74}
PER_YEAR = {"year": 1, "annual": 1, "yearly": 1, "month": 12, "monthly": 12, "week": 52, "weekly": 52,
            "day": 260, "daily": 260, "hour": 2080, "hourly": 2080}


def salary_fields(lo, hi, currency, period):
    """Display text and an approximate USD/year figure (None when it can't be worked out)."""
    try:
        lo, hi = float(lo or 0) or None, float(hi or 0) or None
    except (TypeError, ValueError):
        return "", None
    if not lo and not hi:
        return "", None
    cur = (currency or "USD").upper()
    per = (period or "year").lower()
    fmt = lambda v: f"{v:,.0f}"
    text = f"{cur} {fmt(lo or hi)}" + (f"–{fmt(hi)}" if lo and hi and hi != lo else "") + ("" if per in ("year", "annual", "yearly") else f"/{per}")
    rate, mult = USD_RATE.get(cur), PER_YEAR.get(per)
    return text, round((lo or hi) * rate * mult) if rate and mult else None


# ---------------------------------------------------------------- sources

def himalayas(profile):
    """Search API. Empty locationRestrictions means open worldwide."""
    jobs = []
    for q in profile["searches"]:
        for scope in ({"worldwide": "true"}, {"country": profile["home_country"]}):
            for page in range(1, 4):
                d = fetch_json("https://himalayas.app/jobs/api/search?" + urllib.parse.urlencode({"q": q, "page": page, **scope}))
                if not d or not d.get("jobs"):
                    break
                for r in d["jobs"]:
                    places = r.get("locationRestrictions") or []
                    tz = r.get("timezoneRestrictions") or []
                    if places:
                        restriction = ", ".join(places)
                    elif tz and max(tz) - min(tz) < 20:   # a near-full span (UTC-11..+14) is no restriction at all
                        restriction = f"UTC{min(tz):+g} to UTC{max(tz):+g}"
                    else:
                        restriction = "Worldwide"
                    text, usd = salary_fields(r.get("minSalary"), r.get("maxSalary"), r.get("currency"), r.get("salaryPeriod"))
                    jobs.append(job("Himalayas", r.get("guid") or r.get("applicationLink"), r.get("title"), r.get("companyName"),
                                    r.get("applicationLink") or r.get("guid"), restriction=restriction, remote=True,
                                    salary=text, usd_year=usd, job_type=r.get("employmentType") or "",
                                    posted=iso_date(r.get("pubDate")), closes=iso_date(r.get("expiryDate")),
                                    description=r.get("description") or r.get("excerpt")))
                if len(d["jobs"]) < 20:
                    break
    return jobs


def remotive(profile):
    d = fetch_json("https://remotive.com/api/remote-jobs?category=software-dev") or {}
    return [job("Remotive", r["id"], r["title"], r["company_name"], r["url"], restriction=r.get("candidate_required_location"),
                remote=True, salary=r.get("salary") or "", job_type=(r.get("job_type") or "").replace("_", " "),
                posted=iso_date(r.get("publication_date")), description=r.get("description"))
            for r in d.get("jobs", [])]


def jobicy(profile):
    d = fetch_json("https://jobicy.com/api/v2/remote-jobs?count=100&industry=dev") or {}
    out = []
    for r in d.get("jobs", []):
        text, usd = salary_fields(r.get("salaryMin"), r.get("salaryMax"), r.get("salaryCurrency"), r.get("salaryPeriod"))
        jt = r.get("jobType")
        out.append(job("Jobicy", r["id"], r["jobTitle"], r["companyName"], r["url"], restriction=r.get("jobGeo"), remote=True,
                       salary=text, usd_year=usd, job_type=", ".join(jt) if isinstance(jt, list) else jt or "",
                       posted=iso_date(r.get("pubDate")), description=r.get("jobExcerpt") or r.get("jobDescription")))
    return out


def wwr(profile):
    out = []
    for cat in ("remote-front-end-programming-jobs", "remote-full-stack-programming-jobs", "remote-back-end-programming-jobs"):
        raw = fetch(f"https://weworkremotely.com/categories/{cat}.rss")
        if not raw:
            continue
        for it in ET.fromstring(raw).iter("item"):
            company, _, role = (it.findtext("title") or "").partition(":")
            out.append(job("We Work Remotely", it.findtext("guid") or it.findtext("link"), role or company, company if role else "",
                           it.findtext("link"), restriction=it.findtext("region") or it.findtext("country") or "", remote=True,
                           job_type=it.findtext("type") or "", posted=iso_date(it.findtext("pubDate")),
                           closes=iso_date(it.findtext("expires_at")), description=it.findtext("description")))
    return out


def workingnomads(profile):
    d = fetch_json("https://www.workingnomads.com/api/exposed_jobs/") or []
    return [job("Working Nomads", r["url"], r["title"], r.get("company_name"), r["url"], restriction=r.get("location"),
                remote=True, posted=iso_date(r.get("pub_date")), description=r.get("description"))
            for r in d if r.get("category_name") == "Development"]


def remoteok(profile):
    d = fetch_json("https://remoteok.com/api") or []
    out = []
    for r in d[1:]:  # first item is the API's legal notice
        text, usd = salary_fields(r.get("salary_min"), r.get("salary_max"), "USD", "year")
        out.append(job("Remote OK", r["id"], r.get("position"), r.get("company"), r.get("url") or r.get("apply_url"),
                       restriction=r.get("location") or "", remote=True, salary=text, usd_year=usd,
                       posted=iso_date(r.get("date") or r.get("epoch")), description=r.get("description")))
    return out


def arbeitnow(profile):
    out = []
    for page in range(1, 4):
        d = fetch_json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
        if not d or not d.get("data"):
            break
        for r in d["data"]:
            out.append(job("Arbeitnow", r["slug"], r["title"], r["company_name"], r["url"], location=r.get("location") or "",
                           remote=bool(r.get("remote")), job_type=", ".join(r.get("job_types") or []),
                           posted=iso_date(r.get("created_at")), description=r.get("description")))
    return out


def hn_hiring(profile):
    """Top-level posts in the latest 'Ask HN: Who is hiring?' thread. Header line: Company | Role | Location | ..."""
    s = fetch_json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=6") or {}
    story = next((h for h in s.get("hits", []) if "who is hiring" in h.get("title", "").lower()), None)
    item = story and fetch_json(f"https://hn.algolia.com/api/v1/items/{story['objectID']}")
    out = []
    for c in (item or {}).get("children", []):
        raw = c.get("text") or ""
        header = text_of(raw.split("<p>")[0])
        parts = [p.strip() for p in header.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        roles = [p for p in parts[1:] if title_ok(p, profile)]
        if not roles:
            continue
        loc = " | ".join(p for p in parts[1:] if p not in roles)
        out.append(job("HN Who is hiring", c["id"], roles[0], parts[0], f"https://news.ycombinator.com/item?id={c['id']}",
                       restriction=loc, location=loc, remote=bool(re.search(r"\bremote\b", header, re.I)),
                       posted=iso_date(c.get("created_at")), description=raw))
    return out


def job_posting_ld(page):
    """The schema.org JobPosting embedded in an advert page, or {}."""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block, strict=False)
        except ValueError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                return d
    return {}


def hotnigerianjobs(profile):
    """RSS gives only a one-line summary, so matching titles get their advert page's JobPosting data too."""
    raw = fetch("https://www.hotnigerianjobs.com/feed/rss.xml")
    out = []
    for it in ET.fromstring(raw).iter("item") if raw else []:
        title = it.findtext("title") or ""
        role, _, company = title.rpartition(" at ")
        role = role or title
        if not title_ok(role, profile):
            continue
        link, description, location, closes = it.findtext("link"), it.findtext("description") or "", "Nigeria", ""
        page = fetch(link)
        ld = job_posting_ld(page.decode("utf-8", "replace")) if page else {}
        if ld:
            description = html.unescape(ld.get("description") or description)
            closes = iso_date(ld.get("validThrough"))
            places = ld.get("jobLocation") or []
            places = places if isinstance(places, list) else [places]
            towns = [(p.get("address") or {}).get("addressLocality") for p in places if isinstance(p, dict)]
            location = ", ".join(t for t in towns if t) + ", Nigeria" if any(towns) else "Nigeria"
        out.append(job("Hot Nigerian Jobs", it.findtext("guid") or link, role, company, link, location=location, remote=False,
                       posted=iso_date(it.findtext("pubDate")), closes=closes, description=description))
    return out


def jobsinnigeria(profile):
    """WordPress search feeds. robots.txt asks for 20 s between requests, so only a few searches."""
    out, seen = [], set()
    for i, q in enumerate(("developer", "software", "frontend", "full stack")):
        if i:
            time.sleep(20)
        raw = fetch("https://www.jobsinnigeria.careers/?" + urllib.parse.urlencode({"s": q, "feed": "rss2"}))
        for it in ET.fromstring(raw).iter("item") if raw else []:
            link = it.findtext("link")
            role, _, company = (it.findtext("title") or "").rpartition(" at ")
            if link in seen or not role:
                continue
            seen.add(link)
            body = it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or it.findtext("description") or ""
            out.append(job("Jobs in Nigeria", link, role, company, link, location="Nigeria", remote=False,
                           posted=iso_date(it.findtext("pubDate")), description=body))
    return out


def adzuna(profile):
    """Optional: roles in Canada, the UK, Germany and the Netherlands whose adverts mention sponsorship."""
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []
    out = []
    for country in ("ca", "gb", "de", "nl"):
        params = {"app_id": app_id, "app_key": app_key, "what": "visa sponsorship", "what_or": "angular react typescript frontend .net node",
                  "category": "it-jobs", "max_days_old": profile["max_days_old"], "results_per_page": 50, "sort_by": "date"}
        d = fetch_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?" + urllib.parse.urlencode(params),
                       {"Accept": "application/json"}) or {}
        cur = {"ca": "CAD", "gb": "GBP"}.get(country, "EUR")
        for r in d.get("results", []):
            predicted = str(r.get("salary_is_predicted")) == "1"
            text, usd = ("", None) if predicted else salary_fields(r.get("salary_min"), r.get("salary_max"), cur, "year")
            out.append(job("Adzuna", r["id"], r.get("title"), (r.get("company") or {}).get("display_name"), r.get("redirect_url"),
                           location=(r.get("location") or {}).get("display_name", "") + f", {country.upper()}", remote=False,
                           salary=text, usd_year=usd, job_type=r.get("contract_time") or "", posted=iso_date(r.get("created")),
                           description=r.get("description")))
    return out


# Richer location data first: when the same job is on several boards, the earlier source's copy is kept.
SOURCES = [himalayas, remotive, jobicy, wwr, workingnomads, remoteok, arbeitnow, hn_hiring, hotnigerianjobs, jobsinnigeria, adzuna]
SOURCE_RANK = {"Himalayas": 0, "Remotive": 1, "Jobicy": 2, "We Work Remotely": 3, "Working Nomads": 4, "Remote OK": 5,
               "Arbeitnow": 6, "HN Who is hiring": 7, "Hot Nigerian Jobs": 8, "Jobs in Nigeria": 9, "Adzuna": 10}


# ---------------------------------------------------------------- location access

WORLD = re.compile(r"\b(worldwide|anywhere|global(ly)?|international|all countries|any country|any location|world)\b", re.I)
HOME = re.compile(r"\b(nigeria|lagos|abuja|africa|emea|wat)\b", re.I)
TZ_RANGE = re.compile(r"(?:utc|gmt)\s*([+\-−–]\s*\d{1,2})(?::\d\d)?\s*(?:to|-|–|—|and)\s*(?:utc|gmt)?\s*([+\-−–]\s*\d{1,2})", re.I)
CET_WINDOW = re.compile(r"\b(cet|cest|gmt|utc|wat|european time)", re.I)
VISA = re.compile(r"visa sponsorship|sponsor(ship)? (your |a |the )?(work )?visa|\bvisa\b[^.]{0,40}\b(support|sponsor|assist|provided|available|help)"
                  r"|relocation (package|support|assistance|bonus|budget|help)|help (you )?relocat|(will|can) relocate you|relocation (is )?(provided|offered|available)", re.I)
HN_VISA = re.compile(r"\bVISA\b")   # HN headers flag sponsorship in capitals; lower-case "visa" is often the card network
NO_VISA = re.compile(r"(not|unable to|cannot|can't|don't|do not|will not|won't)\s+(be\s+able\s+to\s+)?(offer|provide)\s+(visa\s+)?(sponsorship|visas?|relocation)"
                     r"|(cannot|can't|unable to|do not|don't|will not|won't|not able to)\s+sponsor|without (the need for )?(visa )?sponsorship"
                     r"|must (already )?have (the )?(legal )?right to work|must be (legally )?(authori[sz]ed|eligible) to work|no (visa )?sponsorship", re.I)


def tz_covers_home(text, home_offset=1):
    m = TZ_RANGE.search(text)
    if m:
        a, b = (int(re.sub(r"[\s−–]", lambda x: "-" if x.group() in "−–" else "", g)) for g in m.groups())
        return min(a, b) <= home_offset <= max(a, b)
    return bool(CET_WINDOW.search(text)) and bool(re.search(r"(\+/?-|±)\s*\d|time ?zone|overlap", text, re.I))


def remote_access(restriction):
    """(access, note) for a remote job given its candidate-location restriction text."""
    r = re.sub(r"\b(remote|fully|100%|only|from|candidates?|based|in)\b|[()]", " ", restriction or "", flags=re.I)
    r = " ".join(r.split()).strip(" ,;|-/")
    if not r.strip():
        return "unclear", "Remote; no location restriction stated"
    if HOME.search(r):
        return "region", restriction
    if WORLD.search(r):
        return "worldwide", restriction
    if tz_covers_home(r):
        return "region", restriction + " (covers Lagos time)"
    return "restricted", restriction


# Boards often tag a role "Worldwide" while the advert says otherwise ("must be located in the US...").
RESIDENCY = re.compile(r"(must|should|need to|needs to|required to|have to|you are|you're|you will be|candidates? (must|should) be)\s+(be\s+)?(currently\s+)?(legally\s+)?"
                       r"(located|based|residing|reside|living|live|authori[sz]ed to work|able to work( legally)?|eligible to work)\s+(in|within|from)\s+(the\s+)?([^.;:()]{2,90})", re.I)
TAX_OR_CLEARANCE = re.compile(r"\b(u\.?s\.?\s+(w-?2|citizens?(hip)?|tax residen\w+|persons?)|security clearance (is )?required|must (hold|have|obtain) (an? )?(active )?(security )?clearance"
                              r"|right to work in the (uk|us|united states|eu))", re.I)


def advert_residency(description):
    """('restricted' | 'unclear', quote) when the advert limits where candidates live; None otherwise."""
    m = RESIDENCY.search(description)
    if m and not (HOME.search(m.group(0)) or WORLD.search(m.group(0)) or tz_covers_home(m.group(0))):
        quote = m.group(0).strip()[:140]
        return ("unclear" if re.search(r"relocat", description[m.start():m.end() + 80], re.I) else "restricted"), quote
    m = TAX_OR_CLEARANCE.search(description)
    if m:
        return "restricted", description[max(0, m.start() - 40):m.end() + 40].strip()[:140]
    return None


def classify_access(j):
    """Decide whether someone based in Nigeria can take this job, and how sure we are."""
    text = f"{j['title']} {j['restriction']} {j['location']} {j['description'][:3000]}"
    visa = bool(VISA.search(text)) or (j["source"] == "HN Who is hiring" and bool(HN_VISA.search(j["restriction"])))
    no_visa = bool(NO_VISA.search(text))
    where = j["location"] or j["restriction"]
    in_nigeria = bool(re.search(r"\b(nigeria|lagos|abuja|port harcourt|ibadan)\b", where, re.I))

    if in_nigeria and not j["remote"]:
        return "nigeria", where
    if j["remote"]:
        access, note = remote_access(j["restriction"])
        if access in ("worldwide", "region", "unclear"):
            limit = advert_residency(j["description"])
            if limit:
                access, note = limit[0], f"Tagged '{j['restriction'] or 'Remote'}', but the advert says: “{limit[1]}…”"
        if access in ("worldwide", "region"):
            return access, note
        if visa and not no_visa:
            return "visa", f"{note}; mentions visa sponsorship / relocation"
        if j["source"] == "Arbeitnow" and access != "restricted":
            return "restricted", "Remote, Germany/EU-based (Arbeitnow)"
        return access, note
    if no_visa:
        return "no-visa", f"{where}; states no sponsorship"
    if visa:
        return "visa", f"{where}; mentions visa sponsorship / relocation"
    return "abroad", f"{where}; sponsorship not mentioned"


# ---------------------------------------------------------------- scoring

TECH = ["angular", "react", "typescript", "javascript", "tailwind", "rxjs", "nx", ".net", "c#", "node", "postgres", "fintech", "payments"]


def padded(s):
    return f" {s.lower()} "


def title_ok(title, profile):
    t = padded(title)
    return any(w in t for w in profile["title_must_match"]) and not any(w in t for w in profile["title_exclude"])


def score(j, profile):
    """(score 0-100, matched skills, notes) or None when the title isn't a role we want at all."""
    if not title_ok(j["title"], profile):
        return None
    t, text = padded(j["title"]), padded(f"{j['title']} {j['description']}")
    points, notes = 30, []
    for w, p in profile["title_points"].items():
        if w in t:
            points += p
    for w, p in profile["text_points"].items():
        if w in text:
            points += p
    mine = ("angular", "react", "frontend", "front-end", "front end", "typescript", "javascript", ".net", "c#", "node")
    if any(w in t for w in profile["other_stacks"]) and not any(w in t for w in mine):
        points += profile["penalties"]["title_other_stack"]
        notes.append("different stack")
    if re.search(r"desarrollador|desenvolvedor|programador|ingenier|engenheir|entwickler|développeur|sviluppatore", t):
        points += profile["penalties"]["non_english_title"]
        notes.append("non-English advert")
    if re.search(r"\b(lead|staff|principal|architect)\b", t):
        points += profile["penalties"]["lead_or_staff"]
        notes.append("lead/staff level")
    if re.search(r"(german|deutsch)[^.]{0,40}(c1|b2|fluent|native|required|flie(ss|ß)end)|(fluent|native)[^.]{0,20}german|sehr gute deutsch", text):
        points += profile["penalties"]["german_required"]
        notes.append("German required")
    if re.search(r"(fluent|native)[^.]{0,20}french|french[^.]{0,30}(required|fluent|native)", text):
        points += profile["penalties"]["french_required"]
        notes.append("French required")
    try:
        age = (date.today() - date.fromisoformat(j["posted"])).days
        if age > profile["max_days_old"]:
            return None
        points += max(0, 7 - age)
    except ValueError:
        pass
    skills = [s for s in TECH if s in text]
    return max(0, min(100, points)), skills, notes


ACCESS_OK = ("worldwide", "region", "nigeria", "visa")


def label(j, profile):
    """APPLY / REVIEW / SKIP, following claude-job-agent's CLAUDE.md."""
    if j["access"] in ("restricted", "abroad", "no-visa"):
        return "SKIP"
    if j["usd_year"] and j["usd_year"] < profile["min_usd_per_year"]:
        return "SKIP"
    if j["closes"] and j["closes"] < date.today().isoformat():
        return "SKIP"
    if j["score"] < profile["skip_below"]:
        return "SKIP"
    if j["score"] >= profile["apply_threshold"] and j["access"] in ACCESS_OK and not j["notes"]:
        return "APPLY"
    return "REVIEW"


COMPANY_SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|gmbh|ab|bv|b\.v|sa|sas|srl|plc|corp|corporation|co|group)\b\.?", re.I)


def dedupe_key(j):
    """Same title at the same company, whichever board it came from ("Proxify AB" = "Proxify")."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return f"{norm(j['title'])}|{norm(COMPANY_SUFFIX.sub('', j['company'] or ''))}"


# ---------------------------------------------------------------- storage

JOB_COLUMNS = ["id", "source", "title", "company", "url", "restriction", "location", "remote", "access", "access_note",
               "salary", "usd_year", "job_type", "posted", "closes", "score", "label", "skills", "notes", "snippet",
               "first_seen", "last_seen"]
GRACE_DAYS = 3


def is_active(j, today):
    if j.get("closes") and j["closes"] < today.isoformat():
        return False
    return j["last_seen"] >= (today - timedelta(days=GRACE_DAYS)).isoformat()


class FileStore:
    name = "local files"

    def known(self):
        return load_json(OUT / "seen.json", {})

    def save(self, jobs, today):
        seen = self.known()
        for j in jobs:
            seen[j["id"]] = {"first_seen": j["first_seen"]}
        save_json(OUT / "seen.json", seen)
        return [{**j, "active": True, "tracked": False} for j in jobs]


class SupabaseStore:
    name = "Supabase"
    JOBS, STATUS = "dev_jobs", "dev_job_status"

    def __init__(self, url, key):
        self.base = url.rstrip("/") + "/rest/v1/"
        self.headers = {"apikey": key, "Content-Type": "application/json"}
        if key.startswith("eyJ"):
            self.headers["Authorization"] = f"Bearer {key}"

    def _call(self, method, path, body=None, prefer=None):
        headers = {**UA, **self.headers, **({"Prefer": prefer} if prefer else {})}
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                if e.code < 500 or attempt == 2:
                    raise RuntimeError(f"Supabase {method} {path.split('?')[0]} failed: {e.code} {detail}") from None
            except urllib.error.URLError:
                if attempt == 2:
                    raise
            time.sleep(3 * (attempt + 1))

    def _select_all(self, table, query):
        rows = []
        while True:
            batch = self._call("GET", f"{table}?{query}&limit=1000&offset={len(rows)}")
            rows += batch
            if len(batch) < 1000:
                return rows

    def _in(self, ids):
        return urllib.parse.quote(",".join(f'"{x}"' for x in ids))

    def known(self):
        return {r["id"]: r for r in self._select_all(self.JOBS, "select=id,first_seen&order=id")}

    def save(self, jobs, today):
        rows = [{c: j.get(c) for c in JOB_COLUMNS} for j in jobs]
        for i in range(0, len(rows), 500):
            self._call("POST", self.JOBS, rows[i:i + 500], prefer="resolution=merge-duplicates,return=minimal")

        tracked = {r["job_id"] for r in self._select_all(self.STATUS, "select=job_id&order=job_id")}
        cols = ",".join(JOB_COLUMNS)
        since = (today - timedelta(days=GRACE_DAYS + 1)).isoformat()
        out = {r["id"]: r for r in self._select_all(self.JOBS, f"select={cols}&last_seen=gte.{since}&order=id")}
        missing = sorted(tracked - set(out))
        for i in range(0, len(missing), 100):
            out |= {r["id"]: r for r in self._call("GET", f"{self.JOBS}?select={cols}&id=in.({self._in(missing[i:i + 100])})")}

        cutoff = (today - timedelta(days=120)).isoformat()
        old = [r["id"] for r in self._select_all(self.JOBS, f"select=id&last_seen=lt.{cutoff}&order=id") if r["id"] not in tracked]
        for i in range(0, len(old), 100):
            self._call("DELETE", f"{self.JOBS}?id=in.({self._in(old[i:i + 100])})")
        return [{**r, "active": is_active(r, today), "tracked": r["id"] in tracked} for r in out.values()]


def open_store():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    return SupabaseStore(url, key) if url and key else FileStore()


def load_env_file(path):
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


# ---------------------------------------------------------------- output

def write_dashboard(jobs, profile, path):
    keep = ["id", "title", "company", "url", "access", "access_note", "salary", "usd_year", "job_type", "posted", "closes",
            "score", "label", "skills", "notes", "snippet", "source", "first_seen", "active"]
    data = {"generated": datetime.now().isoformat(timespec="minutes"), "home": profile["home_label"],
            "jobs": [{k: j.get(k) for k in keep} for j in jobs]}
    auth = {"url": os.getenv("SUPABASE_URL"), "key": os.getenv("SUPABASE_ANON_KEY")}
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (ROOT / "dashboard_template.html").read_text(encoding="utf-8")
    page = page.replace("/*__DATA__*/null", dump(data)).replace("/*__SUPABASE__*/null", dump(auth) if all(auth.values()) else "null")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")


def write_csv(jobs, path):
    cols = ["label", "score", "title", "company", "access", "access_note", "salary", "job_type", "posted", "skills", "notes", "source", "url"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows({**j, "skills": ", ".join(j.get("skills") or []), "notes": ", ".join(j.get("notes") or [])} for j in jobs)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=ROOT / "profile.json", type=Path)
    ap.add_argument("--open", action="store_true", help="open the dashboard when done")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_env_file(ROOT / ".env.local")

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    store, today = open_store(), date.today()
    known = store.known()
    print(f"Searching {len(SOURCES)} sources (state: {store.name})...")

    found = {}
    for source in SOURCES:
        before = len(found)
        try:
            for j in source(profile):
                if j["url"] and j["title"]:
                    found.setdefault(j["id"], j)
        except Exception as e:  # one broken feed shouldn't stop the others
            print(f"  ! {source.__name__} failed: {e}", file=sys.stderr)
        if len(found) > before:
            print(f"  {source.__name__}: {len(found) - before}")
    print(f"  {len(found)} listings")

    by_key = {}
    for j in found.values():
        s = score(j, profile)
        if not s:
            continue
        j["score"], j["skills"], j["notes"] = s
        j["access"], j["access_note"] = classify_access(j)
        j["label"] = label(j, profile)
        k = dedupe_key(j)
        pick = lambda x: (x["label"] == "SKIP", SOURCE_RANK[x["source"]])
        if k not in by_key or pick(j) < pick(by_key[k]):
            by_key[k] = j
    matches = list(by_key.values())
    for j in matches:
        j["snippet"] = j["description"][:260]
        j["first_seen"] = (known.get(j["id"]) or {}).get("first_seen") or today.isoformat()
        j["last_seen"] = today.isoformat()

    shown = [j for j in store.save(matches, today) if j.get("tracked") or (j["label"] != "SKIP" and title_ok(j["title"], profile))]
    order = {"APPLY": 0, "REVIEW": 1, "SKIP": 2}
    shown.sort(key=lambda j: (not j["active"], order[j["label"]], -j["score"]))
    write_csv(shown, OUT / "jobs_latest.csv")
    dashboard = OUT / "dashboard" / "index.html"
    write_dashboard(shown, profile, dashboard)

    live = [j for j in shown if j["active"]]
    count = lambda **kw: sum(all(j.get(k) == v for k, v in kw.items()) for j in live)
    new = [j for j in matches if j["id"] not in known and j["label"] != "SKIP"]
    print(f"  {len(matches)} relevant titles; showing {len(live)}: {count(label='APPLY')} APPLY, {count(label='REVIEW')} REVIEW "
          f"| worldwide {count(access='worldwide')}, Africa/EMEA/time-zone {count(access='region')}, Nigeria {count(access='nigeria')}, "
          f"visa/relocation {count(access='visa')}, unclear {count(access='unclear')} | {len(new)} new")
    for j in sorted(new, key=lambda j: -j["score"])[:10]:
        print(f"  [{j['label']:6} {j['score']:>3}] {j['title']} - {j['company']} ({j['access']}: {j['access_note'][:50]})")
    print(f"Dashboard: {dashboard}")
    if args.open:
        webbrowser.open(dashboard.as_uri())


if __name__ == "__main__":
    main()
