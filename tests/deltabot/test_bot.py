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


def _get_delta(**kwargs):
    defaults = {
        'awarded_at': datetime(1970, 1, 1),
        'awarded_by': 'Jane',
        'awarded_to': 'John',
        'awarder_comment_id': '000002',
        'awarder_comment_url': 'http://example.com/comment',
        'submission_id': '00000a',
        'submission_title': 'Foo',
        'submission_url': 'http://example.com/submission',
    }
    defaults.update(**kwargs)
    return utils.ndb_model(Delta, **defaults)


def _get_comment(**kwargs):
    defaults = {
        'author.name': 'John',
        'body': '+ Genius!',
        'created_utc': 0.0,
        'id': '00000b',
        'link_id': '00000a',
        'link_title': 'Foo',
        'link_url': 'http://example.com/submission',
    }
    defaults.update(**kwargs)
    comment = Mock()
    comment.configure_mock(**defaults)
    return comment


def _get_message(**kwargs):
    defaults = {
        'author.name': 'John',
        'body': 'http://example.com/comment',
        'dest': config.BOT_USERNAME,
        'subject': 'force add',
        'subreddit': None,
    }
    defaults.update(**kwargs)
    message = Mock()
    message.configure_mock(**defaults)
    return message


reddit_test = patch('application.deltabot.utils.praw.Reddit')
defer_reddit_test = patch('application.deltabot.utils.defer_reddit',
                          side_effect=utils.defer_reddit)


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
        self.delta = _get_delta(awarded_to='john')
    
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
    def setUp(self):
        self.delta = _get_delta(awarded_to='john')
        self.delta.put()
    
    def test_delta_count_non_null(self, reddit_class):
        bot.update_user_flair('john')
        assert reddit_class.return_value.set_flair.called
    
    def test_delta_count_null(self, reddit_class):
        bot.update_user_flair('jane')
        assert reddit_class.return_value.delete_flair.called


@reddit_test
class TestUpdateSubmissionFlair(unittest.TestCase, DatastoreTestMixin):
    def setUp(self):
        self.comment = _get_comment()
        self.comment.submission = Mock(id='x')
        
        self.delta = _get_delta(awarded_by='John', submission_id='x')
        self.delta.put()
    
    def test_has_op_delta(self, reddit_class):
        self.comment.submission.author.name = 'John'
        
        bot.update_submission_flair(self.comment)
        
        set_flair = reddit_class.return_value.set_flair
        set_flair.assert_called_with(config.SUBREDDIT, self.comment.submission,
                                     '[Deltas Awarded]', 'OPdelta')
    
    def test_has_no_op_delta(self, reddit_class):
        self.comment.submission.author.name = 'Jane'
        
        bot.update_submission_flair(self.comment)
        
        set_flair = reddit_class.return_value.set_flair
        set_flair.assert_called_with(config.SUBREDDIT, self.comment.submission,
                                     None, None)


class TestGetUserDeltas(unittest.TestCase, DatastoreTestMixin):
    def setUp(self):
        self.delta1 = _get_delta(awarded_at=datetime(1970, 1, 1),
                                 awarded_to='john')
        self.delta2 = _get_delta(awarded_at=datetime(1970, 1, 2),
                                 awarded_to='john')
        ndb.put_multi([self.delta1, self.delta2])
    
    def test_is_sorted(self):
        assert bot._get_user_deltas('john') == [self.delta2, self.delta1]


@reddit_test
class TestUpdateUserWikiPage(unittest.TestCase, DatastoreTestMixin):
    def test_edit_wiki_page_called(self, reddit_class):
        bot.update_user_wiki_page('john')
        assert reddit_class.return_value.edit_wiki_page.called


class TestGetDeltasGroupedByUsers(unittest.TestCase, DatastoreTestMixin):
    def setUp(self):
        self.delta1 = _get_delta(awarded_at=datetime(1970, 1, 1),
                                 awarded_to='john')
        self.delta2 = _get_delta(awarded_at=datetime(1970, 1, 2),
                                 awarded_to='john')
        self.delta3 = _get_delta(awarded_at=datetime(1970, 1, 1),
                                 awarded_to='mary')
        ndb.put_multi([self.delta1, self.delta2, self.delta3])
    
    def test_is_grouped(self):
        assert bot._get_deltas_grouped_by_users() == [self.delta2, self.delta3]


