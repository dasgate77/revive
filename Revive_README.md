# Revive

Revive is a lightweight Python/Tkinter application for recording handwritten annotations over PDF pages and replaying them later.

## Current Features

- Open and display a multi-page PDF as the canvas background.
- Navigate between PDF pages.
- Draw handwritten annotations with the mouse.
- Keep annotations associated with their individual PDF pages.
- Record PDF page-navigation events.
- Replay the recorded annotation activity.
- Preserve annotations when moving between PDF pages.
- Page-specific annotation replay:
  - Page 1 shows only annotations belonging to Page 1.
  - Page 2 shows only annotations belonging to Page 2.
  - And so on.
- Record timestamps for annotation points and page changes.
- Save recordings as JSON.
- Load previously saved JSON recordings.
- Continue an existing recording.
- Erase individual annotation strokes.
- Playback speed controls.
- Ramer-Douglas-Peucker (RDP) stroke simplification when saving.

## RDP Simplification

RDP is used to reduce the number of points stored in the JSON file while preserving the overall shape of handwritten strokes.

The recording itself is not modified in memory. Simplification is applied when the recording is converted to JSON for saving.

### Available RDP Modes

| Mode | RDP Epsilon | Purpose |
|---|---:|---|
| Raw recording | 0.0 | Preserve every recorded point |
| Presentable | 1.0 | Light simplification |
| Academic quality | 1.5 | Balanced simplification |
| Underrated | 3.0 | Strong simplification |

The selected option is shown with a check mark in the Playback menu.

### Important

`Raw recording` is explicitly treated as a no-simplification mode. It preserves the original recorded points.

RDP does not simplify:

- PDF page-change events
- Erase events
- Other non-drawing events

Only `draw` strokes are simplified.

## Recording Model

A recording consists of events called `Stroke` objects.

Each stroke can have one of these actions:

- `draw`
- `erase`
- `page`

A drawing stroke contains:

- Unique stroke ID
- PDF page index
- X/Y coordinates
- Timestamp for every recorded point

A page event contains:

- Unique event ID
- PDF page index
- Timestamp

An erase event contains:

- Unique event ID
- Target stroke ID
- Timestamp

## Page-Based Annotation Behavior

Annotations belong to the PDF page on which they were created.

For example:

```text
Page 1
    A
    B

Page 2
    C
    D
```

When the user is viewing Page 1, only A and B are displayed.

When the user is viewing Page 2, only C and D are displayed.

Changing pages does not delete annotations. The annotations remain stored in the recording and are shown again when returning to their page.

## Page Navigation Recording

When recording is active, changing the PDF page creates a `page` event.

The event stores the destination page and its timestamp.

This allows the replay system to reproduce page navigation as part of the recording.

Page navigation performed before the recording has started is not recorded.

## Timestamps

Timestamps are recorded using the recording's monotonic clock.

Drawing points have their own timestamps.

Page changes also have timestamps.

This allows the replay system to reproduce the timing of the original activity.

For page-specific recording/replay, annotations remain associated with their respective PDF pages while their original event timing is retained.

## JSON Structure

A saved recording follows this general structure:

```json
{
  "title": "Example",
  "strokes": [
    {
      "id": 1,
      "action": "page",
      "target_id": null,
      "page_index": 0,
      "points": [
        {
          "x": 0,
          "y": 0,
          "time": 0.0
        }
      ]
    },
    {
      "id": 2,
      "action": "draw",
      "target_id": null,
      "page_index": 0,
      "points": [
        {
          "x": 100,
          "y": 120,
          "time": 0.02
        }
      ]
    }
  ]
}
```

The exact number of points depends on the recording and the selected RDP simplification mode at save time.

## Replay

Selecting:

**Playback → ▶ Revive**

starts replay.

The replay system:

1. Starts from the beginning of the recorded event sequence.
2. Reproduces page changes at their recorded timestamps.
3. Displays annotations on their associated PDF pages.
4. Replays drawing points according to their timestamps.
5. Applies recorded erase events.
6. Uses the selected playback speed.

Available playback speeds include:

- 0.25×
- 0.5×
- 1×
- 1.5×
- 2×
- 4×

The active speed is displayed with a check mark.

## RDP vs Recording Frequency

The application currently records normal mouse motion events and uses RDP as a post-processing step when saving.

This means RDP does not change how the user draws.

Conceptually:

```text
Mouse movement
      ↓
Raw recording
      ↓
Individual strokes
      ↓
RDP simplification
      ↓
JSON
      ↓
Load
      ↓
Replay
```

This approach keeps the recording behavior independent from JSON compression.

## Basic Workflow

### 1. Start the application

Run the Python application.

### 2. Open a PDF

Use:

**View → Open Background PDF...**

### 3. Start drawing

Draw on the current PDF page.

The first drawing starts the recording timer and records the initial page.

### 4. Navigate

Use the PDF page navigation buttons.

When recording is active, page changes are recorded.

### 5. Annotate additional pages

Move to another page and draw.

Each stroke is associated with that page.

### 6. Select RDP mode

Use:

**Playback → RDP Simplification**

Choose one:

- Raw recording
- Presentable
- Academic quality
- Underrated

The selected option has a `✓`.

### 7. Save

Use:

**File → Save**

or:

**File → Save As...**

RDP simplification is applied during JSON generation.

### 8. Replay

Use:

**Playback → ▶ Revive**

The PDF pages and annotations are replayed according to the recording.

## Recommended RDP Mode

For normal use:

**Academic quality — RDP 1.5**

is the recommended starting point.

Use:

- **Raw recording** when maximum fidelity is required.
- **Presentable** for light compression.
- **Academic quality** for a balance between fidelity and file size.
- **Underrated** when aggressive point reduction is desired.

## Dependencies

The application currently uses:

- Python 3
- Tkinter
- Pillow
- PyMuPDF

Typical imports include:

```python
import tkinter as tk
from PIL import Image, ImageTk
import pymupdf
import time
import json
```

## Notes

- RDP epsilon is measured in canvas-coordinate distance.
- Larger epsilon values generally remove more points.
- Very large epsilon values can remove meaningful handwriting detail.
- RDP should be evaluated visually with representative handwriting before choosing a mode for important recordings.
- Page events and erase events are preserved independently of RDP.
