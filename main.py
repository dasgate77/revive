import tkinter as tk
from PIL import Image, ImageTk
import pymupdf
import time
import json
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, simpledialog, messagebox


# ==================================================
# Data model
# ==================================================

@dataclass
class StrokePoint:
    x: float
    y: float
    time: float


@dataclass
class Stroke:
    points: list[StrokePoint] = field(default_factory=list)

    # "draw", "erase", or "page"
    action: str = "draw"

    stroke_id: int = 0

    target_id: int | None = None

    # PDF page number for page-change events
    page_index: int | None = None


@dataclass
class Recording:
    title: str
    strokes: list[Stroke] = field(default_factory=list)

# ==================================================
# Ramer-Douglas-Peucker stroke simplification
# ==================================================

def perpendicular_distance(point, start, end):

    x = point.x
    y = point.y

    x1 = start.x
    y1 = start.y

    x2 = end.x
    y2 = end.y

    dx = x2 - x1
    dy = y2 - y1

    # Start and end are the same point.
    if dx == 0 and dy == 0:

        return (
            (x - x1) ** 2 +
            (y - y1) ** 2
        ) ** 0.5

    numerator = abs(
        dy * x
        - dx * y
        + x2 * y1
        - y2 * x1
    )

    denominator = (
        dx ** 2 +
        dy ** 2
    ) ** 0.5

    return numerator / denominator


def rdp_simplify(points, epsilon=1.5):

    if len(points) <= 2:
        return points[:]

    start = points[0]
    end = points[-1]

    max_distance = 0
    max_index = 0

    for i in range(1, len(points) - 1):

        distance = perpendicular_distance(
            points[i],
            start,
            end
        )

        if distance > max_distance:

            max_distance = distance
            max_index = i

    # No meaningful deviation from the straight line.
    if max_distance <= epsilon:

        return [
            start,
            end
        ]

    left_points = rdp_simplify(
        points[:max_index + 1],
        epsilon
    )

    right_points = rdp_simplify(
        points[max_index:],
        epsilon
    )

    # The first point of right_points is already
    # present as the last point of left_points.
    return (
        left_points[:-1]
        + right_points
    )

# ==================================================
# Recording compression settings
# ==================================================

# ==================================================
# RDP Simplification
# ==================================================

RDP_EPSILON = 1.5

rdp_options = {
    "Raw recording": 0.0,
    "Presentable": 1.0,
    "Academic quality": 1.5,
    "Underrated": 3.0
}

selected_rdp_name = "Academic quality"

# ==================================================
# Application state
# ==================================================

recording = Recording(
    title="Untitled"
)

current_stroke = None

last_x = None
last_y = None

recording_start_time = None

# Next unique ID for a recorded event
next_stroke_id = 1

# File currently associated with the recording
current_file = None

# True when user is allowed to draw
recording_enabled = True

eraser_mode = False
eraser_seen_strokes = set()

# Background image
background_image = None
background_image_path = None
background_image_original = None

# Page on which the recording started
recording_initial_page = None

# PDF navigation state
pdf_document = None
pdf_page_index = 0
pdf_page_count = 0

# Background PDF
background_pdf = None
background_pdf_path = None
background_pdf_page = 0

# Replay state
replaying = False
replay_start_time = None
replay_stroke_index = 0
replay_point_index = 0
playback_speed = 1.0

# PDF page currently being revived
replay_page = None

# Time offset for the selected page
replay_time_offset = 0.0

# Canvas objects belonging to each stroke during replay
replay_canvas_objects = {}

# ==================================================
# Custom tool cursor
# ==================================================

tool_cursor_item = None

def update_tool_cursor(event=None):

    global tool_cursor_item

    # Remove previous custom cursor
    if tool_cursor_item is not None:
        canvas.delete(tool_cursor_item)
        tool_cursor_item = None

    if eraser_mode:
        cursor_text = "○"
    else:
        cursor_text = "."

    # Get mouse position
    if event is not None:
        x = event.x
        y = event.y
    else:
        x = canvas.winfo_pointerx() - canvas.winfo_rootx()
        y = canvas.winfo_pointery() - canvas.winfo_rooty()

    # The tip of "<" is approximately at its right point.
    # Therefore position that point at the actual mouse location.
    tool_cursor_item = canvas.create_text(
        x,
        y - 8,
        text=cursor_text,
        font=("Arial", 26, "bold"),
        fill="black",
        anchor="center",
        tags="tool_cursor"
    )

    # Keep cursor itself unobtrusive.
    canvas.config(
        cursor="none"
    )

