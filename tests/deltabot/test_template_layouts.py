from datetime import datetime
import os
import unittest

from mock import Mock

from application.deltabot import config
from application.deltabot.utils import render_template

config.SUBREDDIT = 'testsub'


def get_template_double(path):
    data_dir = os.path.join(os.path.dirname(__file__), '../data/templates')
    return open(os.path.join(data_dir, path)).read()


def test_wiki_user_layout():
    """Test the wiki/user_history.md template"""
    delta = Mock(awarded_at=datetime(1970, 1, 1),
                 awarded_by='mary',
                 awarder_comment_url='http://example.com/',
                 submission_title='foo')
    rendered = render_template('wiki/user_history.md', username='john',
                               deltas=[delta] * 2)
    assert rendered == get_template_double('user_wiki.md')


def test_wiki_tracker_layout():
    """Test the wiki/tracker.md template"""
    delta = Mock(awarded_at=datetime(1970, 1, 1),
                 awarded_to='john',
                 awarder_comment_url='http://example.com/')
    rendered = render_template('wiki/tracker.md', deltas=[delta] * 2)
    assert rendered == get_template_double('wiki_tracker.md')


class TemplateTest(unittest.TestCase):
    TEMPLATE_FILENAME = None
    
    def render_template(self, **kwargs):
        return render_template(self.TEMPLATE_FILENAME, **kwargs)


class TestDeltaAdderCommentTemplate(TemplateTest):
    TEMPLATE_FILENAME = 'comments/delta_adder.md'
    
    def test_no_error(self):
        rendered = self.render_template(error=None, awardee_username='John')
        expected = get_template_double('comments/delta_adder_no_error.md')
        assert rendered == expected
    
    def test_error(self):
        rendered = self.render_template(error='already_awarded',
                                        awardee_username='John')
        expected = get_template_double('comments/delta_adder_error.md')
        assert rendered == expected


class TestDeltaRemoverCommentTemplate(TemplateTest):
    TEMPLATE_FILENAME = 'comments/delta_remover.md'
    
    def test_remind(self):
        rendered = self.render_template(error=None, awardee_username='John',
                                        removal_reason='remind')
        expected = get_template_double('comments/delta_remover_remind.md')
        assert rendered == expected
    
    def test_not_remind(self):
        rendered = self.render_template(error=None, awardee_username='John',
                                        removal_reason='abuse')
        expected = get_template_double('comments/delta_remover_not_remind.md')
        assert rendered == expected
