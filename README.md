# Favorite sports — auto-updating Apple Calendar

Creates a public subscribed Apple Calendar feed using GitHub Actions (daily) and GitHub Pages.

## Setup (on the *separate* GitHub account)

1. Create a new GitHub account; verify its email. A public repository exposes the repository files and calendar **but not your private Apple Calendar or email**.
2. Create a **public** repository named `sports-calendar` on that account.
3. On the repository page, choose **Add file → Upload files**. Upload `update.py`, `feeds.json`, and the `.github` workflow directory (for hidden directories, browser drag-and-drop behavior varies; easiest is to use GitHub's **Add file → Create new file** to create `.github/workflows/update.yml` by pasting it). Preserve folder paths exactly.
4. Configure **Settings → Pages → Source: GitHub Actions** first, then open **Actions → Refresh sports calendar → Run workflow**. Enable workflows if GitHub asks. Confirm it finished successfully and that `docs/sports.ics` and `docs/audit.json` exist.
5. Go to **Settings → Pages → Build and deployment → Source: GitHub Actions** (NOT "Deploy from a branch"). Then run the workflow again if necessary. The workflow deploys Pages directly on every scheduled run.
6. Open `https://YOUR-ACCOUNT.github.io/sports-calendar/sports.ics` and verify that it contains `BEGIN:VCALENDAR`. Pages deployment can take some time.
7. On macOS **Calendar → File → New Calendar Subscription**, enter `https://YOUR-ACCOUNT.github.io/sports-calendar/sports.ics`. Set **Auto-refresh** to **every hour** (or next available frequency). On iPhone: Settings → Apps → Calendar → Calendar Accounts → Add Account → Other → Add Subscribed Calendar.

**Crucial:** Do not download/import the ICS from GitHub; use **New Calendar Subscription** so later changes propagate automatically. Do not publish the feed in iCloud Private Calendar; it is a public schedule.

## Source verification / limitations

- ESPN's sports API is **unofficial** and may change. It provides broad multisport team schedules, but no guarantee of all women's, national-team, and knockout fixtures.
- **Official MLB Stats API** is consulted for the Phillies; **official NHL API** for the Flyers. Those fixtures take precedence in matching conflicts. ESPN is checked separately.
- For *other teams*, code consults multiple ESPN competition schedules. **It does not yet actively scrape every official team website**. To ingest official team feeds, put their **verified direct ICS URLs** into `feeds.json` as arrays keyed by team code, for example `{"LFC":["https://EXAMPLE-OFFICIAL-HOST/team.ics"]}`. Do not use a website landing page as an ICS URL.
- `docs/audit.json` reports missing/failed sources and kickoff conflicts. It does not establish that dates omitted from an API are canceled.
- All event dates are UTC internally, displayed in your local timezone by Apple Calendar.
- Streaming rights are not automatically inferred; published fixtures include competition/source link, **not unverified game-by-game broadcaster claims**.
- A published schedule is only as good as source completeness. Check `docs/audit.json`, especially teams with zero events or errors, before treating the calendar as comprehensive.
- Postseason, cup draws, national friendlies are added when upstream sources publish them.
- GitHub Pages may cache updated files. Apple Calendar refresh timing is controlled by Apple and may vary.

## Technical choices

- No third-party Python dependencies, API keys, credit card, server, or manual weekly uploads.
- Uses persistent source-derived calendar UIDs for stable edits.
- Keeps last-known fixtures for a team if *all* its feeds fail. A provider outage will not wipe out the entire calendar.
- Runs daily at 05:23 UTC; manual runs are supported under Actions.
- You can set the repository's GitHub Pages site to a public URL without exposing your main GitHub profile.
