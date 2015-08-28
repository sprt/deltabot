Below is a list of all of the users that have earned deltas.

User | Delta List | Last Delta Earned
---- | ---------- | -----------------
{% for delta in deltas %}
/u/{{ delta.awarded_to }} | [Link](/r/{{ config.SUBREDDIT }}/wiki/user/{{ delta.awarded_to }}) | [{{ delta.awarded_at.strftime('%B %-d, %Y') }}]({{ delta.awarder_comment_url }})
{% endfor %}
