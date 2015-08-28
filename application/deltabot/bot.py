from datetime import datetime
import logging
from operator import attrgetter
import re
import threading

from cached_property import cached_property
from enum import Enum
from google.appengine.ext import ndb
from praw.objects import Submission

from . import config, utils
from .models import Delta


def _generate_user_flair(username):
    qry = utils.ndb_query(Delta, Delta.awarded_to == username)
    delta_count = qry.count(keys_only=True)
    # XXX: use delete_flair instead
    return str(delta_count) + config.DELTA if delta_count else ''


# Deferred
def update_user_flair(username):
    logging.debug("Updating /u/{}'s flair".format(username))
    r = utils.get_reddit()
    r.set_flair(config.SUBREDDIT, username, _generate_user_flair(username))


# Deferred
def update_comment_submission_flair(awarder_comment):
    logging.debug('Updating flair of submission (comment {})'
                  .format(awarder_comment.id))
    
    # XXX: test this line
    # XXX: [deleted]?
    if awarder_comment.author.name != awarder_comment.link_author:
        return
    
    r = utils.get_reddit()
    submission = awarder_comment.submission
    r.set_flair(config.SUBREDDIT, submission, '[Deltas Awarded]', 'OPdelta')


# Deferred
def update_user_wiki_page(username):
    logging.debug("Updating /u/{}'s wiki page".format(username))
    
    qry = utils.ndb_query(Delta, Delta.awarded_to == username)
    qry_ordered = qry.order(-Delta.awarded_at)
    user_deltas = qry_ordered.fetch()
    
    content_md = utils.render_template('wiki/user_history.md',
                                       username=username, deltas=user_deltas)
    
    r = utils.get_reddit()
    r.edit_wiki_page(config.SUBREDDIT, 'user/{}'.format(username), content_md)


def _get_deltas_grouped_by_users():
    all_deltas_qry = utils.ndb_query(Delta).order(-Delta.awarded_at)
    deltas_by_user = {}
    
    for delta in all_deltas_qry:
        user_delta = deltas_by_user.get(delta.awarded_to)
        if not user_delta or user_delta.awarded_at < delta.awarded_at:
            deltas_by_user[delta.awarded_to] = delta
    
    deltas = deltas_by_user.values()
    deltas.sort(key=attrgetter('awarded_to'))
    
    return deltas


# Deferred
def update_tracker_wiki_page():
    logging.debug('Updating tracker wiki page')
    
    deltas = _get_deltas_grouped_by_users()
    content_md = utils.render_template('wiki/tracker.md', deltas=deltas)
    
    r = utils.get_reddit()
    r.edit_wiki_page(config.SUBREDDIT, 'deltabot/tracker', content_md)


class ItemProcessor(object):
    NotQueuableReason = None
    NotProcessableReason = None
    
    def _is_queueable(self):
        raise NotImplementedError
    
    def _is_processable(self):
        raise NotImplementedError
    
    def before_queuing(self, is_queuable, not_queuable_reason):
        pass
    
    def after_processing(self, is_processable, not_processable_reason):
        pass
    
    def _do_processing(self):
        raise NotImplementedError
    
    def _process(self):
        is_processable, not_processable_reason = self._is_processable()
        if is_processable:
            self._do_processing()
        self.after_processing(is_processable, not_processable_reason)
    
    def queue(self):
        is_queuable, not_queuable_reason = self._is_queuable()
        self.before_queuing(is_queuable, not_queuable_reason)
        if is_queuable:
            utils.defer_reddit(self._process)


