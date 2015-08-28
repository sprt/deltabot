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


class DatastoreTestMixin(object):
    nosegae_datastore_v3 = True
    nosegae_datastore_v3_kwargs = {
        'consistency_policy':
            datastore_stub_util.PseudoRandomHRConsistencyPolicy(probability=0),
    }
    
    def setUp(self):
        ndb.get_context().set_cache_policy(False)


# class TestMessageProcessor(unittest.TestCase):
#     def setUp(self):
#         self.processor = bot.MessageProcessor()
    
#     def test_get_command_name(self):
#         pass


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
        assert self.consumer.PROCESSOR.return_value.queue.called
    
    def test_process_item_already_processed(self):
        utils.KVStore_set('foos_processed:a')
        self.consumer._process_item(Mock(id='a'))
        taskqueue_stub = self.testbed.get_stub('taskqueue')
        assert len(taskqueue_stub.get_filtered_tasks()) == 0
    
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


class TestGenerateUserFlair(unittest.TestCase, DatastoreTestMixin,
                            TaskQueueTestMixin):
    def setUp(self):
        delta = utils.ndb_model(
            Delta,
            awarded_at=datetime.now(),
            awarded_by='mary',
            awarded_to='john',
            awarder_comment_id='foo',
            awarder_comment_url='http://awardercomment/',
            submission_id='sbmsn',
            submission_title='Blah',
            submission_url='http://linkurl/')
        delta.put()
    
    def test_has_delta(self):
        assert bot._generate_user_flair('john') == '1+'
    
    def test_has_no_delta(self):
        assert bot._generate_user_flair('stranger') == ''


@patch('application.deltabot.utils.praw.Reddit')
def test_update_user_flair(reddit_class):
    init_datastore_stub(test_update_user_flair)
    bot.update_user_flair('john')
    assert reddit_class.return_value.set_flair.called


