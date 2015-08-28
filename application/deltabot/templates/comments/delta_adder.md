{% if error == 'already_awarded' %}
You have already awarded that redditor a delta on this submission.
{% elif error == 'toplevel_comment' %}
You cannot award a delta in a top-level comment.
{% elif error == 'awardee_is_awarder' %}
You cannot award yourself a delta.
{% elif error == 'awardee_is_deltabot' %}
You can't award me a delta, you silly human!
{% elif error == 'awardee_is_op' %}
You cannot award OP a delta.
{% elif error == 'no_explanation' %}
You must provide an explanation when awarding a delta.

Please make a new comment including the delta token and your
explanation.  Edits to this comment will *not* be taken into account.
{% else %}
Confirmation: delta awarded to /u/{{ awardee_username }}
{% endif %}

{% if not error %}
^([/u/{{ awardee_username }}'s delta history][user_history] |)
{% endif %}
^([Delta system explained][delta_system])

[user_history]:
    https://www.reddit.com/r/{{ config.SUBREDDIT }}/wiki/user/{{ awardee_username }}
[delta_system]:
    https://www.reddit.com/r/{{ config.SUBREDDIT }}/wiki/deltabot
