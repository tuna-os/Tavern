# Incident Response & Postmortem Runbook

## Triage Procedure
1. **Severity Assessment**:
   - **P0 / Critical**: Flatpak launch crash on start, data loss, severe regression affecting all users.
   - **P1 / High**: Core feature broken without workaround (e.g. app listing failed to load).
   - **P2 / Medium**: Minor cosmetic or localized feature regression.
2. **Initial Action**:
   - File an issue using `.github/ISSUE_TEMPLATE/incident_report.md`.
   - Identify last known good commit and isolate broken PR/commit.

## Escalation & Containment
- Revert faulty commits if CI or production build fails.
- Create operational hotfix PR tagged with `hold` for human review.

## Postmortem Execution
- Complete `.github/ISSUE_TEMPLATE/postmortem.md` for all P0/P1 incidents within 48 hours.
- Record root causes, timeline, and preventive operational action items.
