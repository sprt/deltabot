from . import app
from .deltabot.bot import CommentsConsumer, MessagesConsumer
from .deltabot.utils import defer_reddit


@app.route('/')
def index():
    return 'Hello, World!'


@app.route('/crons/consumecomments')
def consume_comments():
    comments_consumer = CommentsConsumer()
    # TODO: no retry
    defer_reddit(comments_consumer.run)
    return 'Task enqueued'


@app.route('/crons/consumemessages')
def consume_messages():
    messages_consumer = MessagesConsumer()
    # TODO: no retry
    defer_reddit(messages_consumer.run)
    return 'Task enqueued'


@app.route('/_ah/warmup')
def warmup():
    return ''
