# Data-retention policy (template)

AEGIS ships default retention classes per organisation. These are **templates** that your organisation must review, and you can edit them in Administration → Settings & retention.

| Class | Default period | Typical use |
| --- | --- | --- |
| `standard` | 365 days | Routine triage cases |
| `extended` | 7 years | Cases that may support formal proceedings |
| `legal_minimum` | 90 days | Cases closed with no further action |
| `research` | 3 years | Consented research evaluation |

Rules enforced by the software:

- The Settings & retention view lists cases past their retention period for review. Nothing is deleted automatically.
- Deletion requires a request with a reason and approval by a second, authorised person.
- Legal hold blocks deletion requests and approvals.
- A purge removes stored bytes but keeps hashes, version tombstones and audit events.
- Audit events are never purged by the application.

Organisation to define: who reviews due cases, how often; the legal-hold authority; the destruction verification method for backups.
