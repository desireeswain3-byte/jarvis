---
date: 2026-10-23
type: trading-playbook
---
# Market hours and time changes

US stock market regular hours are 9:30 AM to 4:00 PM Eastern Time, every weekday except market holidays. For Madam Swain in Memphis (Central Time) that is 8:30 AM to 3:00 PM, all year, because Memphis changes its clocks on the same days as New York.

Daylight saving time: on Sunday, November 1, 2026, Eastern Time moves from EDT to EST (at 2:00 AM EDT, clocks go back to 1:00 AM EST). The next change back to EDT is Sunday, March 14, 2027. Market hours in Eastern Time do not change. Only the hours in UTC shift: regular hours become 14:30 to 21:00 UTC instead of 13:30 to 20:00 UTC. In Memphis time, nothing changes.

JARVIS's own schedule follows New York time automatically, so none of it moves for her: morning research about 7:45 AM Memphis time, no autopilot buys in the first 15 minutes after the open, swing mode looks for setups around 2:30 PM, autopilot sells its day trades about 10 minutes before the 3:00 PM close, the evening review after 3:15 PM, and the Mac stays awake from 7:30 AM to 4:00 PM on weekdays.

Alpaca also offers a 24/5 overnight session through its Trading API: 8:00 PM to 4:00 AM Eastern Time (7:00 PM to 3:00 AM in Memphis). After the change, the Sunday, November 1 overnight session (for the Monday, November 2 trade date) starts at 8:00 PM EST, which is 01:00 UTC Monday, and ends Monday at 4:00 AM EST (09:00 UTC). JARVIS does not trade the overnight session. Overnight and extended hours have thinner trading, wider gaps between buy and sell prices, and bigger jumps, so they are riskier for a small account; stay in regular hours.

Regular US hours seen from other countries after the change: UK 2:30 PM to 9:00 PM, Turkey 5:30 PM to midnight, UAE 6:30 PM to 1:00 AM, Thailand 9:30 PM to 4:00 AM, Singapore and Hong Kong 10:30 PM to 5:00 AM, Japan and Korea 11:30 PM to 6:00 AM (the next day).
