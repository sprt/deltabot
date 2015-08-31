{% if error == 'no_record' %}
No record of the delta in the database.
{% elif error == 'is_removed' %}
That delta was removed.
{% elif error == 'already_approved' %}
Delta already approved.
{% else %}
Delta approved.
{% endif %}
