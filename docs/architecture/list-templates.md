# List Templates

List Templates are reusable, Home-scoped definitions for Lists. A template has
an owner, a Personal or Household scope, ordered sections and ordered default
items. Personal templates are visible and editable only by their owner;
Household templates follow the existing `lists.view`/`lists.manage`
capabilities.

Creating a List with `template_id` copies the template sections and default
items into new `household_list_sections` and `household_list_items` rows. The
new List stores optional source-template provenance, but has no live dependency
on the template. Later template changes therefore cannot alter an existing
List. Existing Lists remain valid because their section and source fields are
nullable.

The initial API supports listing, searching, creating, replacing/editing,
duplicating and archiving templates. Public libraries, cross-Home sharing,
versioning, smart categorisation and silent template synchronisation are
intentionally deferred.
