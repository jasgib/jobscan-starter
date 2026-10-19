# jobscan

Checks the job boards of the companies you choose every day, filters out what's obviously wrong, and has Claude score the rest against what *you* want - then writes tailored CVs and cover letters for the ones worth applying to. It runs on your laptop with your Claude Pro plan. No API key, no extra cost.

## Start here
1. **Install Python 3** if you don't have it: https://www.python.org/downloads/ (on Windows, tick "Add python.exe to PATH").
2. **Install Claude Code** and sign in with your Claude account: https://docs.claude.com/en/docs/claude-code
3. **Open the welcome page:** double-click `start.command` (Mac) or `start.bat` (Windows). The first time takes a minute or two while it installs. On a Mac, if it says the file can't be opened, right-click it → Open.
   The page tells you everything else - fill in "Get to know you", add your CV, then follow the steps.

## Every day
- Double-click `collect.command` / `collect.bat` (free).
- In Claude Code in this folder: `/review-jobs`.
- Open `dashboard.html`.

## Use it responsibly
jobscan reads companies' public careers pages and job-board APIs for your own job search. It identifies itself honestly, checks each site once per run at a gentle pace, and collects only job listings. Respect each site's terms of use, don't raise the request rate, and don't use it to collect anything other than jobs.

## Needs
- Google Chrome (or Chromium) for making PDF CVs and letters.
- Nothing you enter leaves this laptop except what Claude reads when you use Claude Code.