class CommentProcessor(ItemProcessor):
    def __init__(self, awarder_comment, message=None):
        self._awarder_comment = awarder_comment
        self._message = message
        self._submission_id = utils.fullname_to_id(awarder_comment.link_id)
    
    @cached_property
    def _awardee_comment(self):
        r = utils.get_reddit()
        awardee_comment_fullname = self._awarder_comment.parent_id
        return r.get_info(thing_id=awardee_comment_fullname)
    
    @cached_property
    def _stored_delta(self):
        comment_id = self._awarder_comment.id
        qry = utils.ndb_query(Delta, Delta.awarder_comment_id == comment_id)
        return qry.get()
    
    def _reply_to_comment(self, error):
        awardee_username = getattr(self._awarder_comment.author, 'name', None)
        reply_text = utils.render_template(self.COMMENT_TEMPLATE,
                                           awardee_username=awardee_username,
                                           error=error)
        
        reply = self._awarder_comment.reply(reply_text)
        
        try:
            utils.defer_reddit(reply.distinguish)
        except:
            # If, for whatever reason, the defer() call fails, an exception
            # will be thrown, causing this function to be retried, which means
            # we'll end up double-posting.  To prevent that, just don't
            # distinguish the comment if an exception is thrown.
            # It's unlikely to happen but better be safe than sorry.
            # XXX: We should probably find a workaround anyway.
            logging.warning("Couldn't distinguish comment")
    
    def _reply_to_message(self, error):
        awardee_username = getattr(self._awarder_comment.author, 'name', None)
        reply_text = utils.render_template(self.MESSAGE_TEMPLATE,
                                           awardee_username=awardee_username,
                                           error=error)
        self._message.reply(reply_text)
    
    def _update_reddit(self):
        awarder_comment = self._awarder_comment
        awardee_username = self._awardee_comment.author.name
        utils.defer_reddit(update_comment_submission_flair, awarder_comment)
        utils.defer_reddit(update_user_flair, awardee_username)
        utils.defer_reddit(update_user_wiki_page, awardee_username)
    
    def _update_records(self):
        raise NotImplementedError
    
    def before_queuing(self, is_queuable, not_queuable_reason):
        error = getattr(not_queuable_reason, 'name', None)
        if not is_queuable and self._message:
            utils.defer_reddit(self._reply_to_message, error)
    
    def after_processing(self, is_processable, not_processable_reason):
        error = getattr(not_processable_reason, 'name', None)
        if self._message:
            utils.defer_reddit(self._reply_to_message, error)
        if is_processable or not self._message:
            utils.defer_reddit(self._reply_to_comment, error)
    
    def _do_processing(self):
        self._update_records()
        self._update_reddit()


class DeltaAdder(CommentProcessor):
    # Assume expanded tabs
    RE_INLINE_CODE = re.compile(r'`[^`]+`')
    RE_BLOCK_QUOTE = re.compile(r'(?ms)^\x20{0,3}>(.+?)\n\n')
    RE_CODE_BLOCK = re.compile(r'(^\n?|\n\n)\x20{4}.+(\n(\x20{4}.+|\x20*))*'
                               r'(\n|$)')
    
    COMMENT_TEMPLATE = 'comments/delta_adder.md'
    MESSAGE_TEMPLATE = 'messages/delta_adder.md'
    
    NotQueuableReason = Enum('NotQueuableReason', [
        'no_author',
        'no_token',
    ])
    
    NotProcessableReason = Enum('NotProcessableReason', [
        'already_awarded',
        'awardee_is_awarder',
        'awardee_is_deltabot',
        'awardee_is_op',
        'no_explanation',
        'toplevel_comment',
    ])
    
    def __init__(self, awarder_comment, message=None, force=False):
        super(DeltaAdder, self).__init__(awarder_comment, message)
        self._force = force
    
    def _has_delta_token(self):
        # XXX: ignore deltas between quotes?
        text = self._awarder_comment.body.expandtabs(4)
        text = self.RE_CODE_BLOCK.sub('', text)
        text = self.RE_BLOCK_QUOTE.sub('', text + '\n\n')[:-2]
        text = self.RE_INLINE_CODE.sub('', text)
        delta_tokens = (config.DELTA,) + config.DELTA_ALIASES
        return any((token in text) for token in delta_tokens)
    
    def _get_comment_reply(self, error):
        awardee_username = self._awardee_comment.author.name
        return utils.render_template('comments/delta.md', error=error,
                                     awardee_username=awardee_username)
    
    def _update_records(self):
        awarded_at = datetime.fromtimestamp(self._awarder_comment.created_utc)
        awarder_comment_url = utils.get_comment_url(self._awarder_comment)
        delta = utils.ndb_model(
            Delta,
            awarded_at=awarded_at,
            awarded_by=self._awarder_comment.author.name,
            awarded_to=self._awardee_comment.author.name,
            awarder_comment_id=self._awarder_comment.id,
            awarder_comment_url=awarder_comment_url,
            submission_id=self._submission_id,
            submission_title=self._awarder_comment.link_title,
            submission_url=self._awarder_comment.link_url)
        delta.put()
    
    def _is_queuable(self):
        if not self._awarder_comment.author:
            return False, self.NotQueuableReason.no_author
        elif not self._has_delta_token() and not self._force:
            return False, self.NotQueuableReason.no_token
        else:
            return True, None
    
    def _is_processable(self):
        awarder_username = self._awarder_comment.author.name
        awardee_username = self._awardee_comment.author.name
        op_username = self._awarder_comment.link_author
        
        # XXX: check same comment id?
        already_awarded_qry = utils.ndb_query(
            Delta,
            Delta.awarded_by == awarder_username,
            Delta.awarded_to == awardee_username,
            Delta.submission_id == self._submission_id)
        
        # Conditions order important
        if already_awarded_qry.get(keys_only=True):
            return False, self.NotProcessableReason.already_awarded
        elif self._awarder_comment.is_root:
            return False, self.NotProcessableReason.toplevel_comment
        
        # These three are mutually exclusive, so the order doesn't matter
        elif self._awardee_comment.author.name == awarder_username:
            return False, self.NotProcessableReason.awardee_is_awarder
        elif self._awardee_comment.author.name == config.BOT_USERNAME:
            return False, self.NotProcessableReason.awardee_is_deltabot
        elif self._awardee_comment.author.name == op_username:
            return False, self.NotProcessableReason.awardee_is_op
        
        elif (self._awarder_comment.body.strip() == config.DELTA and
              not self._force):
            return False, self.NotProcessableReason.no_explanation
        else:
            return True, None


