import os
from flask import Flask

app = Flask(__name__)
app.config['IS_DEV'] = (os.environ.get('SERVER_SOFTWARE', '')
                        .startswith('Development'))
app.config['DEBUG'] = app.config['IS_DEV']

os.environ['REDDIT_SITE'] = 'prod' if not app.config['IS_DEV'] else 'dev'

import views  # noqa
