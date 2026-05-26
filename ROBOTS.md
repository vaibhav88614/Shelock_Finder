# Scraping etiquette

JobPulse is a personal, local-only aggregator. It is designed to be a polite
guest on every careers site it touches:

* **User-Agent:** every HTTP request identifies as
  `JobPulseBot/1.0 (+https://github.com/local/jobpulse)`. Configure via the
  `JOBPULSE_USER_AGENT` env var.
* **robots.txt:** the Tier-2 (CustomAdapter) and Tier-3 (Playwright) scrapers
  check `robots.txt` for the target host before fetching and skip disallowed
  paths. Tier-1 adapters use the public JSON APIs the ATS providers publish.
* **Rate limits:** per-ATS token buckets (Greenhouse 10 req/s, Workday 2 req/s,
  others 5 req/s) plus a global semaphore of 10 concurrent companies.
* **Back-off on 429 / 5xx:** exponential back-off via `tenacity`, max 3 retries.
* **Manual trigger only:** no cron, no daemon. The user runs
  `python run.py scrape` when they want fresh data.
* **No login walls, no captcha bypass, no PII collection.**

If you are a site owner and want JobPulse removed from a specific endpoint,
add it to `robots.txt` or contact the user running the instance.
