#!/usr/bin/env python3

import logging
import os
import pickle
import random
import re
import sys
import time
import traceback
from datetime import datetime as dt
from subprocess import run

import dateparser
import feedparser
import html2markdown
from fuzzywuzzy import process
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode


# Read bot token from environment
TOKEN = os.environ['MIA_TG_TOKEN']
CHAT_IDS = os.environ['MIA_TG_CHATID'].split(',')
URL = f"https://api.telegram.org/bot{TOKEN}/"
DUMP = os.getenv('MIA_DUMP', '')
DIRNAME = os.path.dirname(os.path.realpath(__file__))
PODCAST_FEEDS = os.environ['MIA_PODCAST_FEED'].split(',')
YOUTUBE_FEED = os.getenv('MIA_YOUTUBE_FEED', None)


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
                logger.info(f'Reloaded dumped feed for {self.url}')
            except Exception as exc:
                logger.info(f'{exc!r}\n{traceback.format_exc()}')
                logger.info('Failed loding dumped feed. Falling back to download.')
                self._get_feed()
        else:
            logger.info(f'Loading feed {self.url}')
            self._get_feed()

    def _get_feed(self):
        self.feed = feedparser.parse(self.url)
        self.last_updated = time.time()
        if self.dump:
            with open(self.dump, 'wb') as f:
                pickle.dump((self.last_updated, self.feed), f)

    def refresh(self, force=False):
        if force or (self.last_updated + self.max_age < time.time()):
            logger.debug('Refreshing feed')
            self._get_feed()

    def check_new_episode(self, max_age=3600):
        self.refresh(force=True)
        published = dateparser.parse(self.latest_episode['published'])
        now = dt.now(published.tzinfo)
        logger.debug(f'Episode age = {(now - published).total_seconds()} seconds, '
                     f'max_age = {max_age} seconds')
        if (now - published).total_seconds() < max_age:
            return self.latest_episode
        return False

    @property
    def latest_episode(self):
        return self.feed['items'][0]

    @property
    def episode_titles(self):
        self.refresh()
        return [i.title for i in self.feed['items']]

    @property
    def title(self):
        return self.feed['feed'].get('title', None)


podcast_feeds = []
for i, feed in enumerate(PODCAST_FEEDS):
    podcast_feeds.append(PodcastFeed(url=feed, dump=f'{DUMP}_{i}'))
podcast_feed = podcast_feeds[0]  # select main feed


if YOUTUBE_FEED:
    yt_feed = feedparser.parse(YOUTUBE_FEED)


def markdownv2_escape(text):
    """Escapes all necessary characters and returns valid MarkdownV2 style.

    See: https://core.telegram.org/bots/api#markdownv2-style
    """
    return re.sub(r'([_*\[\]\(\)~`>#+\-=|{}.!\\])', r'\\\1', text)


async def tg_broadcast(text: str, context: ContextTypes.DEFAULT_TYPE):
    """Sends the message `text` to all CHAT_IDS."""
    for chat_id in CHAT_IDS:
        await context.bot.send_message(chat_id=chat_id,
                                       text=text,
                                       parse_mode=ParseMode.MARKDOWN_V2)


async def check_podcast(context: ContextTypes.DEFAULT_TYPE):
    max_age = context.job.data.get('max_age', 3600)
    for podcast_feed in podcast_feeds:
        logger.debug(f'Periodic check for {podcast_feed.title}')
        new_episode = podcast_feed.check_new_episode(max_age=max_age)
        logger.info(f'Checked for new episode: {bool(new_episode)}. '
                    f'Latest episode is: {podcast_feed.latest_episode.title}')
        if new_episode:
            title = markdownv2_escape(podcast_feed.title)
            message = (f'*{markdownv2_escape(new_episode.title)}*\n'
                       f'Eine neue Folge von "{title}" ist erschienen\\!\n'
                       f'[Jetzt anhören]({new_episode.link})')
            await tg_broadcast(message, context)


async def check_youtube(context: ContextTypes.DEFAULT_TYPE):
    max_age = context.job.data.get('max_age', 3600)
    logger.debug(f'Periodic check for {yt_feed.title}')
    new_episode = yt_feed.check_new_episode(max_age=max_age)
    logger.info(f'Checked for new episode: {bool(new_episode)}. '
                f'Latest episode is: {yt_feed.latest_episode.title}')
    if new_episode:
        message = (f'*{markdownv2_escape(new_episode.title)}*\n'
                   f'Ein neues Youtube Video ist erschienen\\!\n'
                   f'[Jetzt ansehen]({new_episode.link})')
        await tg_broadcast(message, context)


