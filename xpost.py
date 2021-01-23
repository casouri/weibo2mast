#!/usr/bin/env python

import json
import os
from datetime import date, datetime, timedelta
import time
import random

from mastodon import Mastodon
import requests

import weibo

POSTED_POST_FILE = 'posted.json'
MAST_INSTANCE_URL = 'https://botsin.space'

### Mastodon

def access_token():
    """Return the access token for mastodon app."""
    with open('token', 'r') as fl:
        return fl.read().strip()

def cross_post(post, mast):
    """Post POST to mastodon.
MAST is the mastodon api instance. Return a toot dict."""
    post_url = f'https://m.weibo.cn/detail/{post["id"]}'
    text = '{}:\n\n{}\n\n源: {}'.format(post['screen_name'],
                                        post['text'],
                                        post_url)

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

    media_list = []
    for url in image_urls + video_urls:
        resp = requests.get(url)
        mime = resp.headers['content-type'].split(';')[0].strip()
        # https://mastodonpy.readthedocs.io/en/stable/#media-post
        try:
            ret = mast.media_post(resp.content, mime)
            media_list.append(ret)
        except MastodonIllegalArgumentError:
            print(f'Problem posting media of type {mime} at {url}')
        
    return mast.status_post(text, media_ids=media_list)['id']

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

### Post

def save_posted(posted):
    """Save post id's in POST_LIST to POSTED_POST_FILE."""
    with open(POSTED_POST_FILE, 'w') as fl:
        json.dump(posted, fl)

def get_posted():
    """Return a list of {'toot_id': id, 'weibo_id': id}."""
    with open(POSTED_POST_FILE, 'r') as fl:
        return json.load(fl)

### Main

if __name__ == '__main__':
    if not os.path.exists(POSTED_POST_FILE):
        with open(POSTED_POST_FILE, 'w') as fl:
            json.dump([], fl)
            
    config = weibo.get_config()
    wb = weibo.Weibo(config)
    posted = get_posted()

    mast = Mastodon(access_token=access_token(),
                    api_base_url=MAST_INSTANCE_URL)

    # A list of toot id’s.
    
    while True:
        print('Awake, running...')
        for user_config in wb.user_config_list:
            wb.initialize_info(user_config)
            # You have to get user_info first, ‘get_one_page’ uses
            # information retrieved by it.
            wb.get_user_info()
            # Only crawl the first page, that should be more than
            # enough.
            wb.get_one_page(1)
            for post in reversed(wb.weibo):
                if not (post['id'] in posted):
                    toot_id = cross_post(post, mast)
                    posted.append({'toot_id': toot_id,
                                   'weibo_id': post['id']})
            save_posted(posted)
        print('Done')
        sleep_time = random.randint(5, 10)
        print(f'Sleeping for {sleep_time} minutes')
        time.sleep(sleep_time * 60)
