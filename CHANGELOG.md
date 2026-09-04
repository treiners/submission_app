# Changelog

## v1.5.0 (2026-09-04)

### Added
- Release-ready version bump for the current stable submission and marking workflow
- Clearer version tracking in the public form metadata for release confirmation
- Documentation update to reflect the current shipped configuration and release notes

### Changed
- Standardised the app version metadata to the latest release value in configuration and docs
- Refined the release documentation to better match the current admin/marking workflow

### Fixed
- No functional code changes in this release; this is a release packaging and documentation update for the current stable build

## v1.4.0 (2026-09-02)

### Added
- Active marking template selection now drives marking questions from `active_template.json`
- Report-first default preview in the right pane, with selectable video playback for Q1 uploads
- Dedicated video preview endpoint that streams media directly in the marking pane

### Changed
- Question headers now show the prompt inline after the question number
- Answer text now strips question marker tags from rendered marking output
- Image attachment is tag-aware and no longer falls back to prompt matching when tags are present
- Marking completion now requires both score and feedback
- Score inputs default to the question max score when available
- Template mode status was compacted into a single header row

### Fixed
- Video preview playback now uses an explicit media MIME type and direct streaming endpoint
- Missing `mimetypes` import in the video preview route

## v1.3.2 (2026-09-01)

### Added
- PDF-first document preview in marking view
- DOCX preview fallback selector in marking view
- DOCX-to-PDF converter option `dxpdf`
- Dashboard column sorting
- Keyboard navigation shortcuts (`n`/`p`)
- Empty-dashboard worksheet template upload flow
- Marker parser for worksheet tags and `active_template.json` scaffold
- Question-scoped area mapping (`question`/`questions`) for marking context
- Q1-linked video submission area with common video formats and 400MB/file limit

### Changed
- Two-pane marking workspace (left marking, right document)
- Draggable pane divider with saved width
- Header navigation moved to top controls
- Re-extract button moved into header action row
- Per-student answers split into one card per question
- Template folder renamed from making_template to marking_template
- Dashboard now shows detailed template validation errors when upload is blocked
- Submission form now captures first and last name separately
- Upload hard ceiling now auto-scales from configured area file-size limits

### Fixed
- Split-pane layout nesting bug affecting both review modes
- Invalid nested forms in marking cards (undo action)
- Independent left/right pane scrolling
- Full-height PDF viewer in right pane
- Desktop split-view breakpoint behavior
