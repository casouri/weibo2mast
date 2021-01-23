#!/usr/bin/env python

import json
import os
from datetime import datetime
import time
import random
import logging

from mastodon import Mastodon, MastodonError
import requests

import weibo

POSTED_POST_FILE = 'posted.json'
TOKEN_FILE = 'token.txt'

### Logging

logger = logging.getLogger('xpost')

### Mastodon

def access_token():
    """Return the access token for mastodon app."""
    with open(TOKEN_FILE, 'r') as fl:
        return fl.read().strip()
def error_code(err):
    """Return the error code for MastodonError ERR."""
    err.args[1]

def cross_post(post, mast, config):
    """Post POST to mastodon.
MAST is the mastodon api instance. Return a toot dict.
CONFIG should contain 'toot_len_limit' and 'max_attachment_count'."""
    len_limit = config['toot_len_limit']
    max_attatchment = config['max_attachment_count']

    # Get media url's.
    image_urls = post['pics']
    if image_urls == '':
        image_urls = []
    else:
        image_urls = image_urls.split(',')

    video_urls = post['video_url']
    if video_urls == '':
        video_urls = []
    else:
        video_urls = video_urls.split(';')

    # Upload media.
    media_list = []
    media_too_large = False
    media_too_many = False
    url_list = image_urls + video_urls
    if len(url_list) > max_attatchment:
        url_list = url_list[:max_attatchment]
        media_too_many = True
    for url in url_list:
        resp = requests.get(url)
        mime = resp.headers['content-type'].split(';')[0].strip()
        # https://mastodonpy.readthedocs.io/en/stable/#media-post
        try:
            ret = mast.media_post(resp.content, mime)
            media_list.append(ret)
        except MastodonError as err:
            if error_code(err) == 422:
                media_too_large = True
                logger.warning(f'Problem uploading media, type: {mime}, url: {url}, error: {err}')
            else:
                raise err


    # Toot!
    post_url = f'https://m.weibo.cn/detail/{post["id"]}'
    body = post['text']
    if len(body)> len_limit - 100:
        body = body[0:400] + '……\n\n（太长了，完整版看原微博）'
    if media_too_large or media_too_many:
        body += '\n\n（有些图片/视频因为太多/太大传不了，完整版看原微博）'
    text = '#{}_bot\n\n{}\n\n源: {}'.format(post['screen_name'],
                                        body,
                                        post_url)

    # toot_id_list = []
    # # Mastodon has a 500 character limit.
    # toot_id = None
    # for idx in range(1 + (len(text) // len_limit)):
    #     text_idx = idx * len_limit
    #     text_end_idx = text_idx + len_limit
    #     toot_id = mast.status_post(text[text_idx:text_end_idx],
    #                                in_reply_to_id=toot_id,
    #                                media_ids=media_list)['id']
    #     toot_id_list.append(toot_id)

    return [mast.status_post(text, media_ids=media_list)['id']]

def delete_all_toots(mast):
    """Delete all toots."""
    user_id = mast.me()['id']
    while True:
        toots = mast.account_statuses(user_id)
        if toots == []:
            return
        else:
            for toot in toots:
                mast.status_delete(toot['id'])
                time.sleep(random.randint(1,5))

### Post

def save_posted(posted):
    """Save post id's in POST_LIST to POSTED_POST_FILE."""
    with open(POSTED_POST_FILE, 'w') as fl:
        json.dump(posted, fl)

def get_posted():
    """Return a list of {'toot_id_list': [], 'weibo_id': id}."""
    with open(POSTED_POST_FILE, 'r') as fl:
        return json.load(fl)

def cross_posted_p(post, posted):
    """Return True if POST is in POSTED.
POST is a dictionary returned by Weibo.get_one_weibo().
POSTED is a list of {'toot_id_list': [], 'weibo_id': id}."""
    for elm in posted:
        if elm['weibo_id'] == post['id']:
            return True
    return False

def add_dummy_config(config):
    """Add dummy config entries to CONFIG."""
    # These attribtues are not useful for xpost and aren't actually
    # used, but are required by weibo crawler.
    config['since_date'] = '2018-01-01'
    config['start_page'] = 1
    config['write_mode'] = ['csv']
    config['original_pic_download'] = 1
    config['retweet_pic_download'] = 0
    config['original_video_download'] = 1
    config['retweet_video_download'] = 0
    config['result_dir_name'] = 0
    return config

### Main

if __name__ == '__main__':
    if not os.path.exists(POSTED_POST_FILE):
        with open(POSTED_POST_FILE, 'w') as fl:
            json.dump([], fl)

    posted = get_posted()

    url = weibo.get_config()['mastodon_instance_url']
    mast = Mastodon(access_token=access_token(), api_base_url=url,
                    request_timeout=30)

    while True:
        logger.info('Awake, running...')
        # Reload configuration on-the-fly.
        config = add_dummy_config(weibo.get_config())

        # Crawl weibo posts.
        wb = weibo.Weibo(config)
        for user_config in wb.user_config_list:
            wb.initialize_info(user_config)
            # We have to get user_info first, ‘get_one_page’ uses
            # information retrieved by it.
            wb.get_user_info()
            # Only crawl the first page, that should be more than
            # enough.
            wb.get_one_page(1)

            # Cross-post to Mastodon.
            for post in reversed(wb.weibo):
                try:
                    if not cross_posted_p(post, posted):
                        summary = post['text'][:30].replace('\n', ' ')
                        logger.debug('user_id: %s\tpost_id: %s',
                                     post['user_id'], post['id'])
                        logger.info('Cross posting weibo by %s: %s...',
                                    wb.user['screen_name'], summary)

                        toot_id_list = cross_post(post, mast, config)
                        logger.debug('toot_id_list: %s', toot_id_list)
                        posted.append({'toot_id_list': toot_id_list,
                                       'weibo_id': post['id']})
                        save_posted(posted)
                        logger.info('Posted')
                except MastodonError as err:
                    logger.warning(f'Something went wrong when cross posting to Mastodon: {err}')
        logger.info('Done')
        sleep_time = random.randint(5, 10)
        logger.info(f'Sleeping for {sleep_time} minutes')
        time.sleep(sleep_time * 60)