class DeltaApprover(CommentProcessor):
    NotProcessableReason = Enum('NotProcessableReason', [
        'already_removed',
        'is_approved',
        'no_record',
    ])
    
    def _is_queuable(self):
        return True, None
    
    def _is_processable(self):
        if not self._stored_delta:
            return False, self.NotProcessableReason.no_record
        elif stored_delta.removed_reason:
            return False, self.NotProcessableReason.already_removed
        elif stored_delta.is_approved:
            return False, self.NotProcessableReason.is_approved
        else:
            return True, None
    
    def _update_records(self):
        self._stored_delta.status = 'approved'
        self._stored_delta.put()
    
    def _update_reddit(self):
        pass


class DeltaRemover(CommentProcessor):
    COMMENT_TEMPLATE = 'comments/delta_remover.md'
    MESSAGE_TEMPLATE = 'messages/delta_remover.md'
    
    NotProcessableReason = Enum('NotProcessableReason', [
        'already_removed',
        'is_approved',
        'no_record',
    ])
    
    def __init__(self, awarder_comment, removal_reason, message=None):
        super(DeltaRemover, self).__init__(awarder_comment, message)
        self._removal_reason = removal_reason
    
    def _is_queuable(self):
        return True, None
    
    def _is_processable(self):
        if not self._stored_delta:
            return False, self.NotProcessableReason.no_record
        elif (self._stored_delta.status or '').startswith('removed'):
            return False, self.NotProcessableReason.already_removed
        elif self._stored_delta.status == 'approved':
            return False, self.NotProcessableReason.is_approved
        else:
            return True, None
    
    def _update_records(self):
        self._stored_delta.status = 'removed_' + self._removal_reason
        self._stored_delta.put()


