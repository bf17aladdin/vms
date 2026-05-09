# 🗂️ PROJECT CLEANUP PLAN

**Generated**: 2026-02-14T19:40:54.025161  
**Status**: Identification Phase (No deletions yet)

## Overview

| Category | Count | Action |
|----------|-------|--------|
| **KEEP** | 4 | Remain in active tree |
| **ARCHIVE** | 15 | Move to archive/ (no deletion) |
| **NEEDS-REVIEW** | 21 | Review before moving/deleting |
| **TOTAL** | 40 | - |

---

## ✅ KEEP (Active Files)

Files essential to the project remain in place.

- [vms/backend/routers/vehicle_registry.py](vms/backend/routers/vehicle_registry.py) — API router required by backend
- [vms/backend/routers/ws_ai.py](vms/backend/routers/ws_ai.py) — WebSocket AI handler
- [vms/frontend/src/pages/map/MapPage.tsx](vms/frontend/src/pages/map/MapPage.tsx) — Active frontend Map page
- [vms/frontend/src/components/Map/GoogleMapsComponent.tsx](vms/frontend/src/components/Map/GoogleMapsComponent.tsx) — Map component used by MapPage

---

## 📦 ARCHIVE (15 files)

Phase completion reports and status documents recommended for archiving (preserving but moving out of active tree).

```
archive/
├── reports/
│   └── [phase reports moved here]
└── guides/
    └── [phase guides moved here]
```

Candidates:

- `PHASE2_3_COMPLETION_REPORT.md` — Phase report - archive out of active tree
- `PROJECT_STATUS_PHASE2_3.txt` — Project status snapshot - archive
- `PHASE4_COMPLETION_REPORT.md` — Phase 4 completion report - archive
- `PHASE4_NEXT_STEPS.md` — Phase 4 next steps - archive
- `PHASE4_STATUS.txt` — Phase 4 status - archive
- `PHASE4_QUICK_START.md` — Phase 4 quick start - archive
- `PHASE5_DEPLOYMENT_GUIDE.md` — Phase 5 deployment guide - archive
- `PHASE5_COMPLETION_REPORT.md` — Phase 5 completion report - archive
- `PHASE5_QUICK_START.txt` — Phase 5 quick start - archive
- `PHASE5_INTEGRATION_COMPLETE.md` — Phase 5 integration complete - archive
- `PHASE2_INTEGRATION_GUIDE.md` — Phase 2 guide - archive
- `PHASE2_COMPLETION_REPORT.md` — Phase 2 completion report - archive
- `PHASE2_STATUS.txt` — Phase 2 status - archive
- `CLEANUP_REPORT.md` — Existing cleanup report - archive
- `CLEANUP_COMPLETE.md` — Existing cleanup complete doc - archive

---

## 🔍 NEEDS-REVIEW (21 files)

Large test and E2E scripts—review for consolidation or archiving before final cleanup.

- `phase4_e2e_test.py` — Large E2E test suite - review for duplication or archive
- `phase4_client.html` — Interactive E2E client - review
- `phase4_validate.py` — Preflight validator - review
- `phase5_smoke_test.py` — Smoke tests - review
- `deploy_phase5.py` — Deployment script - review before archiving
- `test_frontend_integration.py` — Frontend integration tests - review
- `test_websocket_e2e.py` — WebSocket E2E tests - review
- `test_e2e_complete.py` — E2E complete suite - review
- `test_quick_e2e.py` — Quick E2E test - review
- `test_vms_complete.py` — Large test file - review
- `test_vms_automated.py` — Automated tests - review
- `test_integration.py` — Integration tests - review
- `test_compiled_frontend.py` — Frontend compiled checks - review
- `test_frontend_paths.py` — Frontend path checks - review
- `test_auth_quick.py` — Auth quick tests - review
- `test_auth.py` — Auth tests - review
- `test_asset_loading.py` — Asset loading tests - review
- `test_phase4_simple.py` — Phase4 simple E2E - review
- `phase3_load_test.py` — Phase3 load test - review
- `phase3_quick_test.py` — Phase3 quick test - review
- `phase3_fast_validation.py` — Phase3 fast validation - review

---

## Implementation Steps (Manual Review)

1. **Review this plan** and approve classifications (edit `cleanup_candidates.csv` to adjust)
2. **Move ARCHIVE files** to `archive/` subdirectory structure
3. **Consolidate NEEDS-REVIEW** tests if possible (combine if testing same functionality)
4. **Create feature branch** with changes for PR review
5. **Test build & runtime** to confirm cleanup does not break project

---

## Safety Notes

✅ **No files deleted yet** — only classification and planning  
✅ **CSV can be edited** — adjust classifications before executing cleanup  
✅ **Archive = preservation** — files moved out but kept (not deleted)  
✅ **Reversible** — archive can be restored if needed

---

## Next Actions

- [ ] Review and approve classification (edit `cleanup_candidates.csv` if needed)
- [ ] Examine NEEDS-REVIEW files in detail
- [ ] Plan archive directory structure
- [ ] Create git branch `cleanup/execute` with actual moves
- [ ] Validate build after cleanup

**Questions?** See `CLEANUP_ANALYSIS.txt` for detailed notes.
