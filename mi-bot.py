#!/usr/bin/env python3

import feedparser

from time import mktime
from datetime import datetime as dt

MINKORREKT_RSS='http://minkorrekt.de/feed/'

mi_feed = feedparser.parse(MINKORREKT_RSS)

newest_episode = mi_feed['items'][0]

episode_release = datetime.fromtimestamp(mktime(newest_episode['published_parsed'])
