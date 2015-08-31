{# start not queuable #}
{% if error == 'no_author' %}
Deleted comment.
{# No need to include no_token since adding a delta is forced when from a
command message #}
{# start not processable #}
{% elif error == 'already_awarded' %}
Already awarded that redditor a delta on this submission.
{% elif error == 'toplevel_comment' %}
Delta awarder is a top-level comment.
{% elif error == 'awardee_is_awarder' %}
Trying to award a delta to oneself.
{% elif error == 'awardee_is_deltabot' %}
Can't award DeltaBot a delta.
{% elif error == 'awardee_is_op' %}
Can't award OP a delta.
{% else %}
Delta awarded to /u/{{ awardee_username }}
{% endif %}
