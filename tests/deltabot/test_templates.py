from datetime import datetime
import os

from mock import Mock

from application.deltabot import config
from application.deltabot.utils import render_template

config.SUBREDDIT = 'test'


def _get_template_double(path):
    data_dir = os.path.join(os.path.dirname(__file__), '../data/templates')
    return open(os.path.join(data_dir, path)).read()


def test_wiki_user_layout():
    """Test the wiki/user_history.md template"""
    delta = Mock(awarded_at=datetime(1970, 1, 1),
                 awarded_by='mary',
                 awarder_comment_url='http://example.com/',
                 submission_title='foo')
    rendered_template = render_template('wiki/user_history.md',
                                        username='john',
                                        deltas=[delta] * 2)
    assert rendered_template == _get_template_double('user_wiki.md')


def test_wiki_tracker_layout():
    """Test the wiki/tracker.md template"""
    delta = Mock(awarded_at=datetime(1970, 1, 1),
                 awarded_to='john',
                 awarder_comment_url='http://example.com/')
    rendered_template = render_template('wiki/tracker.md', deltas=[delta] * 2)
    assert rendered_template == _get_template_double('wiki_tracker.md')


def test_comment_valid_delta_layout():
    """Test the comments/delta.md with a valid delta"""
    rendered_template = render_template('comments/delta_adder.md',
                                        error=None,
                                        awardee_username='john')
    assert rendered_template == _get_template_double('valid_delta.md')


def test_comment_invalid_delta_layout():
    """Test the comments/delta.md with an invalid delta"""
    rendered_template = render_template(
        'comments/delta_adder.md',
        awardee_username='john',
        error='already_awarded')
    assert rendered_template == _get_template_double('invalid_delta.md')