def update_pdf_navigation():

    if background_pdf is None:

        pdf_page_label.config(
            text="Page - / -"
        )

        previous_page_button.config(
            state=tk.DISABLED
        )

        next_page_button.config(
            state=tk.DISABLED
        )

        return

    total_pages = len(
        background_pdf
    )

    current_page = (
        background_pdf_page + 1
    )

    pdf_page_label.config(
        text=(
            f"Page {current_page}"
            f" / "
            f"{total_pages}"
        )
    )

    if background_pdf_page <= 0:

        previous_page_button.config(
            state=tk.DISABLED
        )

    else:

        previous_page_button.config(
            state=tk.NORMAL
        )

    if background_pdf_page >= total_pages - 1:

        next_page_button.config(
            state=tk.DISABLED
        )

    else:

        next_page_button.config(
            state=tk.NORMAL
        )

def previous_pdf_page():

    global background_pdf_page

    if background_pdf is None:
        return

    if background_pdf_page <= 0:
        return

    background_pdf_page -= 1

    record_page_change()

    render_pdf_page()

    update_pdf_navigation()

def next_pdf_page():

    global background_pdf_page

    if background_pdf is None:
        return

    if background_pdf_page >= len(background_pdf) - 1:
        return

    background_pdf_page += 1

    record_page_change()

    render_pdf_page()

    update_pdf_navigation()

def record_page_change():

    global next_stroke_id

    # --------------------------------------------------
    # If recording has not started yet, page navigation
    # is just normal browsing.
    # --------------------------------------------------

    if recording_start_time is None:
        return

    timestamp = (
        time.monotonic()
        - recording_start_time
    )

    page_event = Stroke(
        action="page",
        stroke_id=next_stroke_id,
        page_index=background_pdf_page
    )

    next_stroke_id += 1

    page_event.points.append(
        StrokePoint(
            x=0,
            y=0,
            time=timestamp
        )
    )

    recording.strokes.append(
        page_event
    )

    update_time_display(
        timestamp
    )

    print(
        "PAGE:",
        "page =", background_pdf_page + 1,
        "time =", round(timestamp, 2)
    )
# ==================================================
# GUI
# ==================================================

root = tk.Tk()

root.title("Revive")

root.geometry("1000x700")

canvas = tk.Canvas(
    root,
    bg="white"
)

canvas.pack(
    fill=tk.BOTH,
    expand=True
)

status_frame = tk.Frame(root)

status_frame.pack(
    fill=tk.X
)

# ==================================================
# PDF page navigation
# ==================================================

pdf_navigation_frame = tk.Frame(
    status_frame
)

pdf_navigation_frame.pack(
    side=tk.LEFT,
    padx=10
)


previous_page_button = tk.Button(
    pdf_navigation_frame,
    text="←",
    width=3,
    command=previous_pdf_page
)

previous_page_button.pack(
    side=tk.LEFT
)


pdf_page_label = tk.Label(
    pdf_navigation_frame,
    text="Page - / -"
)

pdf_page_label.pack(
    side=tk.LEFT,
    padx=5
)


next_page_button = tk.Button(
    pdf_navigation_frame,
    text="→",
    width=3,
    command=next_pdf_page
)

next_page_button.pack(
    side=tk.LEFT
)

title_label = tk.Label(
    status_frame,
    text="Untitled",
    anchor="w"
)

title_label.pack(
    side=tk.LEFT,
    padx=10,
    pady=5
)


time_label = tk.Label(
    status_frame,
    text="00:00 / 00:00",
    anchor="e"
)

time_label.pack(
    side=tk.RIGHT,
    padx=10,
    pady=5
)

# ==================================================
# Draw existing recording on canvas
# ==================================================

def draw_recording():

    canvas.delete("all")

    # --------------------------------------------------
    # Draw current background
    # --------------------------------------------------

    if background_image is not None:

        canvas.create_image(
            0,
            0,
            image=background_image,
            anchor="nw",
            tags="background"
        )

    # --------------------------------------------------
    # Find all strokes that have been erased.
    # --------------------------------------------------

    erased_strokes = set()

    for stroke in recording.strokes:

        if stroke.action == "erase":

            if stroke.target_id is not None:

                erased_strokes.add(
                    stroke.target_id
                )

    # --------------------------------------------------
    # Draw annotations.
    # --------------------------------------------------

    for stroke in recording.strokes:

        if stroke.action != "draw":
            continue

        if stroke.stroke_id in erased_strokes:
            continue

        # --------------------------------------------------
        # If this is a PDF recording, only draw strokes
        # belonging to the currently visible page.
        # --------------------------------------------------

        if background_pdf is not None:

            if stroke.page_index != background_pdf_page:
                continue

        if len(stroke.points) < 2:
            continue

        for i in range(1, len(stroke.points)):

            previous = stroke.points[i - 1]
            point = stroke.points[i]

            canvas.create_line(
                previous.x,
                previous.y,
                point.x,
                point.y,
                fill="black",
                width=3,
                capstyle=tk.ROUND,
                smooth=True
            )


# ==================================================
# New recording
# ==================================================

