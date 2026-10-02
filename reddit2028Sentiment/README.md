# Reddit sentiment toward potential 2028 Democratic primary candidates

Finds the share of Reddit posts naming Gavin Newsom, AOC, Pete Buttigieg,
Kamala Harris, JB Pritzker, Jon Ossoff or Ro Khanna that talk about each one
positively, negatively or neutrally.

## Run

```sh
pip install -r requirements.txt
export REDDIT_CLIENT_ID=... REDDIT_CLIENT_SECRET=...   # "script" app from reddit.com/prefs/apps
export ANTHROPIC_API_KEY=...

python sentiment.py fetch --days 365     # -> data/posts.jsonl
python sentiment.py classify             # -> data/stances.jsonl (resumable)
python sentiment.py report               # -> data/summary.csv
```

## Method

- **Collection:** Reddit's search API, run for each candidate's name variants
  with the `new`, `relevance`, `top` and `comments` sorts, merged and
  de-duplicated. Only posts (title and body) are included, not comments. Reddit
  stops returning results after a few hundred per query, so this is a large
  sample, not a full census.
- **Matching:** a post counts for a candidate when its title or body matches that
  candidate's name pattern. "Harris" alone doesn't count (it needs "Kamala" or
  "VP/Vice President/President Harris"), and "AOC" only counts in capitals.
- **Stance:** Claude labels each post's stance toward *each* candidate it
  names: positive, negative, neutral, or not_about (the name match is someone
  or something else). One post can be positive about one candidate and negative
  about another. not_about posts are left out of the percentages.
- **Output columns:** `pct_positive`, `pct_negative` and `pct_neutral` are shares
  of all relevant posts. `pos_share_of_polar` is positive ÷ (positive +
  negative), which ignores neutral news posts.

Caveats: Reddit's user base leans young and left, and subreddits differ a lot.
Break results down by `subreddit` in `stances.jsonl` before generalizing.

## News media: Media Cloud, % positive by month

`mediacloud_sentiment.py` does the same analysis for news articles in Media
Cloud's "United States - National" collection, month by month for the
current year.

```sh
export MEDIACLOUD_API_KEY=...   # search.mediacloud.org -> your profile
export ANTHROPIC_API_KEY=...

python mediacloud_sentiment.py fetch                   # -> data/mc_stories.jsonl
python mediacloud_sentiment.py classify                # -> data/mc_stances.jsonl (resumable)
python mediacloud_sentiment.py report                  # -> data/mc_monthly.csv, data/mc_pct_positive.png
```

- **Coverage:** only articles whose headline names the candidate (`article_title:` queries), and every such headline in each month (up to `--max-per-month`, default 3000). The free Media Cloud tier returns headlines only and allows 2 requests a minute, so the fetch takes about 45 minutes.
- **Stance:** Claude reads the headline (plus up to 12,000 characters of text
  with `--full-text`, on accounts allowed to fetch it) and labels how the article portrays that candidate: positive,
  negative, neutral, or not about them. A bad event reported in a dry tone
  (an indictment, a poll slump) still counts as negative.
- **Chart:** one panel per candidate, with the other candidates in gray for
  comparison. Panels are ordered by average % positive. Hollow points mark
  months with fewer than 30 classified articles.
- **% positive** = positive ÷ (positive + negative + neutral). The CSV also has
  % negative.

### 2026 results (Jan–Sep)

`data/mc_pct_positive.png` and `data/mc_monthly.csv` hold the results for
6,273 headlines. The labels in `data/mc_stances.jsonl` were made by Claude
reading every headline in a Claude Code session, not through the API, using
the same rubric as `classify`. `data/labels/` has the per-batch label files,
`show.py` (prints headlines by index) and `merge.py` (rebuilds
`mc_stances.jsonl`). Running `classify` instead would relabel through the API.

### Outlet lean and traffic

`data/mc_outlets.csv` has one row per outlet (143) with:

- **Audience lean** (`lean`, `lean_group`): from Media Cloud's 2019 US partisanship
  collections, which group outlets by whether their stories were shared mostly
  by Twitter followers of liberal or conservative politicians (so it measures
  readership, not editorial stance). Outlets listed in several groups are
  averaged on a −2 (left) to +2 (right) scale; `mc_2019_groups` shows the raw
  groups. Four outlets missing from the collections (Newsweek, Fortune, Fox
  Business, one blog) were assigned by judgment (`lean_source=judgment`).
  Note the data is from 2019.
- **Traffic** (`umbrella_rank`, `traffic_tier`): rank in the Cisco Umbrella
  top-1M domain list (by DNS query volume; lower = more traffic). This is a
  popularity rank, not a visitor count.

Rebuild with `python data/outlets/fetch_partisanship.py` (needs
`MEDIACLOUD_API_KEY`, about 7 minutes), download
`https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip` into
`data/outlets/`, then `python data/outlets/build_outlets.py`. `report` then
also writes `data/mc_by_lean.csv` and `data/mc_by_lean.png`, which show tone per
candidate split by outlet lean.
