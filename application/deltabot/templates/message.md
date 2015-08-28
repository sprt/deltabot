{% if error == 'not_a_mod' %}
You are not a mod of /r/{{ config.SUBREDDIT }}.
{% elif error == 'command_unknown' %}
Command unkown.
{% elif error == 'comment_not_found' %}
Comment not found.
{% endif %}

Replies will not be taken into account, send a new message.
