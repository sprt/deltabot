from datetime import datetime, timedelta
import os
from threading import Lock
import unittest

from google.appengine.datastore import datastore_stub_util
from google.appengine.ext import deferred, ndb, testbed
from mock import call, patch, MagicMock, Mock

from application.deltabot import config, utils
from application.deltabot import bot
from application.deltabot.models import Delta

config.BOT_USERNAME = 'bot'
config.DELTA = '+'
config.DELTA_ALIASES = ('!plus',)
config.SUBREDDIT = 'testsub'


reddit_test = patch('application.deltabot.utils.praw.Reddit')


def init_datastore_stub(function):
    policy = datastore_stub_util.PseudoRandomHRConsistencyPolicy(probability=0)
    function.testbed.init_datastore_v3_stub(consistency_policy=policy)
    function.testbed.init_memcache_stub()
    ndb.get_context().set_cache_policy(False)


# See <https://github.com/testing-cabal/mock/issues/139#issuecomment-94939404>
class PickableMock(Mock):
    def __reduce__(self):
        return (Mock, ())


class TaskQueueTestMixin(object):
    nosegae_taskqueue = True
    nosegae_taskqueue_kwargs = {
        'root_path': os.path.join(os.path.dirname(__file__), '../..'),
    }
    
    def get_tasks(self):
        return self.testbed.get_stub('taskqueue').get_filtered_tasks()


class DatastoreTestMixin(object):
    nosegae_datastore_v3 = True
    nosegae_datastore_v3_kwargs = {
        'consistency_policy':
            datastore_stub_util.PseudoRandomHRConsistencyPolicy(probability=0),
    }
    
    def setUp(self):
        ndb.get_context().set_cache_policy(False)


class TestQueryUserDeltas(unittest.TestCase, DatastoreTestMixin):
    def setUp(self):
        self.delta = utils.ndb_model(Delta,
            awarded_at=datetime.now(),
            awarded_by='foo',
            awarded_to='john',
            awarder_comment_id='foo',
            awarder_comment_url='foo',
            submission_id='foo',
            submission_title='foo',
            submission_url='foo')
    
    def test_delta_not_removed(self):
        self.delta.status = None
        self.delta.put()
        assert bot._query_user_deltas('john').count() == 1
    
    def test_delta_removed(self):
        self.delta.status = 'removed_abuse'
        self.delta.put()
        assert bot._query_user_deltas('john').count() == 0


@reddit_test
class TestUpdateUserFlair(unittest.TestCase, DatastoreTestMixin):
    def test_delta_count_non_null(self, reddit_class):
        delta = utils.ndb_model(Delta,
            awarded_at=datetime.now(),
            awarded_by='foo',
            awarded_to='john',
            awarder_comment_id='foo',
            awarder_comment_url='foo',
            submission_id='foo',
            submission_title='foo',
            submission_url='foo')
        delta.put()
        
        bot.update_user_flair('john')
        assert reddit_class.return_value.set_flair.called
    
    def test_delta_count_null(self, reddit_class):
        bot.update_user_flair('john')
        assert reddit_class.return_value.delete_flair.called


@reddit_test
class TestUpdateSubmissionFlair(unittest.TestCase, DatastoreTestMixin):
    def setUp(self):
        self.comment = Mock()
        self.comment.author.name = 'john'
    
    def test_delta_from_op(self, reddit_class):
        self.comment.link_author = 'john'
        bot.update_submission_flair(self.comment)
        assert reddit_class.return_value.set_flair.called
    
    def test_delta_not_from_op(self, reddit_class):
        self.comment.link_author = 'jane'
        bot.update_submission_flair(self.comment)
        assert not reddit_class.return_value.set_flair.called


class TestGetUserDeltas(unittest.TestCase, DatastoreTestMixin):
    def test_is_sorted(self):
        delta1 = utils.ndb_model(Delta,
            awarded_at=datetime(1970, 1, 1),
            awarded_by='foo',
            awarded_to='john',
            awarder_comment_id='foo',
            awarder_comment_url='foo',
            submission_id='foo',
            submission_title='foo',
            submission_url='foo')
        delta1.put()
        
        delta2 = utils.ndb_model(Delta,
            awarded_at=datetime(1970, 1, 2),
            awarded_by='foo',
            awarded_to='john',
            awarder_comment_id='foo',
            awarder_comment_url='foo',
            submission_id='foo',
            submission_title='foo',
            submission_url='foo')
        delta2.put()
        
        assert bot._get_user_deltas('john') == [delta2, delta1]