def test_get_user_deltas():
    init_datastore_stub(test_get_user_deltas)
    
    def make_delta(**kwargs):
        defaults = {
            'awarded_by': 'mary',
            'awarded_to': 'john',
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
    delta1 = make_delta(awarded_at=now)
    delta2 = make_delta(awarded_at=now + timedelta(seconds=1))
    ndb.put_multi([delta1, delta2])
    
    assert bot._get_user_deltas('john') == [delta2, delta1]


@patch('application.deltabot.utils.praw.Reddit')
def test_update_user_wiki_page(reddit_class):
    init_datastore_stub(test_update_user_wiki_page)
    bot.update_user_wiki_page('john')
    assert reddit_class.return_value.edit_wiki_page.called


def test_get_deltas_grouped_by_users():
    init_datastore_stub(test_get_deltas_grouped_by_users)
    
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


@patch('application.deltabot.utils.praw.Reddit')
def test_update_tracker_wiki_page(reddit_class):
    init_datastore_stub(test_update_tracker_wiki_page)
    bot.update_tracker_wiki_page()
    assert reddit_class.return_value.edit_wiki_page.called


class TestHasDeltaToken(unittest.TestCase):
    """Test the CommentProcessor._has_delta_token() method"""
    
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


@patch('application.deltabot.utils.praw.Reddit')
class TestCommentProcessorBase(unittest.TestCase, DatastoreTestMixin,
                               TaskQueueTestMixin):
    def setUp(self):
        super(TestCommentProcessorBase, self).setUp()
        
        self.awarder_comment = PickableMock(
            author='john',
            body='You genius! +',
            created_utc=0.0,
            id='foo',
            is_root=False,
            link_id='t3_sbmsn',
            link_title='Blah',
            link_url='http://linkurl/',
            parent_id='parent')
        
        self.awardee_comment = PickableMock(
            author='mary',
            id='parent')
        
        self.processor = bot.CommentProcessor(self.awarder_comment)
        self.processor._awarder_comment_url = 'http://awardercomment/'
    
    def test_awardee_comment(self, reddit_class):
        reddit_class.return_value.get_info.return_value = self.awardee_comment
        assert self.processor._awardee_comment.id == 'parent'
    
    # def test_update_records(self, reddit_class):
    #     reddit_class.return_value.get_info.return_value = self.awardee_comment
        
    #     self.processor._update_records()
        
    #     assert utils.ndb_query(Delta).get().to_dict() == {
    #         'awarded_at': datetime(1970, 1, 1, 0, 0, 0),
    #         'awarded_by': 'john',
    #         'awarded_to': 'mary',
    #         'awarder_comment_id': 'foo',
    #         'awarder_comment_url': 'http://awardercomment/',
    #         'submission_id': 'sbmsn',
    #         'submission_title': 'Blah',
    #         'submission_url': 'http://linkurl/',
    #     }
    
    # @patch('application.deltabot.utils.deferred.defer', wraps=deferred.defer)
    # def test_reply_to_awarder_defer_fail(self, defer_func, reddit_class):
    #     reddit_class.return_value.get_info.return_value = self.awardee_comment
    #     defer_func.side_effect = Exception
        
    #     try:
    #         self.processor._reply_to_awarder()
    #     except Exception, e:
    #         self.fail()
        
    #     self.awarder_comment.reply.assert_called_with(
    #         self.processor._get_reply_message())
    
    # def test_update_submission_flair(self, reddit_class):
    #     self.processor._update_submission_flair()
        
    #     reddit_class().set_flair.assert_called_with(
    #         config.SUBREDDIT, self.awarder_comment.submission,
    #         '[Deltas Awarded]', 'OPdelta')


@patch('application.deltabot.utils.praw.Reddit')
class TestCommentProcessorValidDelta(unittest.TestCase, DatastoreTestMixin,
                                     TaskQueueTestMixin):
    def setUp(self):
        super(TestCommentProcessorValidDelta, self).setUp()
        
        self.awarder_comment = PickableMock(
            author='john',
            body='You genius! +',
            created_utc=0.0,
            id='foo',
            is_root=False,
            link_id='t3_sbmsn',
            link_title='Blah',
            link_url='http://linkurl/',
            parent_id='parent')
        
        self.awardee_comment = PickableMock(
            author='mary',
            id='parent')
        
        self.processor = bot.CommentProcessor(self.awarder_comment)
        self.processor._awarder_comment_url = 'http://awardercomment/'
    
    # def test_invalid_reason(self, reddit_class):
    #     reddit_class.return_value.get_info.return_value = self.awardee_comment
    #     assert self.processor._invalid_reason is None
    
    # def test_is_valid(self, reddit_class):
    #     reddit_class.return_value.get_info.return_value = self.awardee_comment
    #     assert self.processor._is_valid
    
    # def test_get_reply_message(self, reddit_class):
    #     reddit_class.return_value.get_info.return_value = self.awardee_comment
    #     assert ('Confirmation: delta awarded' in
    #             self.processor._get_reply_message())
    
    # @patch('application.deltabot.utils.deferred.defer', wraps=deferred.defer)
    # def test_run(self, defer_func, reddit_class):
    #     reddit_class.return_value.get_info.return_value = self.awardee_comment
        
    #     self.processor._update_records = PickableMock()
    #     self.processor._update_submission_flair = PickableMock()
    #     self.processor._reply_to_awarder = PickableMock()
        
    #     self.processor.run()
        
    #     assert self.processor._update_records.called
        
    #     defer_calls = [
    #         call(bot.update_user_flair, 'mary', _queue='reddit',
    #              _transactional=True),
    #         call(self.processor._update_submission_flair, _queue='reddit',
    #              _transactional=True),
    #         call(bot.update_user_wiki_page, 'mary', _queue='reddit',
    #              _transactional=True),
    #         call(self.processor._reply_to_awarder, _queue='reddit',
    #              _transactional=True),
    #     ]
    #     defer_func.assert_has_calls(defer_calls, any_order=True)


# @patch('application.deltabot.utils.praw.Reddit')
# class TestCommentProcessorInvalidDelta(DatastoreTestMixin, TaskQueueTestMixin):
#     def setUp(self):
#         super(TestCommentProcessorInvalidDelta, self).setUp()
        
#         # Setup the comments so they match all the errors. The awardee_is_*
#         # errors are special as they're mutually exclusive so we match
#         # awardee_is_awarder by default and we'll do the others in the specific
#         # tests.
        
#         self.awarder_comment = PickableMock(
#             author='john',
#             body='',  # no_token
#             created_utc=0.0,
#             id='foo',
#             is_root=True,  # toplevel_comment
#             link_author='op',
#             link_id='t3_sbmsn',
#             link_title='Blah',
#             link_url='http://linkurl/',
#             parent_id='parent')
        
#         self.awardee_comment = PickableMock(
#             author='john',  # awardee_is_awarder (NOT deltabot, NOT op)
#             id='parent')
        
#         delta = utils.ndb_model(
#             Delta,
#             awarded_at=datetime.now(),
#             awarded_by='john',
#             awarded_to='john',
#             awarder_comment_id='foo',
#             awarder_comment_url='http://awardercomment/',
#             submission_id='sbmsn',
#             submission_title='Blah',
#             submission_url='http://linkurl/')
#         delta.put()  # already_awarded
        
#         self.processor = bot.CommentProcessor(self.awarder_comment)
    
#     def test_invalid_reason_no_token(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
#         assert (self.processor._invalid_reason ==
#                 bot.DeltaRejectedReason.no_token)
    
#     # TODO: reply message
    
#     def test_invalid_reason_already_awarded(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
#         self.awarder_comment.body = '+'  # still no_explanation
#         assert (self.processor._invalid_reason ==
#                 bot.DeltaRejectedReason.already_awarded)
    
#     def test_invalid_reason_toplevel_comment(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
        
#         self.awarder_comment.body = '+'
#         utils.ndb_query(Delta).get(keys_only=True).delete()
        
#         assert (self.processor._invalid_reason ==
#                 bot.DeltaRejectedReason.toplevel_comment)
    
#     def test_invalid_reason_awardee_is_awarder(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
        
#         self.awarder_comment.body = '+'
#         utils.ndb_query(Delta).get(keys_only=True).delete()
#         self.awarder_comment.is_root = False
        
#         assert (self.processor._invalid_reason ==
#                 bot.DeltaRejectedReason.awardee_is_awarder)
    
#     def test_invalid_reason_awardee_is_deltabot(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
        
#         self.awarder_comment.body = '+'
#         utils.ndb_query(Delta).get(keys_only=True).delete()
#         self.awarder_comment.is_root = False
#         self.awardee_comment.author = 'bot'
        
#         assert (self.processor._invalid_reason ==
#                 bot.DeltaRejectedReason.awardee_is_deltabot)
    
#     def test_invalid_reason_awardee_is_op(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
        
#         self.awarder_comment.body = '+'
#         utils.ndb_query(Delta).get(keys_only=True).delete()
#         self.awarder_comment.is_root = False
#         self.awardee_comment.author = 'op'
        
#         assert (self.processor._invalid_reason ==
#                 bot.DeltaRejectedReason.awardee_is_op)
    
#     def test_invalid_reason_awardee_no_explanation(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
        
#         self.awarder_comment.body = '+'
#         utils.ndb_query(Delta).get(keys_only=True).delete()
#         self.awarder_comment.is_root = False
#         self.awardee_comment.author = 'stranger'
        
#         assert (self.processor._invalid_reason ==
#                 bot.DeltaRejectedReason.no_explanation)
    
#     def test_invalid_reason_none(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
        
#         self.awarder_comment.body = '+ because blah'
#         utils.ndb_query(Delta).get(keys_only=True).delete()
#         self.awarder_comment.is_root = False
#         self.awardee_comment.author = 'stranger'
        
#         assert self.processor._invalid_reason is None
    
#     def test_get_reply_message(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
#         self.processor._invalid_reason = \
#             bot.DeltaRejectedReason.already_awarded
        
#         assert 'already awarded' in self.processor._get_reply_message()
    
#     def test_run(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
#         self.processor._update_records = PickableMock()
        
#         self.processor.run()
        
#         assert not self.processor._update_records.called
    
#     def test_run_reason_no_token(self, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
#         self.processor._invalid_reason = bot.DeltaRejectedReason.no_token
        
#         self.processor.run()
        
#         assert not self.testbed.get_stub('taskqueue').get_filtered_tasks()
    
#     @patch('application.deltabot.utils.deferred.defer', wraps=deferred.defer)
#     def test_run_reason_other(self, defer_func, reddit_class):
#         reddit_class.return_value.get_info.return_value = self.awardee_comment
#         self.processor._invalid_reason = \
#             bot.DeltaRejectedReason.already_awarded
        
#         self.processor.run()
        
#         assert defer_func.call_args_list == [
#             call(self.processor._reply_to_awarder, _queue='reddit',
#                  _transactional=True),
#         ]


# @patch('application.deltabot.utils.deferred.defer', wraps=deferred.defer)
# @patch('application.deltabot.utils.praw.Reddit')
# def test_comment_consumer(reddit_class, defer_func):
#     init_datastore_stub(test_comment_consumer)
#     test_comment_consumer.testbed.init_taskqueue_stub(
#         root_path=os.path.join(os.path.dirname(__file__), '../..'))
    
#     comment_a = PickableMock(id='a', author='john', link_id='')
#     comment_b = PickableMock(id='b', author='john', link_id='')
    
#     reddit_object = reddit_class.return_value
#     reddit_object.get_comments.return_value = [
#         PickableMock(id='e', author='john', link_id=''),
#         PickableMock(id='d', author='john', link_id=''),
#         PickableMock(id='c', author='bot', link_id=''),
#         comment_b,
#         comment_a,
#     ]
    
#     utils.KVStore_set('placeholder', 'd')
#     utils.KVStore_set('processed_comments:d')
#     utils.KVStore_set('processed_comments:e')
#     consumer = bot.CommentsConsumer()
#     consumer.run()
    
#     bot.CommentProcessor.__eq__ = (
#         lambda self, other: self._awarder_comment == other._awarder_comment)
    
#     assert defer_func.call_args_list == [
#         call(bot.CommentProcessor(comment_a).run, _queue='reddit',
#              _transactional=True),
#         call(bot.CommentProcessor(comment_b).run, _queue='reddit',
#              _transactional=True),
#         # c: bot comment
#         # d: placeholder
#         # e: already processed
#         call(bot.update_tracker_wiki_page, _queue='reddit'),
#     ]
    
#     for id in ['a', 'b', 'c', 'd', 'e']:
#         assert utils.KVStore_exists('processed_comments:{}'.format(id))
    
#     assert utils.KVStore_get('placeholder') == 'e'
