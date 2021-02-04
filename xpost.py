#!/usr/bin/env python

import json
import os
from datetime import datetime
import time
import random
import logging
import sqlite3
import re
import unicodedata

from mastodon import Mastodon, MastodonError, MastodonAPIError, MastodonNotFoundError
import requests

import weibo

DATABASE_FILE = 'posted.json'
TOKEN_FILE = 'token.txt'

### Types
#
# POST_RECORD := [int(toot_id), int(weibo_id), int(user_id), str(user_name), str(post summary), str(post time)]
# TOOT_DICT := (Refer https://mastodonpy.readthedocs.io/en/stable/#toot-dicts)
# CONFIG := {
#             'user_list': USER_CONFIG,
#             'mastodon_instance_url': str,
#             'toot_len_limit': int,
#             'max_attachment_count': int
#             'include_repost': bool,
#             'external_media': bool, (optional)
#             'standalone_repost': bool,
#             'include_post_url': bool
#           }
# USER_CONFIG := {
#                  'id': int,
#                  'include_repost': bool, (optional)
#                  'external_media': bool, (optional)
#                  'standalone_repost': bool  (optional)
#                 }

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


def collect_media_url(post, recursive=False):
    """Return a list of MEDIA_URL in POST.
MEDIA_URL := {'type': str, 'url': str}.
If RECURSIVE is True, also include url's from original post."""
    url_list = []

    if post['pics'] != '':
        for url in post['pics'].split(','):
            url_list.append({'type': 'image', 'url': url})

    if post['video_url'] != '':
        for url in post['video_url'].split(';'):
            url_list.append({'type': 'video', 'url': url})

    orig_post = post.get('retweet')
    if orig_post and recursive:
        url_list += collect_media_url(orig_post)

    return url_list


def upload_media(url_list):
    """Upload media in URL_LIST.
URL_LIST should be a list of MEDIA_URL. Return (TOOT_LIST, TOO_LARGE,
TOO_MANY). TOOT_LIST is a list of TOOT_DICT.
"""
    media_list = []
    media_too_large = False
    media_too_many = False
    if len(url_list) > max_attatchment:
        url_list = url_list[:max_attatchment]
        media_too_many = True
    for media_url in url_list:
        url = media_url['url']
        resp = requests.get(url)
        mime = resp.headers['content-type'].split(';')[0].strip()
        # https://mastodonpy.readthedocs.io/en/stable/#media-post
        try:
            ret = mast.media_post(resp.content, mime)
            media_list.append(ret)
        except MastodonAPIError as err:
            if error_code(err) == 422:
                media_too_large = True
                logger.warning(f'Problem uploading media, type: {mime}, url: {url}, error: {err}')
    return (media_list, media_too_large, media_too_many)


