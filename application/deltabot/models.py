from google.appengine.ext import ndb


class Delta(ndb.Model):
    awarded_at = ndb.DateTimeProperty(required=True)
    awarded_by = ndb.StringProperty(required=True)
    awarded_to = ndb.StringProperty(required=True)
    awarder_comment_id = ndb.StringProperty(required=True)
    awarder_comment_url = ndb.StringProperty(indexed=False, required=True)
    submission_id = ndb.StringProperty(required=True)
    submission_title = ndb.StringProperty(indexed=False, required=True)
    submission_url = ndb.StringProperty(indexed=False, required=True)
    
    status = ndb.StringProperty(choices=[
        'approved',
        'removed_abuse',
        'removed_low_effort',
        'removed_remind',
    ])
    
    @property
    def is_removed(self):
        return self.removed_why is not None
    
    @classmethod
    def filter_removed(cls, qry):
        return qry.filter(cls.removed_why != None)


class KeyValueStore(ndb.Model):
    value = ndb.StringProperty(indexed=False)
    
    @classmethod
    @ndb.transactional
    def get(cls, key, default=None, **kwargs):
        entity = cls.get_by_id(key, **kwargs)
        return entity.value if entity is not None else default
    
    @classmethod
    def exists(cls, key, **kwargs):
        return bool(cls.get_by_id(key, **kwargs))
    
    @classmethod
    def set(cls, key, value='', **kwargs):
        cls(id=key, value=value, **kwargs).put()
