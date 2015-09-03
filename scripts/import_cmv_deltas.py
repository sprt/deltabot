#!/usr/bin/env python2.7

"""Quick and dirty script to import deltas from the /r/changemyview wiki"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SDK_PATH = '/usr/local/google_appengine'

if os.path.exists(os.path.join(SDK_PATH, 'platform/google_appengine')):
    sys.path.insert(0, os.path.join(SDK_PATH, 'platform/google_appengine'))
else:
    sys.path.insert(0, SDK_PATH)

import dev_appserver
dev_appserver.fix_sys_path()

import appengine_config  # noqa

import getpass
from google.appengine.ext.remote_api import remote_api_stub


def auth_func():
    return (raw_input('Email: '), getpass.getpass('Password: '))


remote_api_stub.ConfigureRemoteApi(None, '/_ah/remote_api', auth_func,
                                   'localhost:8080', save_cookies=True)

from collections import namedtuple
from datetime import datetime
import re
import warnings

from praw.errors import OAuthInvalidToken
from praw.objects import Submission
from requests.exceptions import HTTPError

from application.deltabot.models import Delta
from application.deltabot.utils import get_reddit, ndb_model


def warning_on_one_line(message, category, filename, lineno, file=None,
                        line=None):
    return ('{filename}:{lineno}: {category.__name__}: {message}\n'
            .format(**locals()))


warnings.formatwarning = warning_on_one_line

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

r = get_reddit()
r.refresh_access_information()

ParsedDelta = namedtuple('ParsedDelta', [
    'awarded_at',
    'awarded_by',
    'awarder_comment_id',
    'awarder_comment_url',
    'submission_id',
    'submission_title',
    'submission_url',
])


def parse_date(date_str):
    return datetime.strptime(date_str, '%m/%d/%Y')


def to_https(url):
    if url.startswith('http://'):
        return 'https://' + url[8:]
    elif not url.startswith('https://'):
        warnings.warn('not an https url: {}'.format(url))


def to_ndb_delta(parsed_delta, awardee_username):
    return ndb_model(
        Delta,
        awarded_at=parsed_delta.awarded_at,
        awarded_by=parsed_delta.awarded_by,
        awarded_to=awardee_username,
        awarder_comment_id=parsed_delta.awarder_comment_id,
        awarder_comment_url=to_https(parsed_delta.awarder_comment_url),
        submission_id=parsed_delta.submission_id,
        submission_title=parsed_delta.submission_title,
        submission_url=to_https(parsed_delta.submission_url))


def parse_list_file(filename):
    filename = os.path.join(os.path.dirname(__file__), filename)
    values = []
    for line in open(filename):
        try:
            value, _ = line.split('#', 1)
        except ValueError:  # no comment
            value = line
        value = value.strip()
        if value:
            values.append(value)
    return values


RE_USER_PAGE_V3 = re.compile(
    r"""(?x)
        ^\|(?P<awarded_at>\d+/\d+/\d+)\|
        \[(?P<submission_title>.+?)\]
        \((?P<submission_url>http://www\.reddit\.com/r/changemyview/comments/
            (?P<submission_id>\w+)/.+/)\)\|
        \[Link\]\((?P<comment_url>http://www\.reddit\.com/r/changemyview/
            comments/\w+/.+/(?P<comment_id>\w+))\?context=2\)\|
        /u/(?P<awarded_by>\w+)\|$""")


def parse_user_page_v3(page_content, username):
    parsed_deltas = []
    past_header = False
    pos = 0
    
    for line in page_content.split('\n'):
        pos += len(line) + 1
        
        if line == '| --- | :-: | --- | --- |':
            past_header = True
            continue
        
        m = RE_USER_PAGE_V3.search(line)
        if not m:
            if past_header:
                parsed_deltas.extend(parse_user_page_v2(page_content[pos:],
                                                        username))
                break
            continue
        
        parsed_deltas.append(ParsedDelta(
            awarded_at=parse_date(m.group('awarded_at')),
            awarded_by=m.group('awarded_by'),
            awarder_comment_id=m.group('comment_id'),
            awarder_comment_url=m.group('comment_url'),
            submission_id=m.group('submission_id'),
            submission_title=m.group('submission_title'),
            submission_url=m.group('submission_url')))
    
    if not parsed_deltas:
        parsed_deltas.extend(parse_user_page_v2(page_content, username))
    
    return parsed_deltas


def search_deltas_thread(submission_url, awardee_username):
    parsed_deltas = []
    
    submission = Submission.from_url(r, submission_url, comment_limit=None)
    submission.replace_more_comments(limit=None, threshold=1)
    
    keyphrase = 'delta awarded to /u/{}'.format(awardee_username).lower()
    
    def search_comment(comment, parent):
        if (getattr(comment.author, 'name', None) == 'DeltaBot' and
                keyphrase in comment.body.lower()):
            awarded_at = datetime.fromtimestamp(parent.created_utc)
            awarded_by = getattr(parent.author, 'name', '[deleted]')
            parsed_deltas.append(ParsedDelta(
                awarded_at=awarded_at,
                awarded_by=awarded_by,
                awarder_comment_id=parent.id,
                awarder_comment_url=submission.url + parent.id,
                submission_id=submission.id,
                submission_title=submission.title,
                submission_url=submission.url))
        for reply in comment.replies:
            search_comment(reply, comment)
    
    for comment in submission.comments:
        for reply in comment.replies:
            search_comment(reply, comment)
    
    return parsed_deltas


RE_USER_PAGE_V2_SUBMISSION = re.compile(
    r"""(?mx)
        ^\*\s\[(?P<submission_title>.+)\]
            \((?P<submission_url>http://www\.reddit\.com/r/changemyview/
                comments/(?P<submission_id>\w+)/.+/)\)\s
        \((?P<delta_count>\d)\)""")

RE_USER_PAGE_V2_COMMENT = re.compile(
    r"""(?mx)
        ^\s+1\.\s\[Awarded\sby\s/u/(?P<awarded_by>\w+)\]
            \((?P<comment_url>http://www\.reddit\.com/r/changemyview/comments/
                \w+/.+/(?P<comment_id>\w+))\?context=2\)\s
        on\s(?P<awarded_at>\d+/\d+/\d+)$""")


def parse_user_page_v2(page_content, username):
    parsed_deltas = []
    
    submission_matches = RE_USER_PAGE_V2_SUBMISSION.finditer(page_content)
    submission_matches = list(submission_matches)
    
    if not submission_matches:
        if not page_content or '/r/PixelOrange' in page_content:
            return []
        parsed_deltas.extend(parse_user_page_v1(page_content, username))
    
    for i, submission_m in enumerate(submission_matches):
        submission_id = submission_m.group('submission_id')
        submission_title = submission_m.group('submission_title')
        submission_url = submission_m.group('submission_url')
        
        substring_start = submission_m.end() + 1
        if submission_m == submission_matches[-1]:
            substring = page_content[substring_start:]
        else:
            substring_end = submission_matches[i + 1].start() - 1
            substring = page_content[substring_start:substring_end]
        
        comment_matches = list(RE_USER_PAGE_V2_COMMENT.finditer(substring))
        
        if not comment_matches:
            found_deltas = search_deltas_thread(submission_url, username)
            parsed_deltas.extend(found_deltas)
            
            delta_count = int(submission_m.group('delta_count'))
            if len(found_deltas) != delta_count:
                warnings.warn('delta count is {}, found {}'
                              .format(delta_count, len(found_deltas)))
        
        for comment_m in comment_matches:
            parsed_deltas.append(ParsedDelta(
                awarded_at=parse_date(comment_m.group('awarded_at')),
                awarded_by=comment_m.group('awarded_by'),
                awarder_comment_id=comment_m.group('comment_id'),
                awarder_comment_url=comment_m.group('comment_url'),
                submission_id=submission_id,
                submission_title=submission_title,
                submission_url=submission_url))
    
    if not parsed_deltas:
        warnings.warn('v2: no deltas')
    
    return parsed_deltas


RE_USER_PAGE_V1 = re.compile(
    r"""(?mx)
        ^\*\x20\[(?P<submission_title>.+)\]
            \((?P<submission_url>http://www\.reddit.com/r/changemyview/
                comments/(?P<submission_id>\w+)/.+/)""")


def parse_user_page_v1(page_content, username):
    parsed_deltas = []
    matches = list(RE_USER_PAGE_V1.finditer(page_content))
    
    for m in matches:
        submission_url = m.group('submission_url')
        parsed_deltas.extend(search_deltas_thread(submission_url, username))
    
    return parsed_deltas


def process_user(username):
    parsed_deltas = []
    
    print 'Processing for /u/{}...'.format(username),
    
    page_v3 = r.get_wiki_page('changemyview', 'user/{}'.format(username))
    parsed_deltas.extend(parse_user_page_v3(page_v3.content_md, username))
    
    link_old = '/r/ChangeMyView/wiki/userhistory/user/{}'.format(username)
    if link_old in page_v3.content_md:
        page_v2_name = 'userhistory/user/{}'.format(username)
        page_v2 = r.get_wiki_page('changemyview', page_v2_name)
        parsed_deltas.extend(parse_user_page_v2(page_v2.content_md, username))
    
    for parsed_delta in parsed_deltas:
        delta = to_ndb_delta(parsed_delta, username)
        delta.put()
    
    print 'done ({} deltas)'.format(len(parsed_deltas))
    
    if len(parsed_deltas) == 0:
        warnings.warn('no deltas')


def main():
    print datetime.utcnow().isoformat()
    
    usernames = []
    
    for user_page in r.get_wiki_pages('changemyview'):
        name = user_page.page
        if name.startswith('user/'):
            usernames.append(name[5:])
    
    print '{} user pages'.format(len(usernames))
    
    START = 0
    progress = 1
    
    for i, username in enumerate(usernames[START:]):
        i += START
        print '{}/{}...'.format(i, len(usernames) - 1)
        try:
            process_user(username)
        except HTTPError:
            usernames.insert(i + 1, username)
        except OAuthInvalidToken:
            r.refresh_access_information()
            usernames.insert(i + 1, username)
        else:
            progress += 1
    
    print datetime.utcnow().isoformat()


main()