def cross_post(post, mast, config, db):
    """Cross-post POST to mastodon.
MAST is the mastodon api instance. Return a list of POST_RECORD.
"""
    len_limit = config['toot_len_limit'] - 100
    max_attatchment = config['max_attachment_count']
    user_id = post['user_id']
    # external_media is specific to monado.ren.
    external_media = get_user_option(user_id, 'external_media', config)
    standalone_repost = get_user_option(user_id,
                                        'standalone_repost',
                                        config)
    include_post_url = get_user_option(user_id, 'include_post_url',
                                       config)
    post_record_list = []
    orig_toot_id = None

    # Maybe upload media.
    url_list = collect_media_url(post, not standalone_repost)
    media_list = None
    media_too_large = False
    media_too_many = False
    if not external_media:
        media_list, media_too_large, media_too_many = \
            upload_media(url_list[:max_attatchment])

    # Compose toot.
    # 1. Compose body text.
    body = '#{0}_bot\n\n{1}\n\n'.format(
        post['screen_name'], post['text']
    )
    if post['video_url'] != '':
        body = body.replace(f'{post["screen_name"]}的微博视频', '')

    # 2. Cleanup.
    res = re.search('发布了头条文章：《.*》', body)
    if res:
        body = body.replace(res.group(0), '')
    body = body.replace('@', ' 艾特 ')

    # 3. Maybe add original post.
    if post_repost_p(post):
        orig_post = post['retweet']
        if standalone_repost:
            record_list = cross_post(orig_post, mast, config, db)
            orig_toot_id = record_list[0][0]
            post_record_list += record_list
            body += '#转_bot\n\n'
        elif get_toot_by_weibo(post, db):
            orig_toot_id = get_toot_by_weibo(post, db)[0]
            body += '#转_bot\n\n'
        else:
            body += '#转_bot #{0}_bot\n\n{1}\n\n'.format(
                orig_post['screen_name'], orig_post['text']
            )

    # 4. Compose postamble
    postamble = ''
    if external_media:
        for media_url in url_list:
            postamble += '{0}:[{1}]\n'.format(
                media_url['type'].upper(), media_url['url'])

    elif media_too_large or media_too_many:
        postamble += '（有些视频图片太多太大，传不了，完整版看原微博）\n'
        include_post_url = True

    # 5. Maybe truncate the post.
    cutoff_notice = '……\n\n（太长了，完整版看原微博）\n'
    body_limit = len_limit - len(postamble) - 25
    if len(body) > body_limit:
        body = body[:body_limit - len(cutoff_notice)]
        text = body + cutoff_notice + postamble
        include_post_url = True
    else:
        text = body + postamble

    # 6. Maybe add post url.
    if include_post_url:
        post_url = f'https://m.weibo.cn/detail/{post["id"]}'
        text += f'源：{post_url}\n'

    # 6. Toot!
    toot = mast.status_post(text, in_reply_to_id=orig_toot_id,
                            media_ids=media_list)
    post_record_list.append(make_post_record(post, toot))
    return post_record_list
    

def delete_all_toots(mast):
    """Delete all toots."""
    user_id = mast.me()['id']
    while True:
        toots = mast.account_statuses(user_id, max_id='105630663083777912        ')
        if toots == []:
            return
        else:
            for toot in toots:
                mast.status_delete(toot['id'])
                print('ok')
        time.sleep(30 * 60)

                
def delete_toot(toot_id, mast):
    """Delete toot with TOOT_ID."""
    try:
        mast.status_delete(toot_id)
    except MastodonNotFoundError:
        return

### Post

def get_match(key, value, lst):
    """Return the element that contains KEY: VALUE in list LST.
Return None if none found."""
    for elm in lst:
        if elm[key] == value:
            return elm
    return None


def post_repost_p(post):
    """Return True if POST is a repost."""
    return True if post.get('retweet') else False


def get_user_option(user_id, option, config):
    """Return the value of OPTION in USER_ID's USER_CONFIG in CONFIG."""
    user_list = config['user_list']
    user = get_match('id', user_id, user_list)
    if user and user.get(option):
        return user.get(option)
    else:
        return config[option]

def get_weibo_posts(config, db):
    """Return a list of weibo posts.
CONFIG is the configuration dictionary described in README.md.
DBC is the database cursor."""
    post_list = []
    wb = weibo.Weibo(make_weibo_config(config))
    for user in wb.user_config_list:
        wb.initialize_info(user)
        # We have to get user_info first, ‘get_one_page’ uses
        # information retrieved by it.
        wb.get_user_info()
        # Only crawl the first page, that should be more than
        # enough.
        wb.get_one_page(1)

        include_repost = get_user_option(int(wb.user['id']),
                                         'include_repost',
                                         config)

        for post in reversed(wb.weibo):
            if cross_posted_p(post, db) \
               or ((not include_repost) and post_repost_p(post)) \
               or '微博抽奖平台' in post['text'] \
               or '转发抽奖' in post['text']:
                continue
            else:
                post_list.append(post)
    return post_list

### Config

def make_weibo_config(config):
    """Return a new CONFIG that Weibo can use."""
    # These options are not useful for xpost and aren't actually
    # used, but are required by weibo crawler.
    conf = config.copy()
    conf['since_date'] = '2018-01-01'
    conf['start_page'] = 1
    conf['write_mode'] = ['csv']
    conf['original_pic_download'] = 1
    conf['retweet_pic_download'] = 0
    conf['original_video_download'] = 1
    conf['retweet_video_download'] = 0
    conf['result_dir_name'] = 0

    # This option is actually useful, we disable filter to crawl both
    # original post and reposts.
    conf['filter'] = 0

    # Translate user_list to user_id_list.
    user_id_list = []
    for user in conf['user_list']:
        user_id_list.append(str(user['id']))
    conf['user_id_list'] = user_id_list

    return conf


