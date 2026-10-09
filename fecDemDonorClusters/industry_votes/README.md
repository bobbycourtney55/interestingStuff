# Industry money and issue votes, House and Senate Democrats, 119th Congress

- `industry_money.py`: tags 2025–26 money by industry (crypto, oil/gas/auto, defense, pro-Israel, J Street). It covers four kinds of money: direct PAC contributions, independent expenditures supporting a member, donations bundled through a conduit (e.g. earmarked through AIPAC PAC), and donations from individuals whose listed employer is in the industry.
- `votes_money.py`: for 13 roll calls where Democrats split, estimates
  1. whether pre-vote industry money predicts the pro-industry vote, controlling for DW-NOMINATE dim 1 and other business-PAC money;
  2. a placebo version using other industries' money;
  3. whether post-vote industry money rises for pro-industry voters.
- `votes_followup.py`: a joint crypto + pro-Israel model, a post-vote placebo, and a breakdown by kind of money.

These are associations, not causal estimates. Industries give to members they expect to agree with them. DW-NOMINATE is partly estimated from these same votes. Individual-donor data only exists for members on the 2026 ballot, so Senate coverage is thin.
