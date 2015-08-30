The delta awarded to /u/{{ awardee_username }} has been removed.

{% if removal_reason == 'remind' %}
blah blah
{% endif %}

^([/u/{{ awardee_username }}'s delta history][user_delta_history] |)
^([Delta system explained][delta_system_explained])

[user_delta_history]:
    https://www.reddit.com/r/{{ config.SUBREDDIT }}/wiki/u/{{ awardee_username }}
[delta_system_explained]:
    https://www.reddit.com/r/{{ config.SUBREDDIT }}/wiki/deltabot
