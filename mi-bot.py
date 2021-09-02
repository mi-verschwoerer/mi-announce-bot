#!/usr/bin/env python3

import os
import urllib
import random
import re
from time import mktime, sleep
from datetime import datetime as dt
from subprocess import run

import feedparser
import requests
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext

import html2markdown
from fuzzywuzzy import fuzz
from fuzzywuzzy import process

# Read bot token from environment
TOKEN = os.environ['MIA_TG_TOKEN']
CHATID = os.environ['MIA_TG_CHATID']
URL = f"https://api.telegram.org/bot{TOKEN}/"
DIRNAME = os.path.dirname(os.path.realpath(__file__))


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
def latest_episode(update: Update, context: CallbackContext) -> None:
    MINKORREKT_RSS = 'http://minkorrekt.de/feed/'
    mi_feed = feedparser.parse(MINKORREKT_RSS)
    newest_episode = mi_feed['items'][0]
    episode_release = dt.fromtimestamp(mktime(newest_episode['published_parsed'])).date()
    datum = episode_release.strftime('%d.%m.%Y')
    text = (f'Die letzte Episode ist *{newest_episode.title}* vom {datum}.\n'
            f'[Jetzt anhören]({newest_episode.link})')
    update.message.reply_text(text, quote=False, parse_mode=ParseMode.MARKDOWN)


def cookie(update: Update, context: CallbackContext) -> None:
    text = random.choice(MINKORREKT_TITLES)
    update.message.reply_text(f'\U0001F36A {text} \U0001F36A', quote=False)


def crowsay(update: Update, context: CallbackContext) -> None:
    i = update.message.text.find(' ')
    if i > 0:
        text = update.message.text[i+1:]
    else:
        r = run('fortune', capture_output=True, encoding='utf-8')
        text = r.stdout

    crowfile = os.path.join(DIRNAME, 'crow.cow')
    r = run(['cowsay', '-f', crowfile, text],
            capture_output=True, encoding='utf-8')
    text = r.stdout
    update.message.reply_text(f'```\n{text}\n```', quote=False, parse_mode=ParseMode.MARKDOWN)


def fuzzy_topic_search(update: Update, context: CallbackContext) -> None:
    i = update.message.text.find(' ')
    if i > 0:
        search_term = update.message.text[i+1:]
    topics_all_episodes = [[i.title, i.content[0].value.replace("<!-- /wp:paragraph -->", "").replace("<!-- wp:paragraph -->", "")] for i in mi_feed.entries]
    ratios = process.extract(search_term, topics_all_episodes)
    print("Die besten 3 Treffer sind die Episoden:")
    for ratio in ratios[:3]:
        print(f"{ratio[0][0]}\n-----")
    episodes = [ratio[0][0] for ratio in ratios[:3]]
    return "Die besten 3 Treffer sind die Episoden:\n" + "\n".join(episodes)

def topics_of_episode(update: Update, context: CallbackContext) -> None:
    i = update.message.text.find(' ')
    if i > 0:
         episode_number = update.message.text[i+1:]
    try:
        episode = int(episode_number)
    except:
        print("Es gab einen Fehler mit der Episodennummer.\nStelle sicher, dass du eine Zahl angegeben hast!")
    topics_all_episodes = [[i.title, i.content[0].value.replace("<!-- /wp:paragraph -->", "").replace("<!-- wp:paragraph -->", "")] for i in mi_feed.entries]
    episode_topics = topics_all_episodes[episode]
    episode_topics = " ".join(episode_topics)
    topic_start_points = [m.start() for m in re.finditer("Thema [1, 2, 3, 4]", episode_topics)]
    topic_end_points = []
    for start in topic_start_points:
        topic_end_points.append(start + episode_topics[start:].find('\n'))
    if 0 == len(topic_start_points):
        return "Themen nicht gefunden.\nWahrscheinlich Nobelpreis/Jahresrückblick-Folge"
    topics = [html2markdown.convert(episode_topics[start:end]) for start, end in zip(topic_start_points, topic_end_points)]
    return topics



updater = Updater(TOKEN)

updater.dispatcher.add_handler(CommandHandler('findeFolge', fuzzy_topic_search))
updater.dispatcher.add_handler(CommandHandler('themenVonFolgeX', topics_of_episode))
updater.dispatcher.add_handler(CommandHandler('letzteEpisode', latest_episode))
updater.dispatcher.add_handler(CommandHandler('keks', cookie))
updater.dispatcher.add_handler(CommandHandler('crowsay', crowsay))


if __name__ == '__main__':
    updater.start_polling()
    feed_loop()
    # updater.idle()
