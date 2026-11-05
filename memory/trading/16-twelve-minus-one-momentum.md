---
date: 2026-11-05
type: trading-playbook
---
# 12 minus 1 momentum (freeCodeCamp course, via Alpaca)

Source: an Alpaca email (November 2026) about a free freeCodeCamp Python algorithmic trading course. It practices an end to end paper trading workflow: market data from Massive, momentum scoring in a Django app, and orders sent through SnapTrade into an Alpaca paper account, then checked in the Alpaca dashboard.

What "12 minus 1 momentum" means (standard definition): for each stock, take its return over the last 12 months but skip the most recent month. In practice: price 1 month ago divided by price 12 months ago, minus 1. Skipping the last month avoids the short term reversal effect, where last month's big winners often pull back a little. Rank a universe of stocks (the course uses 50) by that score; the highest scores have the strongest long term trend.

How it differs from what JARVIS trades now: 12 minus 1 momentum is a slow, months long signal, usually rebalanced once a month and held for weeks. It is not a day trading rule. JARVIS's day rules (momentum on the day, the 15 minute opening range close, engulfing candles) work on 5 minute and 15 minute candles and sell before the close.

Where it could help her:
- As a filter for swing mode: only take swing setups in stocks that rank in the top part of the 50 stock universe by 12 minus 1 momentum.
- As a filter for day trades: prefer day trade setups in stocks that are also in a strong long term trend.
- Either idea must be backtested before it changes how he trades, and switched on only with her approval.

Notes: JARVIS already connects to Alpaca directly and does not need SnapTrade or Massive. Watching the course is a good way for her to learn how the pieces of a trading bot fit together. Past momentum results do not promise future ones, and momentum strategies can have sharp losing stretches.
