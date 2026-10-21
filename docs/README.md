# Docs Index

Start with the root README, ACCEPTANCE.md and RELEASE_STATUS.md for TravelAgent.
Most backend/spec/setup documents below
describe the preserved MT/Muse implementation and may require excluded legacy
POI data; they are not a claim that every historical feature is complete.

## Read In This Order

1. [../README.md](../README.md)
2. [RELEASE_STATUS.md](RELEASE_STATUS.md)
3. [../NOTICE.md](../NOTICE.md)
4. [architecture/TRAVEL_DELIVERY.md](architecture/TRAVEL_DELIVERY.md)
5. [architecture/DRAFT_CLARIFICATION.md](architecture/DRAFT_CLARIFICATION.md)
6. [architecture/WEB_EDITING.md](architecture/WEB_EDITING.md)
7. [architecture/AMAP_PROXY.md](architecture/AMAP_PROXY.md)
8. [architecture/BROWSER_ACCEPTANCE.md](architecture/BROWSER_ACCEPTANCE.md)
9. [legacy/MUSE_README.md](legacy/MUSE_README.md) (historical)

Current multiday overview and opt-in live quality checks: [architecture/MULTIDAY_QUALITY.md](architecture/MULTIDAY_QUALITY.md).

Time feasibility diagnostics and Web adjustment guidance: [architecture/TIME_CONSTRAINTS.md](architecture/TIME_CONSTRAINTS.md).

Bounded keyword/stop-count matrix and measured live results: [architecture/EXPANDED_QUALITY.md](architecture/EXPANDED_QUALITY.md).

Saved itinerary filters, direct parent relationships and read-only version comparison: [architecture/SAVED_VERSIONS.md](architecture/SAVED_VERSIONS.md).

Owner-scoped full-history search, snapshot pagination and direct-child counts: [architecture/SAVED_PAGINATION.md](architecture/SAVED_PAGINATION.md).

## Doc Groups

- `architecture/`: orchestration boundaries, coordinator, tool contracts, UI structure.
- `setup/`: local run/debug commands.
- `specs/`: current system shape, context/memory rules, and near-term roadmap.

## Notes

- `TECHNICAL_REPORT.md` and `TECHNICAL_REPORT_DETAILED.md` are background reports, not the source of truth.
- Older planning drafts were removed from the main reading path after the backend moved to `ExecutionPlan + Tool Layer + workflow_trace`.
