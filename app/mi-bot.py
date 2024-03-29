#!/usr/bin/env python3

import datetime
import logging
import os
import pickle
import random
import re
import sys
import time
import traceback
from subprocess import run
from typing import List

import dateparser
import feedparser
import html2markdown
from fuzzywuzzy import process
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode


# Read config from from environment variables
TOKEN = os.environ['MIA_TG_TOKEN']
CHAT_IDS = os.environ['MIA_TG_CHATID'].split(',')
URL = f"https://api.telegram.org/bot{TOKEN}/"
DUMP = os.getenv('MIA_DUMP', '')
DIRNAME = os.path.dirname(os.path.realpath(__file__))
PODCAST_FEEDS = os.environ['MIA_PODCAST_FEED'].split(',')
YOUTUBE_FEED = os.getenv('MIA_YOUTUBE_FEED', None)
DEBUG = os.getenv('MIA_DEBUG', '').lower() in ['1', 'true', 'yes', 'y']

if YOUTUBE_FEED:
    PODCAST_FEEDS.append(YOUTUBE_FEED)


# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
log_format = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')
log_handler = logging.StreamHandler(sys.stdout)
log_handler.setFormatter(log_format)
log_handler.setLevel(logging.INFO)
logger.addHandler(log_handler)


def markdownv2_escape(text):
    """Escapes all necessary characters and returns valid MarkdownV2 style.

    See: https://core.telegram.org/bots/api#markdownv2-style
    """
    return re.sub(r'([_*\[\]\(\)~`>#+\-=|{}.!\\])', r'\\\1', text)


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
        self._last_checked_title = None
        self._tzinfo = None

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

    def build_message(self, episode_index: int = 0, new: bool = True) -> str:
        """Build the message informing about the episode.

        :param episode_index: Index of the desired episode.
        :param new: Whether to annouce as a new episode.
        """

        episode = self.feed['items'][episode_index]
        feed_title = markdownv2_escape(self.title)
        episode_title = markdownv2_escape(episode.title)
        web_link = episode.link
        dl_link = self.get_download_link()
        verb = 'ansehen' if self.is_youtube else 'anhören'

        if new:
            message = (f'*{episode_title}*\n'
                       f'Eine neue Folge von "{feed_title}" ist erschienen\\!\n')
        else:
            episode_release = dateparser.parse(episode['published']).date()
            datum = episode_release.strftime('%d\\.%m\\.%Y')
            message = (f'*{feed_title}*\n'
                       f'Die letzte Episode ist *{episode_title}* vom {datum}\\.\n')

        if dl_link:
            message += f'Jetzt {verb}: [Webseite]({web_link}) [Download]({dl_link})'
        else:
            message += f'[Jetzt {verb}]({web_link})'

        return message

    def check_new_episode(self, initial_check_age: int = 3600, max_age: int = None):
        """
        If a new episode was published since the last check, returns the episode.
        Returns `False` otherwise.

        :param initial_check_age: Max age (in seconds) for the initial check.
        :param max_age: Forces (re)advertisement.
        """

        self.refresh(force=True)
        found_new_episode = False
        now = datetime.datetime.now(self.tzinfo)
        initial_check_age = datetime.timedelta(seconds=initial_check_age)
        published = dateparser.parse(self.latest_episode['published'])

        if self._last_checked_title is None:
            # First check, use initial_check_age
            found_new_episode |= published > (now - initial_check_age)
        else:
            # Compare current title against stored title
            found_new_episode |= self._last_checked_title != self.latest_episode.title

        if max_age:
            # Force (re)advertisement if not older than max_age
            max_age = datetime.timedelta(seconds=max_age)
            found_new_episode |= published > (now - max_age)

        self._last_checked_title = self.latest_episode.title

        if found_new_episode:
            return self.build_message()

        return False

    @property
    def episode_titles(self) -> List[str]:
        self.refresh()
        return [i.title for i in self.feed['items']]

    def get_download_link(self, episode_index: int = 0) -> str:
        """Returns the file download link for the requested episode."""
        episode = self.feed['items'][episode_index]
        for link in episode['links']:
            if link['rel'] == 'enclosure':
                return link['href']
        return ''

    @property
    def is_youtube(self) -> bool:
        return 'www.youtube.com/feeds/videos.xml' in self.url

    @property
    def latest_episode(self):
        return self.feed['items'][0]

    @property
    def title(self):
        return self.feed['feed'].get('title', None)

    @property
    def tzinfo(self):
        if self._tzinfo is None:
            published = dateparser.parse(self.latest_episode['published'])
            self._tzinfo = published.tzinfo
        return self._tzinfo


podcast_feeds = []
for i, feed in enumerate(PODCAST_FEEDS):
    podcast_feeds.append(PodcastFeed(url=feed, dump=f'{DUMP}_{i}'))
podcast_feed = podcast_feeds[0]  # select main feed
MINKORREKT = 'Methodisch inkorrekt' in podcast_feed.title


def parse_input(text: str):
    """Splits the input message to extract the selected feed index.
    Returns a tuple `(feed_index: int, arg: str)`.
    """
    match = re.match(r'\/[\w@]+ (\d+|)(.*)', text)
    if not match:
        return 0, ''
    if match.group(1):
        ifeed = min(int(match.group(1)), len(podcast_feeds))
    else:
        ifeed = 1
    arg = match.group(2).strip()
    return ifeed - 1, arg


async def tg_broadcast(text: str, context: ContextTypes.DEFAULT_TYPE):
    """Sends the message `text` to all CHAT_IDS."""
    for chat_id in CHAT_IDS:
        await context.bot.send_message(chat_id=chat_id,
                                       text=text,
                                       parse_mode=ParseMode.MARKDOWN_V2)


