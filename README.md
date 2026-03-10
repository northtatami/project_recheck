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
  - Diff list table with sortable columns
- Preview pane (side-by-side Base vs Compare):
  - Image
  - Text
  - PDF (Qt PDF module when available)
  - Audio (play/pause, seek, time)
  - Office files external-open only
  - Video optional external-open fallback
- History button + hidden history panel
- Automatic compare-log save on compare execution

## Data location

- Default app data directory:
  - Windows: `%USERPROFILE%\\AppData\\Local\\ReCheck`
- Override with:
  - `RECHECK_DATA_DIR`
