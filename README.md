# Developer jobs: remote, Nigeria & relocation

A daily search for software engineering jobs that a Nigeria-based senior frontend / full-stack developer
(Angular, React, TypeScript, .NET / C#, Node.js) can actually take:

- **Remote, open to Nigeria:** worldwide, Africa/EMEA, or a time-zone window that covers Lagos (UTC+1)
- **In Nigeria:** onsite, hybrid or remote
- **Abroad with visa sponsorship or relocation:** the advert says so

Results are published as a dashboard on GitHub Pages: https://faithfulonoriobakpo.github.io/dev-jobs/

## How jobs are judged

**Location.** "Remote" is never taken to mean "remote from anywhere". A job counts as accessible only if:
- the board's candidate-location field allows Nigeria (worldwide, Africa, EMEA, Nigeria, or a UTC range including +1); **and**
- the advert text doesn't say otherwise. Phrases like "must be located in the US", "authorised to work in the UK", "US W-2" or "security clearance required" override a board's "Worldwide" tag. Those jobs are dropped, or marked *Unclear* with the advert's wording quoted when it's ambiguous.

Onsite or hybrid jobs abroad count only when the advert mentions visa sponsorship or relocation. On Hacker News, a capitalised `VISA` in the header line also counts.

**Fit.** Each title and advert is scored against `profile.json`:
- title and advert keywords (Angular, React, TypeScript, .NET, Node, fintech…) add points;
- other main stacks (Python, Java, Go…), lead/staff level, and German or French language requirements subtract points.

**Label.** The labels follow the claude-job-agent rules:
- **APPLY:** strong match, accessible location, no caveats.
- **REVIEW:** worth a look, but something needs checking.
- **SKIP:** inaccessible location, no sponsorship, below US$1,000/month, closed, or a poor fit. These aren't shown.

## Sources

No keys are needed for:
- **Remote boards:** [Himalayas](https://himalayas.app), [Remotive](https://remotive.com), [Jobicy](https://jobicy.com), [We Work Remotely](https://weworkremotely.com), [Working Nomads](https://www.workingnomads.com), [Remote OK](https://remoteok.com)
- **Europe:** [Arbeitnow](https://www.arbeitnow.com)
- **Hacker News:** [Who is hiring](https://news.ycombinator.com/submitted?id=whoishiring), the latest monthly thread
- **Nigeria:** [Hot Nigerian Jobs](https://www.hotnigerianjobs.com) and [Jobs in Nigeria](https://www.jobsinnigeria.careers). The second is fetched 20 s apart, as its robots.txt asks.

Optional: **Adzuna** (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY` repo secrets) for adverts in Canada, the UK, Germany and the Netherlands that mention sponsorship.

Jobberman isn't used: its robots.txt disallows automated access to job pages and searches.

## How it runs

`.github/workflows/find-jobs.yml` runs every day at 06:00 Lagos time, and on demand from the Actions tab. It:

1. Searches all sources, scores and labels each job, and merges duplicates across boards.
2. Saves jobs to Supabase (`dev_jobs`). A job stays listed for 3 days after it was last seen, unless its closing date passes first.
3. Publishes `output/dashboard/` to GitHub Pages.

On the dashboard, signing in syncs application statuses (Saved / Applied / Interview / Offer / Rejected / Hidden) across devices. They're stored in `dev_job_status`, and each login sees only its own.

## Supabase

This project shares a Supabase project with the nurse job finder. Everything here is prefixed `dev_`.

- `supabase/schema.sql`: tables and access rules. Row-level security is on, and the public key can't read or change `dev_jobs`.
- `setup_supabase.py`: applies the schema, adds this dashboard to the allowed sign-in addresses, and stores the GitHub secrets. It reads `.env.local` (git-ignored).

## Run locally

```
python find_jobs.py --open
```

This uses the Python standard library only. With the Supabase keys in `.env.local` it uses the same database as the Action; without them it keeps state in `output/`.

## Tuning (`profile.json`)

- `title_must_match` / `title_exclude`: which titles count at all.
- `title_points` / `text_points` / `penalties` / `other_stacks`: scoring.
- `apply_threshold` / `skip_below`: the APPLY and hide cut-offs.
- `min_usd_per_year`: minimum pay. This is applied only when a board gives a structured salary.
