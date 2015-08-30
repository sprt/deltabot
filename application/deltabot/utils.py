from datetime import datetime, timedelta
from functools import partial
import os
import re

from enum import Enum
from google.appengine.ext import deferred
from google.appengine.ext import ndb
from jinja2 import Environment, FileSystemLoader
import praw

from . import config
from .models import KeyValueStore

_NDB_ANCESTOR = ndb.Key('_dummy', 1)


KVStore_get = partial(KeyValueStore.get, parent=_NDB_ANCESTOR)
KVStore_exists = partial(KeyValueStore.exists, parent=_NDB_ANCESTOR)
KVStore_set = partial(KeyValueStore.set, parent=_NDB_ANCESTOR)


def defer(callable, *args, **kwargs):
    if ndb.in_transaction() and kwargs.get('_transactional') is not False:
        kwargs['_transactional'] = True
    deferred.defer(callable, *args, **kwargs)


# XXX: minimum delay?
defer_reddit = partial(defer, _queue='reddit')


def ndb_query(model, *args, **kwargs):
    kwargs['ancestor'] = _NDB_ANCESTOR
    return model.query(*args, **kwargs)


def ndb_model(model, *args, **kwargs):
    kwargs['parent'] = _NDB_ANCESTOR
    return model(*args, **kwargs)


@ndb.transactional
def get_reddit():
    dt_format = '%Y-%m-%d %H:%I:%S'
    now = datetime.utcnow()
    
    def refresh_access_info():
        refresh_token = config.OAUTH_REFRESH_TOKEN
        new_access_info = r.refresh_access_information(refresh_token)
        KVStore_set('access_info', str(new_access_info))
        KVStore_set('access_info_last_refresh', now.strftime(dt_format))
    
    r = praw.Reddit(config.USER_AGENT, site_name='dev')
    
    access_info_last_refresh_str = KVStore_get('access_info_last_refresh')
    if access_info_last_refresh_str:
        access_info_last_refresh = datetime.strptime(
            access_info_last_refresh_str, dt_format)
        if now - access_info_last_refresh <= timedelta(hours=1):
            access_info_str = KVStore_get('access_info')
            access_info = eval(access_info_str)
            r.set_access_credentials(**access_info)
        else:
            refresh_access_info()
    else:
        refresh_access_info()
    
    return r


def render_template(filename, **vars):
    def pluralize(count_or_seq, singular, plural):
        try:
            count = len(count_or_seq)
        except TypeError:
            count = count_or_seq
        return singular if count == 1 else plural
    
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    jinja_env = Environment(loader=FileSystemLoader(templates_dir),
                            trim_blocks=True, lstrip_blocks=True,
                            keep_trailing_newline=True)
    jinja_env.globals['pluralize'] = pluralize
    jinja_env.globals['config'] = config
    
    template = jinja_env.get_template(filename)
    return template.render(**vars)


_RE_FULLNAME_PREFIX = re.compile(r'^t[1-5]_')


def fullname_to_id(fullname):
    return _RE_FULLNAME_PREFIX.sub('', fullname)


def get_comment_url(comment, context=None):
    submission_id = fullname_to_id(comment.link_id)
    
    url_tpl = 'https://www.reddit.com/r/{}/comments/{}/_/{}'
    url = url_tpl.format(config.SUBREDDIT, submission_id, comment.id)
    
    if context:
        url += '?context={}'.format(context)
    
    return url
