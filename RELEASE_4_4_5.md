# ERPNext Extensions v4.4.5

Focused UI / list view enhancement release.

## Party title display

- **Post Dated Cheque** list and form now show the party **name/title** (e.g. customer name) instead of `Party Type - Code`.
- **Guarantee Document** list and form use the same title-only resolution via the shared `party_display` batch helper.
- Underlying stored values and filters are unchanged — Party Type and Party filters still use document codes.

## List view cleanup

- **Company** column removed from default Post Dated Cheque and Guarantee Document list views (Company remains available as a standard filter and on forms).

## No accounting or workflow changes

- No changes to accounting logic, workflow transitions, rollback engine, or business rules.
