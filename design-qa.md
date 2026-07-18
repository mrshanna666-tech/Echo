**Design QA — Memory Replay**

- Source visual truth: local reference capture excluded from version control (Figma frame `5:2`)
- Implementation screenshot: local QA artifact excluded from version control
- Side-by-side comparison: local QA artifact excluded from version control
- Viewport: 1440 × 900, Windows desktop, Memory page, current local data

**Findings**

- No actionable P0/P1/P2 mismatch remains.
- Fonts and typography: native Windows Chinese UI font is used in the implementation instead of Figma's Noto Sans. Weight, hierarchy, wrapping, and readability remain equivalent; this is an acceptable platform-native substitution.
- Spacing and layout rhythm: header, replay picker, two-column split, card density, radii, and control spacing closely match the reference. Existing Echo sidebar width and brand treatment are intentionally preserved.
- Colors and visual tokens: warm canvas, cream cards, green privacy/story surfaces, orange metadata, and border contrast match the source direction.
- Image quality and asset fidelity: the source contains no raster imagery, illustrations, or custom icons requiring replacement.
- Copy and content: all reference sections are present; sample text is replaced with real local ActivityWatch and note data as intended.

**Interaction Verification**

- Date and time inputs are accessible and editable.
- Start replay rebuilds the ±30-minute context.
- Fragment cards switch the selected date/time.
- Favorite, expand-window, continue, and earlier-memory actions are wired.
- Accessibility tree exposes the page title, controls, fragment content, replay narrative, and actions.
- Python test suite: 10 tests passed.

**Comparison History**

- Pass 1: offscreen Qt capture showed false black/blank regions caused by rendering hidden overlay graphics effects into a painter target.
- Fix: validated through Windows.Graphics.Capture on the real application window; the artifact is absent. Added fixed upper bounds to story and note cards to preserve the reference density.
- Pass 2: side-by-side comparison found no remaining actionable P0/P1/P2 visual differences.

**Focused Region Comparison**

- Header/picker, memory cards, story block, application trail, note block, and action row are readable in the 1440 × 900 side-by-side image, so separate crops were not required.

**Follow-up Polish**

- P3: optionally rename the existing sidebar item from “Memory” to “记忆” for full language consistency.

final result: passed

**Window Drag Regression**

- Reproduced the Windows blank/frozen surface while moving the native window.
- Removed transient graphics effects from hidden drawers and disabled opacity-based page/entry animation on Windows.
- Verified the application remains fully painted after title-bar dragging; Python test suite remains at 10/10 passing.
