#!/usr/bin/env python3
"""
Cleanup Classification Script
Reads cleanup_candidates.csv and prepares structured cleanup report.
"""

import csv
import os
from pathlib import Path
from datetime import datetime

# Configuration
CSV_FILE = "cleanup_candidates.csv"
ARCHIVE_DIR = "archive"
REPORT_FILE = "CLEANUP_PLAN.md"
SUMMARY_FILE = "CLEANUP_SUMMARY.txt"

def load_cleanup_candidates(csv_path):
    """Load cleanup candidates from CSV."""
    candidates = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['path'].strip():  # Skip empty lines
                    candidates.append({
                        'path': row['path'].strip(),
                        'classification': row['classification'].strip(),
                        'note': row['note'].strip()
                    })
    except FileNotFoundError:
        print(f"ERROR: {csv_path} not found")
        return []
    return candidates

def generate_cleanup_plan(candidates, output_path):
    """Generate comprehensive cleanup plan markdown."""
    keep_files = [c for c in candidates if c['classification'] == 'KEEP']
    archive_files = [c for c in candidates if c['classification'] == 'ARCHIVE']
    review_files = [c for c in candidates if c['classification'] == 'NEEDS-REVIEW']
    
    md_content = f"""# 🗂️ PROJECT CLEANUP PLAN

**Generated**: {datetime.now().isoformat()}  
**Status**: Identification Phase (No deletions yet)

## Overview

| Category | Count | Action |
|----------|-------|--------|
| **KEEP** | {len(keep_files)} | Remain in active tree |
| **ARCHIVE** | {len(archive_files)} | Move to archive/ (no deletion) |
| **NEEDS-REVIEW** | {len(review_files)} | Review before moving/deleting |
| **TOTAL** | {len(candidates)} | - |

---

## ✅ KEEP (Active Files)

Files essential to the project remain in place.

"""
    
    for f in keep_files:
        md_content += f"- [{f['path']}]({f['path']}) — {f['note']}\n"
    
    md_content += f"""
---

## 📦 ARCHIVE ({len(archive_files)} files)

Phase completion reports and status documents recommended for archiving (preserving but moving out of active tree).

```
{ARCHIVE_DIR}/
├── reports/
│   └── [phase reports moved here]
└── guides/
    └── [phase guides moved here]
```

Candidates:

"""
    
    for f in archive_files:
        md_content += f"- `{f['path']}` — {f['note']}\n"
    
    md_content += f"""
---

## 🔍 NEEDS-REVIEW ({len(review_files)} files)

Large test and E2E scripts—review for consolidation or archiving before final cleanup.

"""
    
    for f in review_files:
        md_content += f"- `{f['path']}` — {f['note']}\n"
    
    md_content += """
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
"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    print(f"✅ Generated: {output_path}")

def generate_cleanup_summary(candidates, output_path):
    """Generate cleanup summary text file."""
    keep = len([c for c in candidates if c['classification'] == 'KEEP'])
    archive = len([c for c in candidates if c['classification'] == 'ARCHIVE'])
    review = len([c for c in candidates if c['classification'] == 'NEEDS-REVIEW'])
    
    txt_content = f"""CLEANUP ANALYSIS SUMMARY
Generated: {datetime.now().isoformat()}

================================================================================
CLASSIFICATION STATISTICS
================================================================================

Total Candidates:      {len(candidates)}
  KEEP:                {keep}
  ARCHIVE:             {archive}
  NEEDS-REVIEW:        {review}

================================================================================
SPACE ESTIMATE (Rough)
================================================================================

Archive Candidates (~{archive} MD/TXT phase reports): ~2-5 MB
Test/E2E Scripts (~{review} files):                ~3-8 MB
Estimated cleanup savings:                         ~5-13 MB (non-critical)

================================================================================
RECOMMENDATIONS
================================================================================

1. ARCHIVE Phase reports to reduce clutter in active tree
   - Keep versioning history
   - Organize by phase (archive/phase1/, archive/phase2/, etc.)

2. REVIEW test files for consolidation
   - Many test_*.py files may duplicate coverage
   - Consider creating single test suite or marking deprecated tests

3. KEEP all active component code
   - No deletions of working backend/frontend code

================================================================================
NEXT STEPS (Manual)
================================================================================

Step 1: Review cleanup_candidates.csv
        - Adjust classifications if needed
        - Re-run this script after changes

Step 2: Create archive structure
        mkdir -p archive/{{phase_reports,guides,scripts,tests}}

Step 3: Move archived files
        git mv PHASE*.md archive/phase_reports/
        git mv PHASE*.txt archive/phase_reports/
        ... etc

Step 4: Commit & test
        git add -A
        git commit -m "cleanup: archive phase reports and old guides"

Step 5: Test project
        npm run build
        python -m pytest (or equivalent)

================================================================================
SAFETY CHECKLIST
================================================================================

✅ No files deleted (only moved to archive/)
✅ Archive preserved in git history
✅ Original files remain accessible via git
✅ Can be reverted with: git revert <commit>

Questions? Review CLEANUP_PLAN.md for full details.
"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(txt_content)
    print(f"✅ Generated: {output_path}")

def main():
    """Main entry point."""
    print(f"📋 Loading cleanup candidates from {CSV_FILE}...")
    candidates = load_cleanup_candidates(CSV_FILE)
    
    if not candidates:
        print("❌ No candidates loaded. Exiting.")
        return 1
    
    print(f"✅ Loaded {len(candidates)} candidates")
    
    print(f"📝 Generating {REPORT_FILE}...")
    generate_cleanup_plan(candidates, REPORT_FILE)
    
    print(f"📊 Generating {SUMMARY_FILE}...")
    generate_cleanup_summary(candidates, SUMMARY_FILE)
    
    print(f"""
✅ CLEANUP ANALYSIS COMPLETE

Generated files:
  - {CSV_FILE} (classifications)
  - {REPORT_FILE} (detailed plan)
  - {SUMMARY_FILE} (summary & stats)

Next: Review {REPORT_FILE} and confirm classifications before executing cleanup.
    """)
    
    return 0

if __name__ == '__main__':
    exit(main())