@reddit_test
class TestUpdateTrackerWikiPage(unittest.TestCase, DatastoreTestMixin):
    def test_edit_wiki_page_called(self, reddit_class):
        bot.update_tracker_wiki_page()
        assert reddit_class.return_value.edit_wiki_page.called


@defer_reddit_test
@reddit_test
class TestCommentProcessor(unittest.TestCase, DatastoreTestMixin,
                           TaskQueueTestMixin):
    def setUp(self):
        self.awarder_comment = PickableMock(link_id='foo')
        self.message = Mock()
        self.processor = bot.DeltaAdder(self.awarder_comment, self.message)
    
    def test_reply_to_comment(self, reddit_class, defer_func):
        bot.CommentProcessor._reply_to_comment(self.processor, None)
        assert self.awarder_comment.reply.called
        assert len(self.get_tasks()) == 1
    
    def test_reply_to_comment_defer_fails(self, reddit_class, defer_func):
        defer_func.side_effect = Exception
        try:
            bot.CommentProcessor._reply_to_comment(self.processor, None)
        except:
            self.fail()
    
    def test_reply_to_message(self, reddit_class, defer_func):
        bot.CommentProcessor._reply_to_message(self.processor, None)
        assert self.message.reply.called
    
    def test_update_reddit(self, reddit_class, defer_func):
        self.processor._awardee_comment = PickableMock()
        self.processor._awardee_comment.author.name = 'john'
        
        bot.CommentProcessor._update_reddit(self.processor)
        
        defer_func.assert_any_call(bot.update_submission_flair,
                                   self.awarder_comment)
        defer_func.assert_any_call(bot.update_user_flair, 'john')
        defer_func.assert_any_call(bot.update_user_wiki_page, 'john')


@reddit_test
class TestDeltaAdder(unittest.TestCase, DatastoreTestMixin,
                     TaskQueueTestMixin):
    def setUp(self):
        self.awarder_comment = _get_comment(body='+ Genius!',
                                            created_utc=0.0,
                                            id='y',
                                            is_root=False,
                                            link_author='Adam',
                                            link_id='x',
                                            link_title='Foo',
                                            link_url='http://example.com/')
        self.awarder_comment.author.name = 'John'
        
        self.processor = bot.DeltaAdder(self.awarder_comment)
        
        self.processor._awardee_comment = _get_comment(id='x')
        self.processor._awardee_comment.author.name = 'Jane'
    
    def test_check_queuable_no_error(self, reddit_class):
        assert self.processor._check_queuable() is None
    
    def test_check_queuable_no_author(self, reddit_class):
        self.processor._awarder_comment.author = None
        assert self.processor._check_queuable() == 'no_author'
    
    def test_check_queuable_no_token(self, reddit_class):
        self.processor._awarder_comment.body = 'Genius!'
        assert self.processor._check_queuable() == 'no_token'
    
    def test_check_queuable_no_token_force(self, reddit_class):
        self.processor._force = True
        self.processor._awarder_comment.body = 'Genius!'
        assert self.processor._check_queuable() is None
    
    def test_check_processable_no_error(self, reddit_class):
        assert self.processor._check_processable() is None
    
    def test_check_processable_already_awarded(self, reddit_class):
        delta = _get_delta(awarded_by='John',
                           awarded_to='Jane',
                           submission_id='x')
        delta.put()
        
        assert self.processor._check_processable() == 'already_awarded'
    
    def test_check_processable_toplevel_comment(self, reddit_class):
        self.processor._awarder_comment.is_root = True
        assert self.processor._check_processable() == 'toplevel_comment'
    
    def test_check_processable_awardee_is_awarder(self, reddit_class):
        self.processor._awardee_comment.author.name = 'John'
        assert self.processor._check_processable() == 'awardee_is_awarder'
    
    def test_check_processable_awardee_is_deltabot(self, reddit_class):
        self.processor._awardee_comment.author.name = 'bot'
        assert self.processor._check_processable() == 'awardee_is_deltabot'
    
    def test_check_processable_awardee_is_op(self, reddit_class):
        self.processor._awardee_comment.author.name = 'Adam'
        assert self.processor._check_processable() == 'awardee_is_op'
    
    def test_check_processable_no_explanation(self, reddit_class):
        self.processor._awarder_comment.body = '+'
        assert self.processor._check_processable() == 'no_explanation'
    
    def test_check_processable_no_explanation_force(self, reddit_class):
        self.processor._force = True
        self.processor._awarder_comment.body = '+'
        assert self.processor._check_processable() is None
    
    def test_update_records(self, reddit_class):
        self.processor._update_records()
        
        delta = utils.ndb_query(Delta).get()
        
        assert delta.awarded_at == datetime(1970, 1, 1)
        assert delta.awarded_by == 'John'
        assert delta.awarded_to == 'Jane'
        assert delta.awarder_comment_id == 'y'
        assert delta.awarder_comment_url == ('https://www.reddit.com/r/'
                                             'testsub/comments/x/_/y')
        assert delta.submission_id == 'x'
        assert delta.submission_title == 'Foo'


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


