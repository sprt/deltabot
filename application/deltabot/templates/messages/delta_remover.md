{% if error == 'already_removed' %}
Delta already removed.
{% elif error == 'is_approved' %}
Delta already approved.
{% elif error == 'no_record' %}
No record of the delta in the database.
{% else %}
Delta removed.
{% endif %}
