# 3-minute walkthrough: Day-Ahead Load Forecasting & Ops Reports

A timed script for a Loom recording of about 3 minutes (screen plus camera bubble, 1080p). Say it in your own words; the lines are a guide, not a teleprompter.

**Open these tabs before you press record:** README, ops-log branch reports, forecasting/, dbt/models, GitHub Actions (daily).

| Time | On screen | What to say |
|---|---|---|
| 0:00–0:20 | Portfolio card, then the README title | Control rooms need tomorrow's demand by mid-morning. Over 45,031 half-hours, this forecast beats the national grid operator's own published forecast: 2.69% against 2.78% error. It runs itself every day. |
| 0:20–0:45 | README intro and the Data section | At a Nigerian electricity distributor I produced daily fault and hourly load reporting. This rebuilds that daily operations rhythm on public GB data from NESO. No employer data is used. |
| 0:45–1:10 | README architecture and the daily workflow on GitHub Actions | Every day it loads new data incrementally, builds dbt, forecasts tomorrow, scores yesterday and writes a morning report, in under a minute. |
| 1:10–1:35 | The `ops-log` branch reports | The forecast log lives on its own branch, so accuracy is tracked over time. |
| 1:35–2:00 | The leakage and clock-change tests | Each forecast uses only what was known at 09:45 the day before. A dbt test fails on any late forecast, and another checks the 46- and 50-period clock-change days. |
| 2:00–2:30 | Backtest results in Numbers | The model starts from NESO's forecast and learns its systematic error. It wins in 23 of 31 months; the naive same-day-last-week scores 8.14%. I also caught a date-format bug that swapped day and month in NESO's files, and it's unit-tested. |
| 2:30–2:45 | `docs/design_doc.md`, the options table | The decision I'd defend in an interview: Benchmark against the professional forecast, not just a naive baseline, because beating a naive model proves very little. |
| 2:45–3:00 | Back to the README top | For an energy operator, that means a forecast with an honest track record, delivered every morning without anyone running it. The repo, numbers and design doc are linked under the video. |

## Recording checklist
- Close email, chat and notifications. Zoom the browser to 125% so code is readable.
- Run `make fixture-all` once before recording, so CI-style output is fresh if you show it.
- Keep to one take per section; Loom lets you trim. Aim for 2:45 to 3:10.
- Show real numbers on screen as you say them; never estimate on camera.
- Say "synthetic" out loud wherever the README labels data as synthetic.

## After recording
1. Copy the Loom share link.
2. In `README.md`, replace the roadmap line with `- [x] [3-minute Loom walkthrough](<your Loom link>)` and add the link under the title.
3. Add the link to this project's card on saigwe.github.io.
