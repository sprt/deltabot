import os

from google.appengine.ext import vendor

vendor.add(os.path.join(os.path.dirname(__file__), 'lib'))

appstats_TZOFFSET = -2 * 3600
appstats_SHELL_OK = True
appstats_DATASTORE_DETAILS = True
appstats_CALC_RPC_COSTS = True


def webapp_add_wsgi_middleware(app):
    from google.appengine.ext.appstats import recording
    app = recording.appstats_wsgi_middleware(app)
    return app