async def check_feeds(context: ContextTypes.DEFAULT_TYPE):
    max_age = context.job.data.get('max_age', None)
    initial_check_age = context.job.data.get('initial_check_age', 3600)
    for feed in podcast_feeds:
        logger.info(f'Periodic check for {feed.title} ({feed.url})')
        msg = feed.check_new_episode(initial_check_age=initial_check_age,
                                     max_age=max_age)
        logger.info(f'Checked for new episode: {bool(msg)}. '
                    f'Latest episode is: {feed.latest_episode.title}')
        if msg:
            await tg_broadcast(msg, context)


async def list_feeds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = 'Verfügbare \\(Podcast\\) Feeds:\n'
    for i, feed in enumerate(podcast_feeds):
        title = markdownv2_escape(feed.title)
        link = feed.feed['feed']['link']
        msg += f'{i+1} \\- {title} \\([Webseite]({link}) [Feed]({feed.url})\\)\n'
    await update.message.reply_text(text=msg,
                                    quote=False,
                                    parse_mode=ParseMode.MARKDOWN_V2)


async def latest_episode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ifeed, _ = parse_input(update.message.text)
    msg = podcast_feeds[ifeed].build_message(new=False)
    await update.message.reply_text(text=msg,
                                    quote=False,
                                    parse_mode=ParseMode.MARKDOWN_V2)


async def cookie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = random.choice(podcast_feed.episode_titles)
    await update.message.reply_text(text=f'\U0001F36A {text} \U0001F36A', quote=False)


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
    await update.message.reply_text(text=f'```\n{text}\n```',
                                    quote=False,
                                    parse_mode=ParseMode.MARKDOWN_V2)


async def fuzzy_topic_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ifeed, search_term = parse_input(update.message.text)
    if not search_term:
        help_message = ('Zur Stichwortsuche verwende:\n'
                        '`/findeStichwort FeedNummer Stichwort`\n'
                        'Alle Feed Nummern werden von /feeds aufgelistet.')
        await update.message.reply_text(text=help_message,
                                        quote=False,
                                        parse_mode=ParseMode.MARKDOWN)
        return
    feed = podcast_feeds[ifeed]
    topics_all_episodes = [[
        i.title,
        i.content[0].value.replace('<!-- /wp:paragraph -->',
                                   '').replace('<!-- wp:paragraph -->', '')
    ] for i in feed.feed.entries]
    ratios = process.extract(search_term, topics_all_episodes)
    episodes = [ratio[0][0] for ratio in ratios[:3]]
    text = 'Die besten 3 Treffer sind die Episoden:\n' + '\n'.join(episodes)
    await update.message.reply_text(text=text,
                                    quote=False,
                                    parse_mode=ParseMode.MARKDOWN)


async def topics_of_episode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topics_all_episodes = [[
        i.title,
        i.content[0].value.replace('<!-- /wp:paragraph -->',
                                   '').replace('<!-- wp:paragraph -->', '')
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
        logger.error('Es gab einen Fehler mit der Episodennummer.\n'
                     'Stelle sicher, dass du eine Zahl angegeben hast!')
    # If someone asks for episode number 12, they will automatically retrieve
    # episode 12b as well since they basically belong together
    if episode_number == 12:
        episode_topics = topics_all_episodes[index_number-1:index_number+1][::-1]
        episode_topics = [''.join(tops) for tops in episode_topics]
    else:
        episode_topics = topics_all_episodes[index_number]
    episode_topics = ' '.join(episode_topics)
    topic_start_points = [m.start() for m in re.finditer('Thema [1, 2, 3, 4]', episode_topics)]
    topic_end_points = []
    for start in topic_start_points:
        topic_end_points.append(start + episode_topics[start:].find('\n'))
    if 0 == len(topic_start_points):
        return ('Themen nicht gefunden.\n'
                'Wahrscheinlich Nobelpreis/Jahresrückblick-Folge')
    topics = [
        html2markdown.convert(episode_topics[start:end])
        for start, end in zip(topic_start_points, topic_end_points)
    ]
    topics_text = '\n'.join(topics)
    if episode_number == 12:
        episode_title = '12a Du wirst wieder angerufen! & 12b Previously (on) Lost'
    else:
        episode_title = topics_all_episodes[index_number][0]
    text = f'Die Themen von Folge {episode_title} sind:\n{topics_text}'
    await update.message.reply_text(text=text,
                                    quote=False,
                                    parse_mode=ParseMode.MARKDOWN)


async def debug_new_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    match = re.match(r'\/[\w@]+ (\d+)', update.message.text)
    if match:
        max_age = int(match.group(1))
    else:
        max_age = 3600*24*30
    job_queue.run_once(check_feeds, when=0, data={'max_age': max_age})


application = Application.builder().token(TOKEN)\
    .get_updates_http_version('1.1').http_version('1.1').build()

application.add_handler(CommandHandler('findeStichwort', fuzzy_topic_search))
application.add_handler(CommandHandler('feeds', list_feeds))
application.add_handler(CommandHandler('letzteEpisode', latest_episode))

if MINKORREKT:
    application.add_handler(CommandHandler('keks', cookie))
    application.add_handler(CommandHandler('crowsay', crowsay))
    application.add_handler(CommandHandler('themenVonFolgeX', topics_of_episode))

if DEBUG:
    application.add_handler(CommandHandler('debugNewEpisode', debug_new_episode))

job_queue = application.job_queue
job = job_queue.run_repeating(callback=check_feeds,
                              interval=3600,
                              first=5,
                              data={'initial_check_age': 3600})


if __name__ == '__main__':
    application.run_polling()