async def latest_episode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    latest_episode = podcast_feed.latest_episode
    episode_release = dateparser.parse(latest_episode['published']).date()
    datum = episode_release.strftime('%d\\.%m\\.%Y')
    text = (f'Die letzte Episode ist *{markdownv2_escape(latest_episode.title)}* vom {datum}\\.\n'
            f'[Jetzt anhören]({latest_episode.link})')
    await update.message.reply_text(text, quote=False, parse_mode=ParseMode.MARKDOWN_V2)


async def cookie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = random.choice(podcast_feed.episode_titles)
    await update.message.reply_text(f'\U0001F36A {text} \U0001F36A', quote=False)


async def crowsay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    text = markdownv2_escape(text)
    await update.message.reply_text(f'```\n{text}\n```',
                                    quote=False, parse_mode=ParseMode.MARKDOWN_V2)


async def fuzzy_topic_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    i = update.message.text.find(' ')
    if i > 0:
        search_term = update.message.text[i+1:]
    topics_all_episodes = [[
        i.title,
        i.content[0].value.replace("<!-- /wp:paragraph -->",
                                   "").replace("<!-- wp:paragraph -->", "")
    ] for i in podcast_feed.feed.entries]
    ratios = process.extract(search_term, topics_all_episodes)
    episodes = [ratio[0][0] for ratio in ratios[:3]]
    text = "Die besten 3 Treffer sind die Episoden:\n" + "\n".join(episodes)
    await update.message.reply_text(text, quote=False, parse_mode=ParseMode.MARKDOWN)


async def topics_of_episode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topics_all_episodes = [[
        i.title,
        i.content[0].value.replace("<!-- /wp:paragraph -->",
                                   "").replace("<!-- wp:paragraph -->", "")
    ] for i in podcast_feed.feed.entries]
    i = update.message.text.find(' ')
    if i > 0:
        episode_number = update.message.text[i+1:]
    if episode_number.isnumeric():
        episode_number = int(episode_number)
        # Special case for the split episodes 12 and 12b
        if episode_number >= 13:
            index_number = len(topics_all_episodes)-2-episode_number
        else:
            index_number = len(topics_all_episodes)-1-episode_number
    else:
        print("Es gab einen Fehler mit der Episodennummer.\n"
              "Stelle sicher, dass du eine Zahl angegeben hast!")
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
        return ("Themen nicht gefunden.\n"
                "Wahrscheinlich Nobelpreis/Jahresrückblick-Folge")
    topics = [
        html2markdown.convert(episode_topics[start:end])
        for start, end in zip(topic_start_points, topic_end_points)
    ]
    topics_text = "\n".join(topics)
    if episode_number == 12:
        episode_title = "12a Du wirst wieder angerufen! & 12b Previously (on) Lost"
    else:
        episode_title = topics_all_episodes[index_number][0]
    text = f"Die Themen von Folge {episode_title} sind:\n{topics_text}"
    await update.message.reply_text(text, quote=False, parse_mode=ParseMode.MARKDOWN)


async def debug_new_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    job_queue.run_once(check_podcast, when=0, data={'max_age': 3600*24*30})


bot = Application.builder().token(TOKEN).get_updates_http_version('1.1').http_version('1.1').build()

bot.add_handler(CommandHandler('findeStichwort', fuzzy_topic_search))
bot.add_handler(CommandHandler('themenVonFolgeX', topics_of_episode))
bot.add_handler(CommandHandler('letzteEpisode', latest_episode))
bot.add_handler(CommandHandler('keks', cookie))
bot.add_handler(CommandHandler('crowsay', crowsay))
bot.add_handler(CommandHandler('debugNewEpisode', debug_new_episode))

job_queue = bot.job_queue
job = job_queue.run_repeating(check_podcast, interval=3595, first=5, data={'max_age': 3600})
if YOUTUBE_FEED:
    job_yt = job_queue.run_repeating(check_youtube, interval=3595, first=5, data={'max_age': 3600})


if __name__ == '__main__':
    bot.run_polling()
