# Participant template CRUD regression

The participant template page depends on Bootstrap's JavaScript modal API. Its page-specific script must load only after `bootstrap.bundle.min.js` from the base layout. Loading it from the content block causes `bootstrap is not defined`, which prevents create, edit and delete handlers from being registered.

Regression coverage verifies the rendered `/employee-lists` page loads Bootstrap before `/static/js/participant-templates.js`.