@reddit_test
class TestUpdateUserWikiPage(unittest.TestCase, DatastoreTestMixin):
    def test_edit_wiki_page_called(self, reddit_class):
        bot.update_user_wiki_page('john')
        assert reddit_class.return_value.edit_wiki_page.called


# XXX: can do better
class TestGetDeltasGroupedByUsers(unittest.TestCase, DatastoreTestMixin):
    def test_is_grouped(self):
        def make_delta(**kwargs):
            defaults = {
                'awarded_by': 'mary',
                'awarder_comment_id': 'foo',
                'awarder_comment_url': 'http://awardercomment/',
                'submission_id': 'sbmsn',
                'submission_title': 'Blah',
                'submission_url': 'http://linkurl/',
            }
            delta = utils.ndb_model(Delta)
            delta.populate(**defaults)
            delta.populate(**kwargs)
            return delta
        
        now = datetime.now()
        delta1 = make_delta(awarded_at=now, awarded_to='jo')
        delta2 = make_delta(awarded_at=now + timedelta(seconds=1), awarded_to='jo')
        delta3 = make_delta(awarded_at=now, awarded_to='sally')
        ndb.put_multi([delta1, delta2, delta3])
        
        assert bot._get_deltas_grouped_by_users() == [delta2, delta3]


@reddit_test
class TestUpdateTrackerWikiPage(unittest.TestCase, DatastoreTestMixin):
    def test_edit_wiki_page_called(self, reddit_class):
        bot.update_tracker_wiki_page()
        assert reddit_class.return_value.edit_wiki_page.called


@reddit_test
class TestCommentProcessor(unittest.TestCase, DatastoreTestMixin,
                           TaskQueueTestMixin):
    def setUp(self):
        self.awarder_comment = PickableMock(link_id='foo')
        self.message = Mock()
        self.processor = bot.DeltaAdder(self.awarder_comment, self.message)
    
    def test_reply_to_comment(self, reddit_class):
        bot.CommentProcessor._reply_to_comment(self.processor, None)
        assert self.awarder_comment.reply.called
        assert len(self.get_tasks()) == 1
    
    def test_reply_to_message(self, reddit_class):
        bot.CommentProcessor._reply_to_message(self.processor, None)
        assert self.message.reply.called
    
    def test_update_reddit(self, reddit_class):
        self.processor._awardee_comment = PickableMock()
        bot.CommentProcessor._update_reddit(self.processor)
        assert len(self.get_tasks()) == 3


@reddit_test
class TestDeltaAdder(unittest.TestCase, DatastoreTestMixin,
                     TaskQueueTestMixin):
    def setUp(self):
        self.awarder_comment = PickableMock(author=Mock(),
                                            created_utc=0.0,
                                            id='foo',
                                            link_id='foo',
                                            link_title='foo',
                                            link_url='foo')
        self.awarder_comment.author.configure_mock(name='foo')
        self.message = Mock()
        
        self.processor = bot.DeltaAdder(self.awarder_comment, self.message)
        
        self.processor._awardee_comment = PickableMock(author=Mock(), id='foo')
        self.processor._awardee_comment.author.configure_mock(name='foo')
    
    def test_update_records(self, reddit_class):
        self.processor._update_records()
        assert utils.ndb_query(Delta).get()


