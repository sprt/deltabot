/u/{{ username }} has received {{ deltas|length }}
{{ pluralize(deltas, 'delta', 'deltas') }} for the following
{{ pluralize(deltas, 'comment', 'comments') }}:

Date | Submission | Delta Comment | Awarded By
---- | ---------- | ------------- | ----------
{% for delta in deltas %}
{{ delta.awarded_at.strftime('%B %-d, %Y') }} | {{ delta.submission_title }} | [Link]({{ delta.awarder_comment_url }}) | /u/{{ delta.awarded_by}}
{% endfor %}
