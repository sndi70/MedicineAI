# MedicineAI — Project Plan and Architecture Proposal

**Status:** Proposal based on the current repository
**Repository:** [github.com/sndi70/MedicineAI](https://github.com/sndi70/MedicineAI)
**Current implementation:** Flask, SQLite, browser-native JavaScript, HTML, and CSS

## 1. Executive summary

MedicineAI is a small, Bulgarian-language family medicine register. It helps a household keep medicine purchases organized by family member, look up product details by barcode, view package photos, and see an estimated stock run-out warning.

The current application is intentionally local-first: Flask serves a static browser interface and JSON API, while SQLite stores family profiles and medicine purchase records on the same machine. Barcode lookup calls public product catalogs, including Barcode.bg. This proposal keeps that lightweight architecture for its immediate roadmap and defines a staged path for reliability, data portability, and (only if needed) secure multi-user hosting.

MedicineAI is a household recordkeeping aid, not a medical device or prescribing system. Run-out estimates depend on user-entered information and do not confirm doses actually taken.

## 2. Goals and scope

### Product goals

1. Keep each family member's medicine purchase records separate and easy to review.
2. Reduce manual product entry with barcode-based product name, image, and package-size lookup.
3. Make estimated low-stock or run-out timing visible and understandable.
4. Preserve data locally and make it practical to back up and restore.
5. Keep the application easy to install, run, test, and maintain.

### Out of scope for the current local application

- Medical advice, dosage recommendations, prescribing, or interaction checking.
- Automatic proof of adherence or remaining stock; estimates are not actual counts.
- Public or multi-household hosting without a separately designed authentication and deployment layer.
- Dependence on any one external catalog being available or complete.

## 3. Current system baseline

The following describes code currently in the repository, not future recommendations:

- `app.py` creates the Flask app, initializes SQLite, validates API requests, serves the UI, calculates run-out dates, and coordinates external barcode lookups.
- `public/index.html`, `public/app.js`, and `public/styles.css` make up the browser UI. The UI loads an aggregate overview, selects family members, shows medicine cards and warnings, and handles forms and barcode searches.
- SQLite stores `family_members` and `medicines`. Medicine rows reference a family member with `ON DELETE CASCADE`; an index supports member-specific inventory queries. Foreign-key enforcement and WAL mode are enabled.
- `/api/overview` returns profiles and their medicines in one request. Compatibility routes also serve family and medicine lists and CRUD operations. `/api/lookup/<barcode>` queries Barcode.bg and public product catalogs.
- Catalog failures can occur independently of the local medicine list. The UI allows manual entry if product data is missing.
- Tests use Python's built-in `unittest` and Flask's test client. External catalog responses are mocked for deterministic tests.
- There is no user authentication or authorization. The current documented deployment is local and intended for a trusted environment. Data is stored in `data/medicine-cabinet.sqlite`, which is ignored by Git.

## 4. Proposed architecture

### 4.1 Logical view

```text
┌───────────────────────────────────┐
│ Browser UI                        │
│ HTML + CSS + JavaScript           │
│ Profile selection, inventory,     │
│ forms, barcode lookup, warnings   │
└────────────────┬──────────────────┘
                 │ same-origin JSON / HTTP
┌────────────────▼──────────────────┐
│ Flask application                  │
│                                    │
│ Routes and request validation      │
│ Family and medicine use cases      │
│ Stock estimate and package parsing │
│ Catalog lookup coordination        │
└───────────┬────────────────┬───────┘
            │                │ HTTPS, bounded timeouts
┌───────────▼────────┐  ┌────▼──────────────────────┐
│ SQLite repository  │  │ External product catalogs │
│ profiles, purchase │  │ Barcode.bg and Open Facts │
│ records, indexes   │  │ series                    │
└───────────────────┘  └───────────────────────────┘
```

### 4.2 Module responsibilities

| Module | Responsibility | Current location |
|---|---|---|
| Browser presentation | Accessible controls, profile selection, medicine forms/cards, image preview, local filtering, status and error messages | `public/index.html`, `public/app.js`, `public/styles.css` |
| HTTP/API layer | Parse input, validate parameters, return consistent JSON and HTTP status codes, invoke application behavior | `app.py` Flask routes |
| Family and inventory use cases | Add/delete profiles and medicine purchases; preserve member-to-medicine relationships | `app.py` route handlers and SQLite queries |
| Inventory calculations | Parse medicine quantities and units, estimate run-out date and warning window | `app.py` calculation helpers; UI rendering in `public/app.js` |
| Product lookup integration | Query Barcode.bg and public catalogs, normalize package descriptions, select product details and images | `app.py` catalog lookup functions |
| Persistence | Enforce row constraints, foreign keys, deletion cascade, and member inventory access | SQLite schema in `app.py` |
| Verification | Test API, validation, calculations, parsing, persistence, and catalog behavior | `tests/test_app.py` |

### 4.3 Recommended code organization

For the current small application, retain the single-process Flask + SQLite deployment and avoid premature service splitting. As `app.py` grows, separate code along responsibilities while keeping behavior and API contracts stable:

```text
app.py                    application factory and Flask registration
medicineai/
  api/                    route handlers and request/response mapping
  services/               inventory estimates, family and medicine rules
  catalogs/               Barcode.bg and Open Facts adapters
  repositories/           SQLite queries and transaction boundaries
  db.py                   schema initialization and connection lifecycle
public/                   static browser client
tests/                    route, service, repository, and catalog tests
```

This is a maintainability refactor, not a requirement to add a framework or database server. Extract a module when there is a clear ownership boundary and focused tests can protect the moved behavior.

## 5. Data and API proposal

### 5.1 Current core records

**Family member:** integer ID, display name, creation timestamp. Names are checked case-insensitively in application logic; Python Unicode `casefold()` handles Cyrillic case variants.

**Medicine purchase:** integer ID, owning member ID, barcode, product name, optional image URL, optional package size, purchased package quantity, purchase date, daily usage description, and creation timestamp.

The current medicine row represents a purchase entry. If users later need to merge repeat purchases or track a changing remaining stock, introduce an explicit medicine/product concept and stock movements through a planned migration rather than overloading the existing purchase row.

### 5.2 API conventions to preserve

- Keep JSON request and response shapes stable for the current browser client.
- Validate identifiers, barcode length/content, required fields, quantity bounds, dates, and image URL scheme before writes.
- Use meaningful status codes: `201` for created, `204` for deleted, `400` for invalid input, `404` for missing records, and `409` for duplicate names.
- Return actionable JSON errors; do not silently turn an upstream failure into a successful product match.
- Keep barcode lookup read-only with respect to the medicine inventory. Persist a purchase only after the user confirms the form.

Existing API surface: `GET /api/overview`, family list/create/delete routes, medicine list/create/delete routes, `PATCH /api/medicines/<id>/image`, and `GET /api/lookup/<barcode>`.

## 6. Non-functional requirements and safeguards

### Reliability

- Local profile and inventory operations should continue to work if all catalog services are unavailable.
- Give each upstream lookup a bounded timeout, validate response types and image URL schemes, and report lookup failure separately from “not found.”
- Keep the UI usable with no image, no package size, or an offline catalog.
- Make database writes explicit and preserve foreign-key enforcement. Backups must be consistent with SQLite's journal mode.

### Privacy and security

- Keep the SQLite database and backups out of version control; never include household data in logs or screenshots intended for publication.
- The current app has no authentication and must not be exposed to an untrusted network as-is.
- If remote/multi-user hosting becomes a requirement, design authentication, authorization, HTTPS, secret management, rate limits, secure session settings, deployment logging, and per-household data isolation before deployment.
- Continue validating externally supplied image URLs as HTTPS. Consider stricter host/content validation if image fetching is ever moved server-side.

### Correctness and usability

- Describe warnings as estimates, not confirmed stock or medical advice.
- Only calculate a date when units and usage frequency can be interpreted safely; omit the estimate when quantities are ambiguous.
- Make all important actions keyboard-accessible and provide labels, visible errors, and status announcements.
- Keep the supported Python range and dependency versions documented and verify them in CI.

## 7. Project plan

Work is ordered by value and dependency. Items marked as completed are present in the current repository; remaining items are proposals.

### Phase 0 — Existing usable baseline (complete)

- Family profiles and member-specific medicine purchase records.
- SQLite schema, Flask JSON API, static Bulgarian interface.
- Barcode lookup through Barcode.bg and Open Facts catalogs, with manual-entry fallback.
- Product image preview and package-size extraction/normalization.
- Run-out estimate and three-day warning for interpretable quantities.
- Regression tests for API behavior, catalog response handling, Unicode duplicate names, and stock calculations.

**Exit criteria:** local app runs; API and UI behavior are usable; unit suite passes. Current baseline: `python -m unittest discover -s tests` (27 tests at proposal authoring time).

### Phase 1 — Data safety and operational reliability (recommended next)

1. Add a documented, user-invoked SQLite backup/export flow; do not upload backups automatically.
2. Add restore/import validation, an explicit confirmation, and a pre-restore safety copy.
3. Add a small end-to-end smoke check for app startup, `/api/overview`, and static assets.
4. Add CI for supported Python versions: install dependencies, run `py_compile`, and execute the unittest suite.
5. Add operational guidance for database backup, restore, and catalog outage behavior.

**Exit criteria:** a user can create a backup, restore it into a test database, and verify profiles and medicine records; CI runs on each pull request.

### Phase 2 — Maintainability and product quality

1. Extract catalog, calculation, persistence, and API modules without changing response contracts.
2. Add focused tests for each extracted boundary before removing the old implementation.
3. Improve package/unit parsing through test fixtures representing real Bulgarian and international catalog names.
4. Add accessibility and responsive-layout smoke checks to release validation.
5. Add structured, privacy-conscious error logging and basic health diagnostics.

**Exit criteria:** all existing API and behavior tests still pass; module responsibilities are clear; logs contain no medicine details or household names.

### Phase 3 — Optional shared/remote use (only after product decision)

1. Confirm whether multi-user use is actually required.
2. Select a deployment and persistence model; assess whether SQLite remains appropriate for the expected concurrent write load.
3. Implement sign-in, authorization, household isolation, secure transport, secret handling, backup/restore, and account lifecycle.
4. Review privacy, retention, recovery, and deployment operations before inviting users.
5. Run security and load testing against an isolated staging deployment.

**Exit criteria:** a threat model and privacy plan are approved; cross-household access tests pass; recovery and deployment runbooks exist. This phase is not covered by the current local-only implementation.

## 8. Testing and release strategy

### Automated checks

- **Unit:** quantity parsing, unit matching, package-size normalization, and run-out date edge cases.
- **API integration:** valid/invalid JSON, field limits, status codes, CRUD operations, duplicate Cyrillic names, and cascade deletion.
- **Persistence:** isolated temporary SQLite database per test; verify foreign keys, schema initialization, and read/write behavior.
- **Catalog adapter:** mock HTTP responses for exact barcode match, missing product, malformed response, timeout, and mixed catalog availability.
- **Smoke/UI:** start the application and verify the overview endpoint and core controls; run a browser check for profile selection, lookup result, and warning rendering.
- **Regression:** preserve the current `unittest` suite and run it before each commit and in CI.

### Release checklist

- [ ] Unit and API tests pass.
- [ ] Fresh install and start instructions work on a supported Python version.
- [ ] Existing local database opens without destructive migration.
- [ ] Catalog lookup failure still permits manual entry and does not lose local records.
- [ ] Backup and restore have been tested (required before implementing Phase 1 data portability).
- [ ] No database, environment file, credentials, or personal data is included in the release.
- [ ] Release notes state that run-out dates are estimates, not medical guidance.

## 9. Risks, assumptions, and decisions

| Risk or assumption | Impact | Mitigation / decision |
|---|---|---|
| Public catalogs have incomplete, changing, or unavailable medicine data | Incorrect or absent autofill | Treat catalog output as a suggestion, show source, allow edits/manual entry, and mock outage behavior in tests |
| Package size and daily usage are free-text values | Run-out estimate may be unavailable or wrong | Parse conservatively; do not display a calculated date for incompatible/ambiguous units |
| Local data exists only on the host machine | Disk loss can destroy inventory | Prioritize explicit, tested backup and restore |
| The current app lacks authentication | Unsafe if exposed beyond a trusted local environment | Keep local-only; require a separate security design before remote deployment |
| One medicine record currently represents one purchase | Repeat buys may appear as separate cards | Preserve this semantics now; consider product/stock-movement model only with a migration plan |
| Storage and database are local | Concurrent multi-user access is not a current goal | Keep SQLite until measured requirements justify a different datastore |

### Decisions requested before future expansion

1. Should the app remain a local single-household register, or is remote access required?
2. Should users enter stock adjustments or actual doses, or should the app remain purchase-and-estimate only?
3. Should export/backup be a downloadable file, a user-selected folder, or both?
4. What Python versions and operating systems must be supported in CI?

## 10. Repository references

- [Application and API](../app.py)
- [Browser UI](../public/)
- [Automated tests](../tests/test_app.py)
- [Setup and user guidance](../README.md)
- [AI-assisted development exam document](./MedicineAI_AI_Assisted_Development_Exam.docx)
