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
import sqlite3
import atexit

from mastodon import Mastodon, MastodonError, MastodonAPIError, MastodonNotFoundError
import requests

import weibo

DATABASE_FILE = 'posted.sqlite3'
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
The list could be empty, in which case nothing is tooted.
"""
    if not should_cross_post(post, config, db):
        return []

    len_limit = config['toot_len_limit'] - 100
    max_attatchment = config['max_attachment_count']
    user_id = str(post['user_id'])
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
            # If the original weibo is already cross posted, we don’t
            # cross post it again.
            orig_toot_id = get_toot_by_weibo(post, db)
            if orig_toot_id == None:
                orig_record_list = cross_post(orig_post, mast, config, db)
                if len(orig_toot_id) > 0:
                    orig_toot_id = orig_record_list[0][0]
                post_record_list += orig_record_list
            body += '#转_bot\n\n'
        elif get_toot_by_weibo(post, db) != None:
            orig_toot_id = get_toot_by_weibo(post, db)
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
DB is the database."""
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
        post_list += reversed(wb.weibo)

    return post_list


def should_cross_post(post, config, db):
    """If the POST (a dictionary) should be posted, return True.
DB is the database."""
    include_repost = get_user_option(
        int(post['user_id']), 'include_repost', config)
    if cross_posted_p(post, db) \
       or ((not include_repost) and post_repost_p(post)) \
       or '微博抽奖平台' in post['text'] \
       or '转发抽奖' in post['text'] \
       or failed_many_times(post, db):
        # TODO: Other filters.
        return False
    else:
        return True


def failed_many_times(post, db):
    """Return True if POST failed too many times.
DB records the number of times POST failed to cross post.
POST is a dictionary."""
    weibo_id = str(post['id'])
    fail_count = db.execute('SELECT fail_count FROM Post WHERE weibo_id = ?', [weibo_id]).fetchone()
    if fail_count == None:
        return False
    else:
        return fail_count > 3

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
        logger.error(u'找不到config.json')
        exit(1)
    except json.decoder.JSONDecodeError:
        logger.error(u'config.json有语法错误，用网上的json validator检查一下吧')
        exit(1)
    except KeyError as err:
        logger.error(u'config.json里缺少这个选项："%s"', err.args[0])
        exit(1)

### Database        

def get_db():
    """Return the database."""
    connection = sqlite3.connect(DATABASE_FILE)
    # If the table is not created, create it.
    connection.execute('CREATE TABLE if not exists Post (toot_id text, weibo_id text, user_id text, user_name text, post_sum text, post_time text, fail_count integer);')
    return connection


def cross_posted_p(post, db):
    """Return True if POST is in DB.
POST is a dictionary returned by Weibo.get_one_weibo()."""
    return get_toot_by_weibo(post, db) != None


def get_toot_by_weibo(post, db):
    """Return TOOT_ID that corresponds to POST in DB.
Could return None. POST is a dictionary.
"""
    weibo_id = str(post['id'])
    cur = db.execute('SELECT toot_id FROM Post WHERE weibo_id = ?', [weibo_id])
    return cur.fetchone()

def get_record_by_weibo(post, db):
    """Return a dictionary of the record for POST in DB.
POST is a dictionary.
"""
    weibo_id = str(post['id'])
    cur = db.execute('SELECT * FROM Post WHERE weibo_id = ?', [weibo_id])
    return cur.fetchone()


def make_post_record(post, toot):
    """Return a POST_RECORD composed with POST and TOOT.
POST is the data structure returned from weibo-crawler."""
    return (
        toot['id'],
        str(post['id']),
        str(post['user_id']),
        unicodedata.normalize('NFC', post['screen_name']),
        post['text'][:20],
        datetime.now().isoformat(),
        0
    )


def record_failure(post, db):
    """Record a failure to cross post POST in DB.
POST is a dictionary."""
    weibo_id = str(post['id'])
    summary = post['text'][:20]
    user_id = str(post['user_id'])
    user_name = unicodedata.normalize('NFC', post['screen_name'])
    post_time = datetime.now().isoformat()

    fail_count = db.execute('SELECT fail_count FROM Post WHERE weibo_id = ?', [weibo_id]).fetchone()
    if fail_count != None:
        db.execute('UPDATE Post SET fail_count = ? WHERE weibo_id = ?',
                   (fail_count + 1, weibo_id))
    else:
        db.execute('INSERT INTO Post VALUES (?,?,?,?,?,?,?)',
                   ('', weibo_id, user_id, user_name,
                    summary, post_time, 1))
    db.commit()


def record_success(records, db):
    """Record successful cross postings RECORD in DB.
RECORDS is a list of records (tuple)."""
    ids = [[rec[1]] for rec in records]
    db.executemany('DELETE FROM Post WHERE weibo_id = ?', ids)
    db.executemany('INSERT INTO Post VALUES (?,?,?,?,?,?,?)', records)
    db.commit()


def record_older_than(record, n):
    """If record older than N days, return True."""
    seconds = n * 24 * 3600
    post_time = datetime.fromisoformat(record[5])
    today = datetime.now()
    return (today - post_time).total_seconds() > seconds


### Main

if __name__ == '__main__':
    db = get_db()
    url = get_config()['mastodon_instance_url']
    mast = Mastodon(access_token=access_token(), api_base_url=url,
                    request_timeout=30)
    while True:
        logger.info(u'醒了，运行中')
        # Reload configuration on-the-fly.
        config = get_config()
        try:
            post_list = get_weibo_posts(config, db)
        except Exception as e:
            post_list = []
            print("Failed to get a list of posts from weibo:")
            print(e)

        for post in post_list:
            summary = post['text'][:30].replace('\n', ' ')
            try:
                records = cross_post(post, mast, config, db)
                record_success(records, db)
                if records != []:
                    logger.info(u'转发了%s的微博：%s...',
                                post['screen_name'], summary)
            except MastodonError as err:
                logger.warning(u'试图转发%s的微博：%s...，但没有成功：%s',
                               post['screen_name'], summary, str(err))
                record_failure(post, db)

        logger.info(u'完成')
        sleep_time = random.randint(10, 20)
        logger.info(f'睡{sleep_time}分钟')
        time.sleep(sleep_time * 60)