def validate_config(config):
    """Retrieve options from CONFIG. If some options are not present,
Python will emit KeyError."""
    for user in config['user_list']:
        user['id']
    config['mastodon_instance_url'], config['toot_len_limit'],
    config['max_attachment_count'], config['standalone_repost'],
    config['include_repost'], config['include_post_url']


def get_config():
    """Return the config dictionary."""
    config_path = os.path.split(os.path.realpath(__file__))[0] \
        + os.sep + 'config.json'
    try:
        with open(config_path, 'r') as fl:
            config = json.load(fl)
        validate_config(config)
        if not config.get('external_media'):
            config['external_media'] = False
        return config

    except FileNotFoundError:
        logger.error(u'找不到 config.json')
        exit(1)
    except json.decoder.JSONDecodeError:
        logger.error(u'config.json 有语法错误，用网上的json validator检查一下吧')
        exit(1)
    except KeyError as err:
        logger.error(u'config.json里缺少这个选项："%s"', err.args[0])
        exit(1)

### Database        

def get_db():
    """Return the database."""
    if not os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'a') as fl:
            json.dump([], fl)
    with open(DATABASE_FILE, 'r') as fl:
        return json.load(fl)

    
def save_db(db):
    """Save DB to file."""
    with open(DATABASE_FILE, 'w') as fl:
        json.dump(db, fl, ensure_ascii=False, indent=2)

        
def cross_posted_p(post, db):
    """Return True if POST is in DB.
POST is a dictionary returned by Weibo.get_one_weibo()."""
    return True if get_toot_by_weibo(post, db) else False


def get_toot_by_weibo(post, db):
    """Return TOOT_ID_LIST that corresponds to POST in DB.
Return None, if there is no correspoding toot."""
    toot_id_list = []
    for row in db:
        if row[1] == post['id']:
            toot_id_list.append(row[0])
    if toot_id_list == []:
        return None
    else:
        return toot_id_list

    
def make_post_record(post, toot):
    """Return a POST_RECORD composed with POST and TOOT."""
    return [
        toot['id'], post['id'], post['user_id'],
        unicodedata.normalize('NFC', post['screen_name']),
        post['text'][:20],
        datetime.now().isoformat()
    ]

def record_older_than(record, n):
    """If record older than N days, return True."""
    seconds = n * 24 * 3600
    post_time = datetime.fromisoformat(record[5])
    today = datetime.now()
    return (today - post_time).total_seconds() > seconds

def get_old_records(db, config):
    """Get old records that needs to be deleted according to CONFIG."""
    days = config['delete_after_days']
    if days == 0:
        return []
    else:
        delete_list = []
        for record in db:
            if record_older_than(record, days):
                delete_list.append(record)
        return delete_list
    
### Main

if __name__ == '__main__':
    db = get_db()
    url = get_config()['mastodon_instance_url']
    mast = Mastodon(access_token=access_token(), api_base_url=url,
                    request_timeout=30)

    while True:
        logger.info('Awake, running')
        # Reload configuration on-the-fly.
        config = get_config()
        try:
            post_list = get_weibo_posts(config, db)
        except Exception:
            post_list = []

        for post in post_list:
            summary = post['text'][:30].replace('\n', ' ')
            logger.info('Cross posting weibo by %s: %s...',
                        post['screen_name'], summary)
            try:
                db += cross_post(post, mast, config, db)
                save_db(db)
                logger.info('Posted')
            except MastodonError as err:
                logger.warning(f'Error cross-posting to Mastodon: {err}')

        logger.info('Deleting old toots')
        for record in get_old_records(db, config):
            logger.info('Deleting post by %s: %s', record[3],
                        record[4].replace('\n', ' '))
            try:
                delete_toot(record[0], mast)
                db.remove(record)
                save_db(db)
            except MastodonError as err:
                logger.warning(f'Error when deleting toot: {err}')

        logger.info('Done')
        sleep_time = random.randint(10, 20)
        logger.info(f'Sleeping for {sleep_time} minutes')
        time.sleep(sleep_time * 60)
