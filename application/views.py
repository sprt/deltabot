from google.appengine.api.taskqueue import TaskRetryOptions

from . import app
from .deltabot import config
from .deltabot.bot import CommentsConsumer, MessagesConsumer
from .deltabot.utils import defer_reddit

cron_retry_options = TaskRetryOptions(task_retry_limit=0)


@app.route('/')
def index():
    return 'Hello, World!'


@app.route('/crons/consumecomments')
def consume_comments():
    comments_consumer = CommentsConsumer()
    defer_reddit(comments_consumer.run, _retry_options=cron_retry_options)
    return 'Task enqueued'


@app.route('/crons/consumemessages')
def consume_messages():
    messages_consumer = MessagesConsumer()
    countdown = 0 if config.IS_DEV else 600
    defer_reddit(messages_consumer.run, _countdown=countdown,
                 _retry_options=cron_retry_options)
    return 'Task enqueued'


@app.route('/_ah/warmup')
def warmup():
    return ''