def new_recording():

    global recording
    global current_stroke
    global last_x
    global last_y
    global recording_start_time
    global page_start_time
    global current_file
    global recording_enabled
    global replaying
    global next_stroke_id
    global recording_initial_page

    global background_pdf
    global background_pdf_path
    global background_pdf_page
    global background_image
    global background_image_original
    global background_image_path

    # --------------------------------------------------
    # Stop replay
    # --------------------------------------------------

    replaying = False

    # --------------------------------------------------
    # Reset recording
    # --------------------------------------------------

    recording = Recording(
        title="Untitled"
    )

    current_stroke = None

    last_x = None
    last_y = None

    recording_start_time = None
    page_start_time = None

    next_stroke_id = 1

    current_file = None

    recording_enabled = True

    recording_initial_page = None

    # --------------------------------------------------
    # Close the currently loaded PDF
    # --------------------------------------------------

    if background_pdf is not None:

        background_pdf.close()

    background_pdf = None
    background_pdf_path = None
    background_pdf_page = 0

    # --------------------------------------------------
    # Clear background image too
    # --------------------------------------------------

    background_image = None
    background_image_original = None
    background_image_path = None

    # --------------------------------------------------
    # Clear canvas completely
    # --------------------------------------------------

    canvas.delete("all")

    # --------------------------------------------------
    # Reset PDF navigation
    # --------------------------------------------------

    update_pdf_navigation()

    # --------------------------------------------------
    # Reset time/title
    # --------------------------------------------------

    update_time_display(0)

    update_title()


# ==================================================
# Start drawing
# ==================================================
def point_to_segment_distance(
    px,
    py,
    x1,
    y1,
    x2,
    y2
):

    dx = x2 - x1
    dy = y2 - y1

    if dx == 0 and dy == 0:

        return (
            (px - x1) ** 2 +
            (py - y1) ** 2
        ) ** 0.5

    t = (
        (px - x1) * dx +
        (py - y1) * dy
    ) / (
        dx * dx +
        dy * dy
    )

    t = max(
        0,
        min(1, t)
    )

    closest_x = x1 + t * dx
    closest_y = y1 + t * dy

    return (
        (px - closest_x) ** 2 +
        (py - closest_y) ** 2
    ) ** 0.5
    
def find_stroke_at(x, y):

    threshold = 8

    for stroke_index, stroke in enumerate(recording.strokes):

        if stroke.action != "draw":
            continue

        # --------------------------------------------------
        # Only search annotations on the current PDF page.
        # --------------------------------------------------

        if background_pdf is not None:

            if stroke.page_index != background_pdf_page:
                continue

        for i in range(1, len(stroke.points)):

            p1 = stroke.points[i - 1]
            p2 = stroke.points[i]

            distance = point_to_segment_distance(
                x,
                y,
                p1.x,
                p1.y,
                p2.x,
                p2.y
            )

            if distance <= threshold:
                return stroke_index

    return None
    
def start_stroke(event):

    global current_stroke
    global last_x
    global last_y
    global recording_start_time
    global next_stroke_id
    global recording_initial_page

    if replaying:
        return

    if not recording_enabled:
        return

    if eraser_mode:

        eraser_seen_strokes.clear()
    
        delete_stroke_at(
            event.x,
            event.y
        )
    
        return

    # Start timer when first new stroke begins.
    if recording_start_time is None:
    
        recording_start_time = time.monotonic()
    
        # --------------------------------------------------
        # Record the PDF page on which the recording began.
        # --------------------------------------------------
    
        if background_pdf is not None:
    
            recording_initial_page = (
                background_pdf_page
            )
    
            initial_page_event = Stroke(
                action="page",
                stroke_id=next_stroke_id,
                page_index=background_pdf_page
            )
    
            next_stroke_id += 1
    
            initial_page_event.points.append(
                StrokePoint(
                    x=0,
                    y=0,
                    time=0.0
                )
            )
    
            recording.strokes.append(
                initial_page_event
            )
    
            print(
                "INITIAL PAGE:",
                background_pdf_page + 1
            )

    current_stroke = Stroke(
        action="draw",
        stroke_id=next_stroke_id,
        page_index=background_pdf_page
            if background_pdf is not None
            else None
    )

    next_stroke_id += 1

    timestamp = (
        time.monotonic()
        - recording_start_time
    )
    
    update_time_display(
        timestamp
    )

    current_stroke.points.append(
        StrokePoint(
            x=event.x,
            y=event.y,
            time=timestamp
        )
    )

    last_x = event.x
    last_y = event.y

