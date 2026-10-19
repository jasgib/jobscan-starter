---
description: Write a tailored CV and cover letter for one job, as PDFs
---
Write an application pack for the job in the arguments ($ARGUMENTS) - a key from the dashboard or `inbox`, or an employer and title to find it with. `JS` is defined in CLAUDE.md.

1. Run `JS show KEY` and read the full description. Read `me/profile.md` and `me/master.json`.
2. Pick the 3-4 things this job cares about most. Say them in one line each before writing.
3. **CV:** copy `me/master.json` to `applications/<Employer> - <Role>/cv.json` and tailor it: rewrite the subtitle and profile paragraph for this job, reorder and trim bullets so the most relevant come first, and reword bullets toward the job's language **only where the underlying fact is unchanged**. Keep it to two pages.
4. **Letter:** write `applications/<Employer> - <Role>/letter.json` with the same `name`, `subtitle`, `contact` as the CV plus:
   `"letter": {"employer": "...", "role": "...", "ref": "<job ref or empty>", "city": "<their city>", "date": "<today, e.g. 12 October 2026>", "salutation": "Dear Hiring Manager,", "paragraphs": ["...", "...", "..."]}`
   Three or four short paragraphs: why this role at this company (something specific from the posting, not flattery), two pieces of evidence from master.json that match what the job needs, and a plain close. No clichés ("I am writing to express my interest", "passionate", "dynamic"). Write like the person talks.
5. **Truth check - mandatory.** Go through every claim, number, tool and skill in both files and confirm it appears in `me/master.json` or `me/about-me.json`. Remove anything that doesn't. List anything you removed.
6. Render: `JS render-cv "applications/<folder>/cv.json" "applications/<folder>/CV.pdf"` and `JS render-letter "applications/<folder>/letter.json" "applications/<folder>/Cover letter.pdf"`. If Chrome is missing, the error says how to install it.
7. Tell them where the PDFs are and to read both before sending.
