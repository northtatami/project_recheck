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
- Base/Compare direct folder pick (creates and assigns snapshots immediately)
- Scope pane:
  - Whole
  - Selected folder
  - Multiple folders
- Diff Results pane:
  - Added/Removed/Modified/Unchanged summary cards
  - Search by filename and relative path
  - Diff list table with sortable columns
- Preview pane (side-by-side Base vs Compare):
  - Image
  - Text
  - PDF first-page preview with external-open fallback
  - Audio (play/pause, seek, time, lightweight waveform)
  - Office files external-open only
  - Video optional external-open fallback
- History button + hidden history panel
- Automatic compare-log save on compare execution
- App settings:
  - Language: Japanese / English
  - Preview cache generations
  - Preview cache total size cap
  - Preview cache target extensions

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
- Base/Compare folder-pick workflow
- language switching (Japanese/English)
- audio waveform sample generation
- PDF first-page preview path and fallback index path