def delete_stroke_at(x, y):

    global next_stroke_id
    global eraser_seen_strokes

    stroke_index = find_stroke_at(
        x,
        y
    )

    if stroke_index is None:
        return
    
    target_stroke = recording.strokes[
        stroke_index
    ]
    
    # Only normal drawing strokes can be erased.
    if target_stroke.action != "draw":
        return
    
    # Don't erase the same stroke twice
    # during one continuous eraser drag.
    if target_stroke.stroke_id in eraser_seen_strokes:
        return
    
    eraser_seen_strokes.add(
        target_stroke.stroke_id
    )

    # Make sure the recording timer exists.
    if recording_start_time is None:
        return

    # Current time in the recording.
    timestamp = (
        time.monotonic()
        - recording_start_time
    )

    # Create an ERASE event.
    erase_event = Stroke(
        action="erase",
        stroke_id=next_stroke_id,
        target_id=target_stroke.stroke_id
    )

    next_stroke_id += 1

    # Store the time of the erase event
    # as its first point.
    erase_event.points.append(
        StrokePoint(
            x=x,
            y=y,
            time=timestamp
        )
    )
    print(
        "ERASE:",
        "target =", target_stroke.stroke_id,
        "time =", round(timestamp, 2)
    )

    recording.strokes.append(
        erase_event
    )

    draw_recording()

    update_title()
# ==================================================
# Continue drawing
# ==================================================

def draw(event):

    global last_x
    global last_y

    if replaying:
        return

    if not recording_enabled:
        return
    
    if eraser_mode:

        delete_stroke_at(
            event.x,
            event.y
        )
    
        return
        
    if current_stroke is None:
        return

    canvas.create_line(
        last_x,
        last_y,
        event.x,
        event.y,
        fill="black",
        width=3,
        capstyle=tk.ROUND,
        smooth=True
    )

    timestamp = (
        time.monotonic()
        - recording_start_time
    )
    
    update_time_display(
        timestamp
    )

    current_stroke.points.append(
        StrokePoint(
            x=event.x,
            y=event.y,
            time=timestamp
        )
    )

    last_x = event.x
    last_y = event.y


# ==================================================
# Finish stroke
# ==================================================

def end_stroke(event):

    global current_stroke
    global last_x
    global last_y

    if replaying:
        return

    if not recording_enabled:
        return
    
    if eraser_mode:
        return
    
    if current_stroke is not None:

        recording.strokes.append(
            current_stroke
        )

    current_stroke = None

    last_x = None
    last_y = None

def simplify_stroke(stroke):

    # Only simplify drawing strokes.
    if stroke.action != "draw":
        return stroke

    # Nothing to simplify.
    if len(stroke.points) <= 2:
        return stroke

    original_count = len(
        stroke.points
    )

    simplified_points = rdp_simplify(
        stroke.points,
        RDP_EPSILON
    )

    print(
        "RDP:",
        "stroke =", stroke.stroke_id,
        "original =", original_count,
        "simplified =", len(simplified_points)
    )

    return Stroke(
        points=simplified_points,
        action=stroke.action,
        stroke_id=stroke.stroke_id,
        target_id=stroke.target_id,
        page_index=stroke.page_index
    )
    
# ==================================================
# Convert recording to dictionary
# ==================================================

def recording_to_dict():

    simplified_strokes = []

    for stroke in recording.strokes:

        simplified_stroke = simplify_stroke(
            stroke
        )

        simplified_strokes.append(
            simplified_stroke
        )

    return {
        "title": recording.title,

        "strokes": [

            {
                "id": stroke.stroke_id,

                "action": stroke.action,

                "target_id": stroke.target_id,

                "page_index": stroke.page_index,

                "points": [

                    {
                        "x": point.x,
                        "y": point.y,
                        "time": point.time
                    }

                    for point in stroke.points
                ]
            }

            for stroke in simplified_strokes
        ]
    }


# ==================================================
# Save As
# ==================================================

def save_as():

    global current_file

    if not recording.strokes:

        messagebox.showwarning(
            "Nothing to save",
            "There is no recording to save."
        )

        return

    filepath = filedialog.asksaveasfilename(

        title="Save Revive Recording As",

        defaultextension=".json",

        filetypes=[
            ("Revive recordings", "*.json")
        ]
    )

    if not filepath:
        return

    current_file = Path(filepath)

    # Use the filename (without .json) as the title
    recording.title = current_file.stem

    save_to_file()

    update_title()


# ==================================================
# Save
# ==================================================

def save_recording():

    if not recording.strokes:

        messagebox.showwarning(
            "Nothing to save",
            "There is no recording to save."
        )

        return

    if current_file is None:

        save_as()

        return

    save_to_file()


# ==================================================
# Actually write JSON file
# ==================================================

def save_to_file():

    with open(
        current_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            recording_to_dict(),
            file,
            indent=2
        )

    messagebox.showinfo(
        "Saved",
        f"Recording saved to:\n{current_file}"
    )


# ==================================================
# Load recording
# ==================================================

