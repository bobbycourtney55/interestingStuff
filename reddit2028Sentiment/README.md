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
