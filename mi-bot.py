#!/usr/bin/env python3

import logging
import os
import pickle
import random
import re
import sys
import time
import traceback
import urllib
from datetime import datetime as dt
from subprocess import run

import feedparser
import html2markdown
import requests
from fuzzywuzzy import process
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext


# Read bot token from environment
TOKEN = os.environ['MIA_TG_TOKEN']
CHATID = os.environ['MIA_TG_CHATID']
URL = f"https://api.telegram.org/bot{TOKEN}/"
DUMP = os.getenv('MIA_DUMP', '')
DIRNAME = os.path.dirname(os.path.realpath(__file__))
MINKORREKT_RSS = 'http://minkorrekt.de/feed/mp3'


# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
log_format = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')
log_handler = logging.StreamHandler(sys.stdout)
log_handler.setFormatter(log_format)
log_handler.setLevel(logging.INFO)
logger.addHandler(log_handler)


class PodcastFeed:
    """Represents the parsed and cached podcast RSS feed"""

    def __init__(self, url: str, max_age: int = 3600, dump: str = ''):
        """
        :param url: URL of the feed to be parsed.
        :param max_age: Time in seconds how long the parsed feed is consider valid.
                        The feed will be refreshed automatically on the first access
                        after max_age is passed.
        :param dump: Allows local storage of the feed. If a valid file path, the feed
                     object will be stored there after refresh, and reloaded on
                     re-initialization. Primarily intended to speed loading time for debugging.
        """
        self.url = url
        self.max_age = max_age
        self.dump = dump

        if dump and os.path.isfile(dump):
            try:
                with open(dump, 'rb') as f:
                    self.last_updated, self.feed = pickle.load(f)
                logger.info('Reloaded dumped feed')
            except Exception as exc:
                logger.info(f'{exc!r}\n{traceback.format_exc()}')
                logger.info('Failed loding dumped feed. Falling back to download.')
                self._get_feed()
        else:
            logger.info('Getting feed')
            self._get_feed()

    def _get_feed(self):
        self.feed = feedparser.parse(self.url)
        self.last_updated = time.time()
        logger.info('Done parsing feed')
        if self.dump:
            with open(self.dump, 'wb') as f:
                pickle.dump((self.last_updated, self.feed), f)

    def refresh(self):
        if self.last_updated + self.max_age < time.time():
            logger.info('Refreshing feed')
            self._get_feed()

    def check_new_episode(self, max_age=3600):
        latest_episode = self.latest_episode
        episode_release = dt.fromtimestamp(time.mktime(latest_episode['published_parsed']))
        if (dt.now() - episode_release).total_seconds() < max_age:
            return latest_episode
        return False

    @property
    def latest_episode(self):
        self.refresh()
        return self.feed['items'][0]

    @property
    def episode_titles(self):
        self.refresh()
        return [i.title for i in self.feed['items']]


mi_feed = PodcastFeed(url=MINKORREKT_RSS, dump=DUMP)


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
    text = re.sub('(?<!\\\\)-', '\\-', text)
    text = urllib.parse.quote_plus(text)
    url = (f"{URL}sendMessage?text={text}"
           f"&chat_id={chat_id}"
           "&parse_mode=MarkdownV2")
    get_url(url)


def tg_send(text):
    send_message(text, CHATID)


def check_minkorrekt(max_age=3600):
    new_episode = mi_feed.check_new_episode(max_age=max_age)
    if new_episode:
        tg_send(f'*{new_episode.title}*\n'
                'Eine neue Folge Methodisch inkorrekt ist erschienen\\!\n'
                f'[Jetzt anhören]({new_episode.link})')


def check_youtube(max_age=3600):
    YOUTUBE_RSS = 'https://www.youtube.com/feeds/videos.xml?channel_id=UCa8qyXCS-FTs0fHD6HJeyiw'
    yt_feed = feedparser.parse(YOUTUBE_RSS)
    newest_episode = yt_feed['items'][0]
    episode_release = dt.fromtimestamp(time.mktime(newest_episode['published_parsed']))
    if (dt.now() - episode_release).total_seconds() < max_age:
        tg_send(f'*{newest_episode.title}*\n'
                'Eine neues Youtube Video ist erschienen!\n'
                f'[Jetzt ansehen]({newest_episode.link})')


