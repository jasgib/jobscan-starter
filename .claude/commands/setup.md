---
description: Turn the welcome-page answers and CV into a profile, a master CV and a list of companies
---
Set jobscan up for the person using it. Work through these steps in order and tell them briefly what you're doing at each one. Commands below use `JS` as shorthand - see CLAUDE.md for the exact command on this computer.

1. **Read what they gave you.**
   - `me/about-me.json` (their welcome-page answers). If it's missing, tell them to double-click `start.command` (Mac) or `start.bat` (Windows), fill in the page, and run `/setup` again. Stop there.
   - Their CV: run `JS cv-text me/cv.<ext>` on whichever `me/cv.*` file exists. If there's no CV, ask them to add one on the welcome page - you need it for `master.json`.

2. **Ask follow-ups - at most five, in one message.** Only ask what you genuinely can't infer and what would change which jobs they see: e.g. which of two directions matters more, a hard salary floor, how far they'd commute, whether a title one level up or down is fine, deal-breakers. Wait for the answers.

3. **Write `me/profile.md`** using the shape of `examples/profile.template.md`. Write it in plain, specific language - their words where possible. Include at least three worked examples (realistic made-up postings with the score you'd give and why), covering a clear yes, a near miss that looks right but isn't, and a clear no. Show them the one-line version and the tiers and ask if anything is wrong.

4. **Write `me/master.json`** in the shape of `examples/master.example.json`, using ONLY facts from their CV and answers. Never invent, round up or embellish a number, skill, tool or achievement. If a section has nothing, leave it as an empty list. `languages[].filled` is 1-6. Tell them to check it.

5. **Write `config.yaml`** in the shape of `examples/config.example.yaml`:
   - `location_terms` from where they'd work (include "Remote" if they'd work remotely).
   - `exclude_title_terms` and `seniority_exclude_terms` from their level and deal-breakers. Be conservative - a word here silently hides jobs. Whole words only; list variants separately.
   - `queries`: 3-8 short search phrases for their target roles.
   - Start `employers:` empty (`employers: {}`).
   Then validate it: `JS status` must run without error.

6. **Add their companies.** For every company in `about-me.json` → `companies`, follow `.claude/commands/add-company.md`. Then suggest 5-10 more that fit their profile, say why in one line each, and add the ones they agree to. Report which couldn't be added and why.

7. **Finish:** run `JS collect` (free, no Claude usage) and tell them how many jobs are waiting. Offer to run `/review-jobs` now. Remind them: day to day it's `collect`, then `/review-jobs`.
