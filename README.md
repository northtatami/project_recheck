# Re:Check v0.1 MVP

Re:Check is a local Windows GUI tool for reviewing folder diffs with scope selection, side-by-side previews, and saved history.

## Run

1. Install dependencies:
   - `python -m pip install -r requirements.txt`
2. Run the app:
   - PowerShell: `$env:PYTHONPATH="src"; python -m recheck`

## Implemented v0.1 scope

- Project create/save/load/switch
- Initial setup dialog
- Snapshot save and Base/Compare snapshot selection
- Scope pane:
  - Whole
  - Selected folder
  - Multiple folders
- Diff Results pane:
  - Added/Removed/Modified/Unchanged summary cards
  - Search by filename and relative path
  - Dense diff list table with sortable columns
  - Filename column + parent-folder path column (`(root)` / `（ルート）` for root files)
- Preview pane (side-by-side Base vs Compare):
  - Image
  - Text
  - PDF first-page preview with external-open fallback
  - Audio (play/pause, seek, time, lightweight waveform)
  - Office files external-open only
  - Video optional external-open fallback
- History button + hidden history panel
- Automatic compare-log save on compare execution
- Automatic CSV export save on compare execution (`compare_exports`)
- Compare confirmation when current root state is unsaved:
  - Save and Compare
  - Compare Without Saving
  - Cancel
- Compare requires at least two snapshots and distinct Base/Compare selection
- Preview pane can be collapsed/reopened from the pane-local header control
- App settings:
  - Language: Japanese / English
  - UI text size: Small / Medium / Large
  - Preview cache generations
  - Preview cache total size cap
  - Preview cache target extensions
- External folder snapshot import is available from project `...` menu
- Project menu includes quick-open for compare CSV export folder
- Keyboard shortcuts:
  - `Ctrl+Enter` Compare
  - `Ctrl+S` Save Snapshot
  - `Ctrl+H` Toggle History
  - `Ctrl+F` Focus diff search
  - `Esc` Collapse preview pane
  - `Ctrl+0` reset text size, `Ctrl+=` larger text, `Ctrl+-` smaller text

## Snapshot Metadata vs Preview Cache

- Snapshots are metadata-first and lightweight:
  - relative path
  - file size
  - modified time
  - snapshot created time
- Full folder copies are not stored per snapshot.
- Preview cache is independent from snapshot metadata.
- Preview cache stores preview-target files with content-hash dedupe.
- Cache retention is pruned automatically by:
  - max generations
  - max total cache size

## Data location

- Default app data directory:
  - Windows: `%USERPROFILE%\\AppData\\Local\\ReCheck`
- Override with:
  - `RECHECK_DATA_DIR`

## Smoke Validation

The implementation was validated locally with offscreen smoke checks for:
- lightweight snapshot creation
- preview cache creation and pruning
- project-menu external folder snapshot import workflow
- new-project reset state (Base/Compare/results/preview) and post-create guidance
- compare branches (save/without-save/cancel) and insufficient-snapshot guidance
- preview pipeline across image/text/PDF/audio/unsupported cases
- language switching (Japanese/English)
- audio waveform sample generation
- PDF first-page preview path and fallback path
- pane-local preview collapse/reopen behavior