@reddit_test
class TestDeltaApprover(unittest.TestCase, DatastoreTestMixin,
                        TaskQueueTestMixin):
    def setUp(self):
        awarder_comment = _get_comment(id='a')
        self.processor = bot.DeltaApprover(awarder_comment)
        self.processor._awardee_comment = _get_comment()
        
        self.delta = _get_delta(awarder_comment_id='a')
        self.delta.put()
        
    def test_check_queuable(self, reddit_class):
        assert self.processor._check_queuable() is None
    
    def test_check_processable_no_error(self, reddit_class):
        assert self.processor._check_processable() is None
    
    def test_check_processable_no_record(self, reddit_class):
        self.delta.key.delete()
        assert self.processor._check_processable() == 'no_record'
    
    def test_check_processable_is_removed(self, reddit_class):
        self.delta.status = 'removed_abuse'
        assert self.processor._check_processable() == 'is_removed'
    
    def test_check_processable_already_approved(self, reddit_class):
        self.delta.status = 'approved'
        assert self.processor._check_processable() == 'already_approved'
    
    def test_update_records(self, reddit_class):
        self.processor._update_records()
        assert self.delta.status == 'approved'


@reddit_test
class TestDeltaRemover(unittest.TestCase, DatastoreTestMixin,
                       TaskQueueTestMixin):
    def setUp(self):
        awarder_comment = _get_comment(id='a')
        self.processor = bot.DeltaRemover(awarder_comment, Mock(), 'abuse')
        self.processor._awardee_comment = _get_comment()
        
        self.delta = _get_delta(awarder_comment_id='a')
        self.delta.put()
    
    def test_check_queuable(self, reddit_class):
        assert self.processor._check_queuable() is None
    
    def test_check_processable_no_error(self, reddit_class):
        assert self.processor._check_processable() is None
    
    def test_check_processable_no_record(self, reddit_class):
        self.delta.key.delete()
        assert self.processor._check_processable() == 'no_record'
    
    def test_check_processable_already_removed(self, reddit_class):
        self.delta.status = 'removed_abuse'
        assert self.processor._check_processable() == 'already_removed'
    
    def test_check_processable_is_approved(self, reddit_class):
        self.delta.status = 'approved'
        assert self.processor._check_processable() == 'is_approved'
    
    # TODO: test different reasons
    def test_update_records(self, reddit_class):
        self.processor._update_records()
        assert self.delta.status == 'removed_abuse'    


@reddit_test
class TestCommandMessageProcessor(unittest.TestCase):
    def setUp(self):
        self.message = _get_message()
        self.processor = bot.CommandMessageProcessor(self.message)
    
    def test_check_queuable_no_error(self, reddit_class):
        assert self.processor._check_queuable() is None
    
    def test_check_queuable_modmail(self, reddit_class):
        self.processor._message.subreddit = 'foo'
        assert self.processor._check_queuable() == 'modmail'
    
    def test_check_queuable_no_author(self, reddit_class):
        self.processor._message.author = None
        assert self.processor._check_queuable() == 'no_author'
    
    def test_check_queuable_system_message(self, reddit_class):
        self.processor._message.author.name = 'reddit'
        assert self.processor._check_queuable() == 'system_message'
    
    def test_check_queuable_not_incoming(self, reddit_class):
        self.processor._message.dest = '#subreddit'
        assert self.processor._check_queuable() == 'not_incoming'


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
