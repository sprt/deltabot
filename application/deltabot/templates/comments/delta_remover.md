The delta awarded to /u/{{ awardee_username }} has been removed.

{% if removal_reason == 'remind' %}
It appears you accidentally awarded it while showing someone else how to use
the delta system.  To avoid this, include the symbol in a blockquote or a code
block, as I will [ignore those][ignored_deltas].
{% endif %}

^([/u/{{ awardee_username }}'s delta history][user_delta_history] |)
^([Delta system explained][delta_system_explained])

[ignored_deltas]:
	https://www.reddit.com/r/{{ config.SUBREDDIT }}/wiki/deltabot#wiki_ignored_deltas
[user_delta_history]:
    https://www.reddit.com/r/{{ config.SUBREDDIT }}/wiki/u/{{ awardee_username }}
[delta_system_explained]:
    https://www.reddit.com/r/{{ config.SUBREDDIT }}/wiki/deltabot