class CommandMessageProcessor(ItemProcessor):
    # XXX: would look cleaner with decorators
    COMMANDS = {
        'approve': '_cmd_approve',
        'force add': '_cmd_force_add',
        'remove abuse': '_cmd_remove_abuse',
        'remove low effort': '_cmd_remove_low_effort',
        'remove remind': '_cmd_remove_remind',
    }
    
    NotQueuableReason = Enum('NotQueuableReason', [
        'no_author',
        'not_incoming',
        'system_message',
    ])
    
    NotProcessableReason = Enum('NotProcessableReason', [
        'command_not_found',
        'command_unknown',
        'not_a_mod',
    ])

    def __init__(self, message):
        self._message = message
    
    def _cmd_approve(self):
        delta_approver = DeltaApprover(self._comment, self._message)
        delta_approver.queue()
    
    def _cmd_force_add(self):
        delta_adder = DeltaAdder(self._comment, self._message, force=True)
        delta_adder.queue()
    
    def _remove(self, reason):
        delta_remover = DeltaRemover(self._comment, reason, self._message)
        delta_remover.queue()
    
    def _cmd_remove_abuse(self):
        self._remove('abuse')
    
    def _cmd_remove_low_effort(self):
        self._remove('low effort')
    
    def _cmd_remove_remind(self):
        self._remove('remind')
    
    def _get_command_name(self):
        subject = self._message.subject.strip()
        return str(subject) if subject in self.COMMANDS else None
    
    def _do_processing(self):
        command_name = self._get_command_name()
        getattr(self, self.COMMANDS[command_name])()
    
    @cached_property
    def _comment(self):
        # wot
        body_words = self._message.body.split(None, 1)
        comment_url = body_words[0]
        if not comment_url:
            return None
        comment_id = comment_url.split('/')[-1]
        if not comment_id:
            return None
        r = utils.get_reddit()
        comment = r.get_info(thing_id='t1_{}'.format(comment_id))
        return comment if comment else None
    
    def _is_queuable(self):
        if not self._message.author:  # message from sub(?)
            return False, self.NotQueuableReason.no_author
        elif self._message.author.name == 'reddit':  # system message
            return False, self.NotQueuableReason.system_message
        elif (not self._message.dest or
                  self._message.dest != config.BOT_USERNAME):
            return False, self.NotQueuableReason.not_incoming
        else:
            return True, None
    
    def _is_processable(self):
        r = utils.get_reddit()
        moderators = r.get_moderators(config.SUBREDDIT)
        moderator_usernames = set(moderator.name for moderator in moderators)
        
        if self._message.author.name not in moderator_usernames:
            return False, self.NotProcessableReason.not_a_mod
        elif not self._get_command_name():
            return False, self.NotProcessableReason.command_unknown
        elif not self._comment:
            return False, self.NotProcessableReason.comment_not_found
        else:
            return True, None
    
    def after_processing(self, is_processable, not_processable_reason):
        if not is_processable:
            reply_text = utils.render_template('message.md',
                                               error=not_processable_reason)
            self._message.reply(reply_text)


class ItemsConsumer(object):
    _lock = None
    
    PROCESSOR = None
    PLACEHOLDER_KEY = None
    PROCESSED_KEY = None
    
    def _fetch_items(self):
        raise NotImplementedError
    
    def _iter_items(self):
        items = list(self._fetch_items())
        logging.debug('Items: {}'.format(len(items)))
        items.sort(key=attrgetter('created_utc'))
        return items
    
    @ndb.transactional
    def _process_item(self, item):
        processed_key = self.PROCESSED_KEY.format(item.id)
        already_processed = utils.KVStore_exists(processed_key)
        if not already_processed:
            processor = self.PROCESSOR(item)
            processor.queue()
        utils.KVStore_set(self.PLACEHOLDER_KEY, item.id)
        utils.KVStore_set(self.PROCESSED_KEY.format(item.id))
    
    def run(self):
        with self._lock:
            self._placeholder = utils.KVStore_get(self.PLACEHOLDER_KEY)
            logging.debug('Placeholder: {}'.format(self._placeholder))
            for item in self._iter_items():
                self._process_item(item)


class CommentsConsumer(ItemsConsumer):
    _lock = threading.Lock()
    
    PROCESSOR = DeltaAdder
    PLACEHOLDER_KEY = 'comments'
    PROCESSED_KEY = 'processed_comments:{}'
    
    def _fetch_items(self):
        r = utils.get_reddit()
        return r.get_comments(config.SUBREDDIT, limit=None,
                              place_holder=self._placeholder)


class MessagesConsumer(ItemsConsumer):
    _lock = threading.Lock()
    
    PROCESSOR = CommandMessageProcessor
    PLACEHOLDER_KEY = 'comments'
    PROCESSED_KEY = 'processed_comments:{}'
    
    def _fetch_items(self):
        r = utils.get_reddit()
        messages = r.get_messages(limit=None, place_holder=self._placeholder)
        for message in messages:
            del message.replies
            yield message