def load_recording():

    global recording
    global current_file
    global recording_start_time
    global recording_enabled
    global current_stroke
    global replaying
    global next_stroke_id

    filepath = filedialog.askopenfilename(

        title="Open Revive Recording",

        filetypes=[
            ("Revive recordings", "*.json")
        ]
    )

    if not filepath:
        return

    try:

        with open(
            filepath,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

    except Exception as error:

        messagebox.showerror(
            "Could not open recording",
            str(error)
        )

        return

    if (
        "title" not in data
        or "strokes" not in data
    ):

        messagebox.showerror(
            "Invalid recording",
            "This is not a valid Revive recording."
        )

        return

    loaded_strokes = []

    highest_stroke_id = 0
    
    for stroke_data in data["strokes"]:

    	stroke_id = stroke_data.get(
        	"id",
        	len(loaded_strokes) + 1
    	)
	
    	action = stroke_data.get(
        	"action",
        	"draw"
    	)
	
    	target_id = stroke_data.get(
        	"target_id",
        	None
    	)
	
    	page_index = stroke_data.get(
        	"page_index",
        	None
    	)
	
    	stroke = Stroke(
        	action=action,
        	stroke_id=stroke_id,
        	target_id=target_id,
        	page_index=page_index
    	)
	
    	for point_data in stroke_data["points"]:
	
        	stroke.points.append(
            	StrokePoint(
                	x=point_data["x"],
                	y=point_data["y"],
                	time=point_data["time"]
            	)
        	)
	
    	loaded_strokes.append(stroke)
	
    	highest_stroke_id = max(
        	highest_stroke_id,
        	stroke_id
    	)

    recording = Recording(
        title=data["title"],
        strokes=loaded_strokes
    )
    
    next_stroke_id = highest_stroke_id + 1

    current_file = Path(filepath)

    # Do not allow drawing immediately after Load.
    recording_enabled = False

    current_stroke = None

    recording_start_time = None

    replaying = False

    draw_recording()

    update_title()


# ==================================================
# Continue recording
# ==================================================

def continue_recording():

    global recording_enabled
    global recording_start_time

    if not recording.strokes:

        messagebox.showwarning(
            "Nothing loaded",
            "Load a recording first."
        )

        return

    # Find the last timestamp in the recording.
    last_time = 0.0

    for stroke in recording.strokes:

        if stroke.points:

            stroke_last_time = (
                stroke.points[-1].time
            )

            last_time = max(
                last_time,
                stroke_last_time
            )

    # We need the new strokes to continue
    # after the old recording.

    recording_start_time = (
        time.monotonic() - last_time
    )

    recording_enabled = True

    messagebox.showinfo(
        "Continue Recording",
        "You can now add new strokes."
    )


# ==================================================
# Replay
# ==================================================

def clear_replay_annotations():

    global replay_canvas_objects

    for canvas_ids in replay_canvas_objects.values():

        for canvas_id in canvas_ids:

            canvas.delete(
                canvas_id
            )

    replay_canvas_objects = {}
    
def start_replay():

    global replay_start_time
    global replay_stroke_index
    global replay_point_index
    global replaying
    global recording_enabled
    global replay_canvas_objects
    global replay_page
    global replay_time_offset

    if not recording.strokes:

        messagebox.showwarning(
            "Nothing to replay",
            "There is no recording."
        )

        return

    # --------------------------------------------------
    # Remember the page currently visible.
    # --------------------------------------------------

    if background_pdf is not None:

        replay_page = background_pdf_page

    else:

        replay_page = None

    # --------------------------------------------------
    # Find the first annotation time on this page.
    #
    # Example:
    #
    # Page 1:
    #   A = 1.0
    #   B = 2.0
    #
    # Page 2:
    #   C = 6.0
    #   D = 7.0
    #
    # If we revive page 2, replay should start
    # from C immediately, not wait 6 seconds.
    # --------------------------------------------------

    replay_time_offset = 0.0

    if background_pdf is not None:

        page_times = []

        for stroke in recording.strokes:

            if (
                stroke.action == "draw"
                and stroke.page_index == replay_page
                and stroke.points
            ):

                page_times.append(
                    stroke.points[0].time
                )

        if page_times:

            replay_time_offset = min(
                page_times
            )

    # --------------------------------------------------
    # Disable drawing while replaying.
    # --------------------------------------------------

    recording_enabled = False

    replaying = True

    # --------------------------------------------------
    # Clear only the annotations currently visible
    # on the canvas.
    #
    # The recording itself is NOT modified.
    # --------------------------------------------------

    canvas.delete("all")

    draw_background_only()

    replay_canvas_objects = {}

    # --------------------------------------------------
    # Start the replay clock.
    # --------------------------------------------------

    replay_start_time = time.monotonic()

    replay_stroke_index = 0

    replay_point_index = 0

    replay_step()

# ==================================================
# Replay engine
# ==================================================

def replay_step():

    global replay_stroke_index
    global replay_point_index
    global replaying

    if not replaying:
        return

    # --------------------------------------------------
    # Calculate replay time.
    # --------------------------------------------------

    elapsed = (
        time.monotonic()
        - replay_start_time
    ) * playback_speed

    # The recording timestamps are global.
    #
    # For example:
    #
    # Page 1: A = 1 sec, B = 2 sec
    # Page 2: C = 6 sec, D = 7 sec
    #
    # If replaying page 2, we shift the clock by
    # 6 seconds so C happens immediately.
    # --------------------------------------------------

    if background_pdf is not None:

        elapsed += replay_time_offset

    update_time_display(
        elapsed - replay_time_offset
    )

    # --------------------------------------------------
    # Process recorded events.
    # --------------------------------------------------

    while replay_stroke_index < len(
        recording.strokes
    ):

        stroke = recording.strokes[
            replay_stroke_index
        ]

        # ==================================================
        # PAGE EVENT
        # ==================================================

        if stroke.action == "page":

            # --------------------------------------------------
            # IMPORTANT:
            #
            # During "Revive Current Page", page events are
            # NOT executed.
            #
            # We keep them in the recording because they will
            # be useful for "Revive Entire Recording" later.
            # --------------------------------------------------

            replay_stroke_index += 1

            replay_point_index = 0

            continue

        # ==================================================
        # ERASE EVENT
        # ==================================================

        if stroke.action == "erase":

            if not stroke.points:

                replay_stroke_index += 1

                replay_point_index = 0

                continue

            erase_time = stroke.points[0].time

            # This erase has not happened yet.

            if erase_time > elapsed:

                break

            target_id = stroke.target_id

            # --------------------------------------------------
            # Find the stroke that this erase belongs to.
            # --------------------------------------------------

            target_stroke = None

            if target_id is not None:

                for candidate in recording.strokes:

                    if (
                        candidate.stroke_id
                        == target_id
                    ):

                        target_stroke = candidate

                        break

            # --------------------------------------------------
            # Only replay erasures belonging to the
            # current page.
            # --------------------------------------------------

            if (
                background_pdf is not None
                and target_stroke is not None
                and target_stroke.page_index != replay_page
            ):

                replay_stroke_index += 1

                replay_point_index = 0

                continue

            # --------------------------------------------------
            # Remove the replayed annotation from canvas.
            # --------------------------------------------------

            if target_id in replay_canvas_objects:

                for canvas_id in replay_canvas_objects[
                    target_id
                ]:

                    canvas.delete(
                        canvas_id
                    )

                del replay_canvas_objects[
                    target_id
                ]

            replay_stroke_index += 1

            replay_point_index = 0

            continue

        # ==================================================
        # DRAW EVENT
        # ==================================================

        if stroke.action != "draw":

            replay_stroke_index += 1

            replay_point_index = 0

            continue

        # --------------------------------------------------
        # Only replay strokes belonging to the page
        # we selected when Revive was clicked.
        # --------------------------------------------------

        if (
            background_pdf is not None
            and stroke.page_index != replay_page
        ):

            replay_stroke_index += 1

            replay_point_index = 0

            continue

        # --------------------------------------------------
        # No points.
        # --------------------------------------------------

        if not stroke.points:

            replay_stroke_index += 1

            replay_point_index = 0

            continue

        # --------------------------------------------------
        # Get current point.
        # --------------------------------------------------

        point = stroke.points[
            replay_point_index
        ]

        # --------------------------------------------------
        # This point has not happened yet.
        # --------------------------------------------------

        if point.time > elapsed:

            break

        # --------------------------------------------------
        # Draw segment.
        # --------------------------------------------------

        if replay_point_index > 0:

            previous = stroke.points[
                replay_point_index - 1
            ]

            canvas_id = canvas.create_line(
                previous.x,
                previous.y,
                point.x,
                point.y,
                fill="black",
                width=3,
                capstyle=tk.ROUND,
                smooth=True
            )

            # --------------------------------------------------
            # Remember which canvas objects belong to this
            # particular stroke.
            # --------------------------------------------------

            existing = replay_canvas_objects.get(
                stroke.stroke_id
            )

            if existing is None:

                replay_canvas_objects[
                    stroke.stroke_id
                ] = [canvas_id]

            else:

                existing.append(
                    canvas_id
                )

        replay_point_index += 1

        # --------------------------------------------------
        # Finished this stroke?
        # --------------------------------------------------

        if replay_point_index >= len(
            stroke.points
        ):

            replay_stroke_index += 1

            replay_point_index = 0

        else:

            # There are more points, but they haven't
            # happened yet.
            break

    # ==================================================
    # Finished replay
    # ==================================================

    if replay_stroke_index >= len(
        recording.strokes
    ):

        replaying = False

        return

    root.after(
        5,
        replay_step
    )

# ==================================================
# Window title
# ==================================================

def update_title():

    if current_file is None:

        root.title(
            f"Revive - {recording.title}"
        )

    else:

        root.title(
            f"Revive - {recording.title} "
            f"- {current_file.name}"
        )

    title_label.config(
        text=recording.title
    )

    duration = get_recording_duration()

    time_label.config(
        text=f"00:00 / {format_time(duration)}"
    )

def get_recording_duration():

    duration = 0.0

    for stroke in recording.strokes:

        if stroke.points:

            last_point = stroke.points[-1]

            duration = max(
                duration,
                last_point.time
            )

    return duration

def format_time(seconds):

    minutes = int(seconds // 60)

    seconds = int(seconds % 60)

    return f"{minutes:02d}:{seconds:02d}"

def load_background_image():

    global background_image
    global background_image_path
    global background_image_original

    filepath = filedialog.askopenfilename(
        title="Open Background Image",
        filetypes=[
            (
                "Image files",
                "*.png *.jpg *.jpeg *.webp *.bmp"
            )
        ]
    )

    if not filepath:
        return

    try:

        # Keep the original image.
        background_image_original = Image.open(
            filepath
        ).convert("RGB")

        background_image_path = Path(filepath)

        fit_background_image()

        draw_recording()

    except Exception as error:

        messagebox.showerror(
            "Could not open image",
            str(error)
        )

        return

def load_background_pdf():

    global background_pdf
    global background_pdf_path
    global background_pdf_page

    filepath = filedialog.askopenfilename(
        title="Open Background PDF",
        filetypes=[
            (
                "PDF files",
                "*.pdf"
            )
        ]
    )

    if not filepath:
        return

    try:

        # Close previously opened PDF.
        if background_pdf is not None:
            background_pdf.close()

        # Open the new PDF.
        background_pdf = pymupdf.open(
            filepath
        )

        background_pdf_path = Path(
            filepath
        )

        # Start at page 1.
        background_pdf_page = 0

        # Render the first page.
        render_pdf_page()
        
        update_pdf_navigation()

    except Exception as error:

        messagebox.showerror(
            "Could not open PDF",
            str(error)
        )

def render_pdf_page():

    global background_image_original

    if background_pdf is None:
        return

    if background_pdf_page < 0:
        return

    if background_pdf_page >= len(background_pdf):
        return

    # --------------------------------------------------
    # Get the PDF page
    # --------------------------------------------------

    page = background_pdf[
        background_pdf_page
    ]

    # --------------------------------------------------
    # Get available canvas size
    # --------------------------------------------------

    canvas_width = canvas.winfo_width()
    canvas_height = canvas.winfo_height()

    if canvas_width <= 1 or canvas_height <= 1:
        return

    # --------------------------------------------------
    # PDF page size is given in points.
    # --------------------------------------------------

    page_width = page.rect.width
    page_height = page.rect.height

    # --------------------------------------------------
    # Calculate the scale required to fit the
    # entire PDF page inside the canvas.
    # --------------------------------------------------

    scale_x = canvas_width / page_width
    scale_y = canvas_height / page_height

    scale = min(
        scale_x,
        scale_y
    )

    # --------------------------------------------------
    # Render the PDF page directly at the required
    # display size.
    # --------------------------------------------------

    matrix = pymupdf.Matrix(
        scale,
        scale
    )

    pixmap = page.get_pixmap(
        matrix=matrix,
        alpha=False
    )

    image = Image.frombytes(
        "RGB",
        [
            pixmap.width,
            pixmap.height
        ],
        pixmap.samples
    )

    # --------------------------------------------------
    # Store the rendered page as our background.
    # --------------------------------------------------

    background_image_original = image
    
    fit_background_image()
    
    draw_background_only()

def fit_background_image():

    global background_image

    if background_image_original is None:
        return

    canvas_width = canvas.winfo_width()
    canvas_height = canvas.winfo_height()

    if canvas_width <= 1 or canvas_height <= 1:
        return

    image_width = background_image_original.width
    image_height = background_image_original.height

    # --------------------------------------------------
    # If the image already fits, don't resize it.
    # --------------------------------------------------

    if (
        image_width <= canvas_width
        and image_height <= canvas_height
    ):

        fitted_image = background_image_original

    else:

        # --------------------------------------------------
        # Calculate scale factor while preserving
        # the original aspect ratio.
        # --------------------------------------------------

        scale_x = canvas_width / image_width
        scale_y = canvas_height / image_height

        scale = min(
            scale_x,
            scale_y
        )

        new_width = int(
            image_width * scale
        )

        new_height = int(
            image_height * scale
        )

        fitted_image = background_image_original.resize(
            (
                new_width,
                new_height
            ),
            Image.Resampling.LANCZOS
        )

    background_image = ImageTk.PhotoImage(
        fitted_image
    )

def draw_background_only():

    canvas.delete("background")

    if background_image is None:
        return

    canvas.create_image(
        0,
        0,
        image=background_image,
        anchor="nw",
        tags="background"
    )
    
def update_time_display(current_time):

    duration = get_recording_duration()

    current_time = max(
        0.0,
        min(current_time, duration)
    )

    time_label.config(
        text=(
            f"{format_time(current_time)}"
            f" / "
            f"{format_time(duration)}"
        )
    )
    
def toggle_eraser():

    global eraser_mode

    eraser_mode = not eraser_mode

    update_tool_cursor()

# ==================================================
# RDP Simplification menu
# ==================================================

def set_rdp_simplification(name):

    global RDP_EPSILON
    global selected_rdp_name

    selected_rdp_name = name

    RDP_EPSILON = rdp_options[
        name
    ]

    update_rdp_menu()

    print(
        "RDP:",
        selected_rdp_name,
        "=",
        RDP_EPSILON
    )


def update_rdp_menu():

    for index, name in enumerate(
        rdp_options.keys()
    ):

        if name == selected_rdp_name:

            label = "✓ " + name

        else:

            label = name

        rdp_menu.entryconfig(
            index,
            label=label
        )
        
# ==================================================
# Menu bar
# ==================================================

menubar = tk.Menu(root)


# --------------------------------------------------
# File menu
# --------------------------------------------------

file_menu = tk.Menu(
    menubar,
    tearoff=0
)

file_menu.add_command(
    label="New",
    command=new_recording
)

file_menu.add_command(
    label="Open...",
    command=load_recording
)

file_menu.add_separator()

file_menu.add_command(
    label="Save",
    command=save_recording
)

file_menu.add_command(
    label="Save As...",
    command=save_as
)

file_menu.add_separator()

file_menu.add_command(
    label="Exit",
    command=root.destroy
)

menubar.add_cascade(
    label="File",
    menu=file_menu
)


# --------------------------------------------------
# Edit menu
# --------------------------------------------------

edit_menu = tk.Menu(
    menubar,
    tearoff=0
)

edit_menu.add_command(
    label="Continue Recording",
    command=continue_recording
)

edit_menu.add_command(
    label="Toggle Eraser",
    command=toggle_eraser
)

menubar.add_cascade(
    label="Edit",
    menu=edit_menu
)


# --------------------------------------------------
# Playback menu
# --------------------------------------------------

playback_menu = tk.Menu(
    menubar,
    tearoff=0
)

playback_menu.add_command(
    label="▶ Revive",
    command=start_replay
)

playback_menu.add_separator()


# ==================================================
# Playback speed
# ==================================================

speed_values = [
    0.25,
    0.5,
    1.0,
    1.5,
    2.0,
    4.0
]


def speed_text(speed):

    return f"{speed:g}×"


def set_playback_speed(speed):

    global playback_speed

    playback_speed = speed

    update_speed_menu()


def update_speed_menu():

    for index, speed in enumerate(speed_values):

        if speed == playback_speed:
            label = "✓ " + speed_text(speed)
        else:
            label = speed_text(speed)

        speed_menu.entryconfig(
            index,
            label=label
        )


speed_menu = tk.Menu(
    playback_menu,
    tearoff=0
)


for speed in speed_values:

    speed_menu.add_command(
        label=speed_text(speed),
        command=lambda s=speed:
            set_playback_speed(s)
    )


playback_menu.add_cascade(
    label="Speed",
    menu=speed_menu
)

# ==================================================
# RDP Simplification menu
# ==================================================

rdp_menu = tk.Menu(
    playback_menu,
    tearoff=0
)


for name in rdp_options:

    rdp_menu.add_command(
        label=name,
        command=lambda n=name:
            set_rdp_simplification(n)
    )


playback_menu.add_cascade(
    label="RDP Simplification",
    menu=rdp_menu
)


update_rdp_menu()

update_speed_menu()


menubar.add_cascade(
    label="Playback",
    menu=playback_menu
)

# --------------------------------------------------
# View menu
# --------------------------------------------------

view_menu = tk.Menu(
    menubar,
    tearoff=0
)

view_menu.add_command(
    label="Open Background Image...",
    command=load_background_image
)
view_menu.add_command(
    label="Open Background PDF...",
    command=load_background_pdf
)

menubar.add_cascade(
    label="View",
    menu=view_menu
)

# --------------------------------------------------
# Help menu
# --------------------------------------------------

help_menu = tk.Menu(
    menubar,
    tearoff=0
)

help_menu.add_command(
    label="About Revive",
    command=lambda: messagebox.showinfo(
        "About Revive",
        "Revive\n\n"
        "A lightweight application for "
        "recording and replaying handwritten concepts."
    )
)

menubar.add_cascade(
    label="Help",
    menu=help_menu
)


root.config(
    menu=menubar
)


# ==================================================
# Mouse events
# ==================================================

canvas.bind(
    "<ButtonPress-2>",
    lambda event: toggle_eraser()
)

canvas.bind(
    "<ButtonPress-3>",
    lambda event: toggle_eraser()
)

canvas.bind(
    "<Motion>",
    update_tool_cursor
)

canvas.bind(
    "<ButtonPress-1>",
    start_stroke
)

canvas.bind(
    "<B1-Motion>",
    draw
)

canvas.bind(
    "<ButtonRelease-1>",
    end_stroke
)

def canvas_resized(event):

    if background_pdf is not None:

        render_pdf_page()

    else:

        fit_background_image()

        draw_recording()


canvas.bind(
    "<Configure>",
    canvas_resized
)

# ==================================================
# Start application
# ==================================================
update_pdf_navigation()

root.mainloop()