#!/bin/sh

#for normal deployment ignore this file, it is only useful for docker deployment
pip install requests
pip install feedparser
python /opt/repo/mi-bot.py