class TestHasDeltaToken(unittest.TestCase):
    """Test the DeltaAdder._has_delta_token() method"""
    
    def check(self, text):
        comment = Mock(body=text, link_id='')
        return bot.DeltaAdder(comment)._has_delta_token()
    
    def test_ok(self):
        assert self.check('+')
        assert self.check('!plus')
        
        assert self.check('foo+')
        assert self.check('+foo')
        assert self.check('foo+foo')
        assert self.check('\nfoo+foo')
        assert self.check('\nfoo+foo\n')
        assert self.check('foo\nfoo+foo')
    
    def test_inline_code(self):
        assert not self.check('`+`')
        assert not self.check('`foo+`')
        
        assert self.check('+`foo`')
        assert self.check('`foo`+')
    
    def test_block_quotes(self):
        assert not self.check('>+')
        assert not self.check(' > +')
        
        assert not self.check('foo\n>+')  # previous line not empty
        assert not self.check('>foo\n+')  # multiline quote
        
        assert self.check('>foo\n\n+')  # delta out of quote
    
    def test_code_blocks(self):
        assert not self.check('\x20\x20\x20\x20+')
        assert not self.check('\t+')
        
        assert not self.check('\n\t+')  # previous line empty
        assert self.check('foo\n\t+')  # previous line not empty
        
        assert not self.check('\t+\n')  # next line empty
        assert not self.check('\t+\nfoo')  # next line not empty
        
        assert self.check('\tfoo\n+')  # delta out of code


class ItemsConsumerMock(bot.ItemsConsumer):
    _lock = MagicMock()
    
    PROCESSOR = PickableMock()
    PLACEHOLDER_KEY = 'foos_placeholder'
    PROCESSED_KEY = 'foos_processed:{}'


class TestItemsConsumer(unittest.TestCase, DatastoreTestMixin,
                        TaskQueueTestMixin):
    def setUp(self):
        super(TestItemsConsumer, self).setUp()
        self.consumer = ItemsConsumerMock()
    
    def test_iter_items(self):
        items_list = [Mock(id='a', created_utc=0), Mock(id='b', created_utc=1)]
        self.consumer._fetch_items = Mock(return_value=reversed(items_list))
        returned_items_list = list(self.consumer._iter_items())
        assert returned_items_list == items_list
    
    def test_process_item_updates_placeholder(self):
        self.consumer._process_item(Mock(id='a'))
        assert utils.KVStore_get('foos_placeholder') == 'a'
    
    def test_process_item_updates_processed(self):
        self.consumer._process_item(Mock(id='a'))
        assert utils.KVStore_exists('foos_processed:a')
    
    def test_process_item_not_already_processed(self):
        self.consumer._process_item(Mock(id='a'))
        taskqueue_stub = self.testbed.get_stub('taskqueue')
        assert self.consumer.PROCESSOR.return_value.run.called
    
    def test_process_item_already_processed(self):
        utils.KVStore_set('foos_processed:a')
        self.consumer._process_item(Mock(id='a'))
        assert len(self.get_tasks()) == 0
    
    def test_run_sets_placeholder(self):
        utils.KVStore_set('foos_placeholder', 'a')
        self.consumer._fetch_items = Mock(return_value=iter([]))
        self.consumer.run()
        assert self.consumer._placeholder == 'a'
    
    def test_run_processes_items(self):
        self.consumer._fetch_items = Mock(return_value=iter([Mock()]))
        self.consumer._process_item = Mock()
        self.consumer.run()
        assert self.consumer._process_item.call_count == 1


@patch('application.deltabot.utils.praw.Reddit')
class TestCommentsConsumer(unittest.TestCase, DatastoreTestMixin,
                           TaskQueueTestMixin):
    def setUp(self):
        self.consumer = bot.CommentsConsumer()
    
    def test_fetch_items(self, reddit_class):
        self.consumer._placeholder = 'a'
        returned_items = self.consumer._fetch_items()
        assert returned_items == reddit_class.return_value.get_comments(
            'testsub', limit=None, placeholder='a')


@patch('application.deltabot.utils.praw.Reddit')
class TestMessagesConsumer(unittest.TestCase, DatastoreTestMixin,
                           TaskQueueTestMixin):
    def setUp(self):
        self.consumer = bot.MessagesConsumer()
    
    def test_fetch_items_strips_replies(self, reddit_class):
        item = Mock(replies=[])
        
        reddit_class.return_value.get_messages.return_value = iter([item])
        
        self.consumer._placeholder = None
        returned_items = self.consumer._fetch_items()
        
        assert not hasattr(next(returned_items), 'replies')
