#!/usr/bin/env python3

import os
import urllib
import random
import re
from time import mktime, sleep
from datetime import datetime as dt

import feedparser
import requests
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext


# Read bot token from environment
TOKEN = os.environ['MIA_TG_TOKEN']
CHATID = os.environ['MIA_TG_CHATID']
URL = f"https://api.telegram.org/bot{TOKEN}/"


# code not using python-telegram-bot library
def get_url(url):
    response = requests.get(url)
    content = response.content.decode("utf8")
    return content


def get_last_chat_id_and_text(updates):
    num_updates = len(updates["result"])
    last_update = num_updates - 1
    text = updates["result"][last_update]["message"]["text"]
    chat_id = updates["result"][last_update]["message"]["chat"]["id"]
    return text, chat_id


def send_message(text, chat_id):
    text = re.sub('(?<!\\\\)!', '\\!', text)
    text = re.sub('(?<!\\\\)#', '\\#', text)
    text = urllib.parse.quote_plus(text)
    url = (f"{URL}sendMessage?text={text}"
           f"&chat_id={chat_id}"
           "&parse_mode=MarkdownV2")
    get_url(url)


def tg_send(text):
    send_message(text, CHATID)


def check_minkorrekt(max_age=3600):
    MINKORREKT_RSS = 'http://minkorrekt.de/feed/'
    mi_feed = feedparser.parse(MINKORREKT_RSS)
    newest_episode = mi_feed['items'][0]
    episode_release = dt.fromtimestamp(mktime(newest_episode['published_parsed']))
    if (dt.now() - episode_release).total_seconds() < max_age:
        tg_send(f'*{newest_episode.title}*\n'
                'Eine neue Folge Methodisch inkorrekt ist erschienen\\!\n'
                f'[Jetzt anhören]({newest_episode.link})')


def check_youtube(max_age=3600):
    YOUTUBE_RSS = 'https://www.youtube.com/feeds/videos.xml?channel_id=UCa8qyXCS-FTs0fHD6HJeyiw'
    yt_feed = feedparser.parse(YOUTUBE_RSS)
    newest_episode = yt_feed['items'][0]
    episode_release = dt.fromtimestamp(mktime(newest_episode['published_parsed']))
    if (dt.now() - episode_release).total_seconds() < max_age:
        tg_send(f'*{newest_episode.title}*\n'
                'Eine neues Youtube Video ist erschienen!\n'
                f'[Jetzt ansehen]({newest_episode.link})')


def get_episode_titles():
    MINKORREKT_RSS = 'http://minkorrekt.de/feed/mp3'
    mi_feed = feedparser.parse(MINKORREKT_RSS)
    return [i.title for i in mi_feed['items']]


MINKORREKT_TITLES = get_episode_titles()


def feed_loop():
    while True:
        check_minkorrekt(3600)
        check_youtube(3600)
        sleep(3595)


# python-telegram-bot library
def cookie(update: Update, context: CallbackContext) -> None:
    text = random.choice(MINKORREKT_TITLES)
    update.message.reply_text(f'\U0001F36A {text} \U0001F36A', quote=False)


updater = Updater(TOKEN)

updater.dispatcher.add_handler(CommandHandler('keks', cookie))


if __name__ == '__main__':
    updater.start_polling()
    feed_loop()
    updater.idle()
