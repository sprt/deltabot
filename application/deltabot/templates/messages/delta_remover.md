{% if error == 'already_removed' %}
Already removed.
{% elif error == 'is_approved' %}
Already approved.
{% elif error == 'no_record' %}
No record of the delta in the database.
{% else %}
Delta removed.
{% endif %}