def feed_loop():
    while True:
        check_minkorrekt(3600)
        check_youtube(3600)
        time.sleep(3595)


# python-telegram-bot library
def latest_episode(update: Update, context: CallbackContext) -> None:
    latest_episode = mi_feed.latest_episode
    episode_release = dt.fromtimestamp(time.mktime(latest_episode['published_parsed'])).date()
    datum = episode_release.strftime('%d.%m.%Y')
    text = (f'Die letzte Episode ist *{latest_episode.title}* vom {datum}.\n'
            f'[Jetzt anhören]({latest_episode.link})')
    update.message.reply_text(text, quote=False, parse_mode=ParseMode.MARKDOWN)


def cookie(update: Update, context: CallbackContext) -> None:
    text = random.choice(mi_feed.episode_titles)
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
    topics_all_episodes = [[i.title, i.content[0].value.replace("<!-- /wp:paragraph -->", "").replace("<!-- wp:paragraph -->", "")] for i in mi_feed.feed.entries]
    ratios = process.extract(search_term, topics_all_episodes)
    episodes = [ratio[0][0] for ratio in ratios[:3]]
    text = "Die besten 3 Treffer sind die Episoden:\n" + "\n".join(episodes)
    update.message.reply_text(text, quote=False, parse_mode=ParseMode.MARKDOWN)

def topics_of_episode(update: Update, context: CallbackContext) -> None:
    topics_all_episodes = [[i.title, i.content[0].value.replace("<!-- /wp:paragraph -->", "").replace("<!-- wp:paragraph -->", "")] for i in mi_feed.feed.entries]
    i = update.message.text.find(' ')
    if i > 0:
        episode_number = update.message.text[i+1:]
    try:
        episode_number = int(episode_number)
        # Special case for the split episodes 12 and 12b
        if episode_number >= 13:
            index_number  = len(topics_all_episodes)-2-episode_number
        else:
            index_number = len(topics_all_episodes)-1-episode_number
    except:
        print("Es gab einen Fehler mit der Episodennummer.\nStelle sicher, dass du eine Zahl angegeben hast!")
    # If someone asks for episode number 12, they will automatically retrieve
    # episode 12b as well since they basically belong together
    if episode_number == 12:
        episode_topics = topics_all_episodes[index_number-1:index_number+1][::-1]
        episode_topics = ["".join(tops) for tops in episode_topics]
    else:
        episode_topics = topics_all_episodes[index_number]
    episode_topics = " ".join(episode_topics)
    topic_start_points = [m.start() for m in re.finditer("Thema [1, 2, 3, 4]", episode_topics)]
    topic_end_points = []
    for start in topic_start_points:
        topic_end_points.append(start + episode_topics[start:].find('\n'))
    if 0 == len(topic_start_points):
        return "Themen nicht gefunden.\nWahrscheinlich Nobelpreis/Jahresrückblick-Folge"
    topics = [html2markdown.convert(episode_topics[start:end]) for start, end in zip(topic_start_points, topic_end_points)]
    topics_text = "\n".join(topics)
    episode_title = "12a Du wirst wieder angerufen! & 12b Previously (on) Lost" if episode_number == 12 else topics_all_episodes[index_number][0]
    text = f"Die Themen von Folge {episode_title} sind:\n{topics_text}"
    update.message.reply_text(text, quote=False, parse_mode=ParseMode.MARKDOWN)


updater = Updater(TOKEN)

updater.dispatcher.add_handler(CommandHandler('findeStichwort', fuzzy_topic_search))
updater.dispatcher.add_handler(CommandHandler('themenVonFolgeX', topics_of_episode))
updater.dispatcher.add_handler(CommandHandler('letzteEpisode', latest_episode))
updater.dispatcher.add_handler(CommandHandler('keks', cookie))
updater.dispatcher.add_handler(CommandHandler('crowsay', crowsay))


if __name__ == '__main__':
    updater.start_polling()
    feed_loop()
    # updater.idle()
