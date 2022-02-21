import subprocess
import re
from enum import Enum
from tkinter import *
import cv2
import numpy as np

SUBPROCESS_ENCODING = 'utf-8'
COORDINATE_TRANSFORM_MATRIX_PROPERTY = "Coordinate Transformation Matrix"

# Extracts connected monitors and their orientation from the output of `xrandr --query`
# We cannot use `xrandr --listmonitors` because that doesn't show the orientation.
# and `xrandr --listmonitors --verbose` just dumps way too much info.
# This: `DP-0 connected 1920x1080+5360+0 right (normal left inverted right x axis y axis) 344mm x 193mm`
# Becomes: {name: "DP-0", width: 1920, height: 1080, x: 5360, y: 0, orientation: "right"}
# A screen with "normal" orientation might simply not report an orientation,
# resulting in an empty string for that group.
XRANDR_MONITOR_REGEX = re.compile(r"^(?P<name>[\w\d-]+) connected(?: primary)? (?P<w>\d+)x(?P<h>\d+)\+(?P<x>\d+)"
                                  r"\+(?P<y>\d+) ?(?P<orientation>\w*) \(")

# Parses a line like:
# Screen 0: minimum 8 x 8, current 5360 x 2520, maximum 32767 x 32767
# into: {width: 5360, height: 2520}
XRANDR_TOTAL_SCREEN_REGEX = re.compile(r"current (?P<width>\d+) x (?P<height>\d+),")

# How far are the calibration points away from the screen edges.
# Width and height are multiplied by this to get the actual pixel locations.
CALIBRATION_POINT_INSET_FRACTION = 0.1


def main():
    virtual_display = get_virtual_display()
    tablet = get_user_pentablet_selection()
    target_display = get_user_display_selection()

    # The pen first needs to be calibrated loosely to the screen, otherwise we aren't going to pick up any clicks.
    print("Mapping tablet to selected display.")
    temporary_matrix = calculate_screen_transformation(virtual_display, target_display)
    apply_matrix_to_device(tablet, temporary_matrix)

    print("Starting fine calibration.")
    calibration = CalibrationWindow(target_display)
    calibration.run()

    fine_matrix = calculate_fine_coordinate_transform_matrix(calibration.calibration_points,
                                                             calibration.clicked_points,
                                                             virtual_display,
                                                             target_display)

    used_command = apply_matrix_to_device(tablet, fine_matrix)
    # When executing the command in a terminal, the device, and property name need quotes.
    used_command[2] = "'" + used_command[2] + "'"
    used_command[4] = "'" + used_command[4] + "'"
    print("If you want to re-apply this calibration later, use the following command:")
    print(" ".join(used_command))

    print("Done")


class CalibrationWindow:
    def __init__(self, target_display):
        self.target_display = target_display

        self.root = Tk()
        # self.root.config(cursor="none")
        self.root.geometry("+{}+{}".format(target_display.x, target_display.y))
        self.root.attributes("-fullscreen", True)

        self.root.bind("<Button-1>", self.calibration_pen_click)
        self.root.bind("<Escape>", self.exit_by_escape)

        self.canvas = Canvas(self.root, highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True)

        self.calibration_points = get_fine_calibration_points(target_display)
        self.clicked_points = np.zeros((4, 2), dtype="float32")
        self.current_point = 0

    def run(self):
        self.draw_next_crosshair()
        self.root.mainloop()

    def draw_next_crosshair(self):
        self.canvas.delete("all")
        self.canvas.create_text(self.target_display.width / 2, self.target_display.height / 2, anchor=CENTER,
                                font=("Helvetica", "15"),
                                text="Click the cross-hairs with the pen tip as accurately as possible")

        point = self.calibration_points[self.current_point]
        self.draw_crosshair(point[0], point[1])

    def draw_crosshair(self, x, y):
        size = 20
        inner_size = 1
        width = 1
        color = "black"

        self.canvas.create_line(x - (size + inner_size), y, x - inner_size + 1, y, fill=color, width=width)
        self.canvas.create_line(x + inner_size, y, x + inner_size + size, y, fill=color, width=width)
        self.canvas.create_line(x, y - (size + inner_size), x, y - inner_size + 1, fill=color, width=width)
        self.canvas.create_line(x, y + inner_size, x, y + inner_size + size, fill=color, width=width)

    def exit_by_escape(self, event):
        self.root.destroy()
        print("User exited.")
        exit(1)

    def calibration_pen_click(self, event):
        x = event.x
        y = event.y

        target_point = self.calibration_points[self.current_point]
        print("Point {}: ({}, {}) -> ({}, {})".format(self.current_point, x, y, target_point[0], target_point[1]))

        self.clicked_points[self.current_point] = (x, y)
        self.current_point += 1

        if self.current_point >= len(self.calibration_points):
            # All calibration points are done. End the loop.
            self.root.destroy()
        else:
            self.draw_next_crosshair()


def apply_matrix_to_device(device_name, matrix):
    mapping_command = ["xinput", "set-prop", device_name, "--type=float", COORDINATE_TRANSFORM_MATRIX_PROPERTY]

    for row in matrix:
        for entry in row:
            mapping_command.append(str(entry))

    subprocess.check_output(mapping_command)

    return mapping_command


def calculate_screen_transformation(virtual_display, target_display):
    virtual_display_corners = np.float32([(0, 0),
                                          (virtual_display.width, 0),
                                          (virtual_display.width, virtual_display.height),
                                          (0, virtual_display.height)])
    target_display_corners = np.float32([(target_display.x, target_display.y),
                                         (target_display.x + target_display.width, target_display.y),
                                         (target_display.x + target_display.width,
                                          target_display.y + target_display.height),
                                         (target_display.x, target_display.y + target_display.height)])

    virtual_display_corners = scale_points_to_virtual_display_unit_size(virtual_display_corners, virtual_display)
    target_display_corners = scale_points_to_virtual_display_unit_size(target_display_corners, virtual_display)

    target_display_corners = move_points_to_orientation(target_display_corners, target_display.orientation)

    matrix = cv2.getPerspectiveTransform(virtual_display_corners, target_display_corners)
    return matrix


def calculate_fine_coordinate_transform_matrix(calibration_points, clicked_points, virtual_display, target_display):
    # The clicked points give us the positions where the pen currently _thinks_ it is when clicking the target.
    # To calibrate, we need to calculate the positions where the pen _should have been_
    # to click precisely in the targets.
    target_points = calibration_points + (calibration_points - clicked_points)

    target_points_on_virtual_display = target_points.copy()

    # Move the points so that they are actually located on the target screen,
    # instead of on the canvas.
    target_points_on_virtual_display[:, 0] = target_points_on_virtual_display[:, 0] + target_display.x
    target_points_on_virtual_display[:, 1] = target_points_on_virtual_display[:, 1] + target_display.y

    calibration_points_on_virtual_display = get_fine_calibration_points(virtual_display)
    calibration_points_on_virtual_display = scale_points_to_virtual_display_unit_size(
        calibration_points_on_virtual_display, virtual_display)
    target_points_on_virtual_display = scale_points_to_virtual_display_unit_size(
        target_points_on_virtual_display, virtual_display)

    fine_adjustment_matrix = cv2.getPerspectiveTransform(calibration_points_on_virtual_display,
                                                         target_points_on_virtual_display)
    return fine_adjustment_matrix


def scale_points_to_virtual_display_unit_size(matrix, virtual_display):
    """xinput expects the translation to be scaled so that the full virtual display's dimensions are equal to 1."""
    matrix[:, 0] = matrix[:, 0] / virtual_display.width
    matrix[:, 1] = matrix[:, 1] / virtual_display.height
    return matrix


def move_points_to_orientation(points, orientation):
    if orientation == Orientation.INVERTED:
        points = np.roll(points, 2, axis=0)

    return points


def get_fine_calibration_points(display):
    x_inset = display.width * CALIBRATION_POINT_INSET_FRACTION
    y_inset = display.height * CALIBRATION_POINT_INSET_FRACTION
    # Ordering of points is clockwise starting from the upper-left.
    return np.float32([(x_inset, y_inset),
                       (display.width - x_inset, y_inset),
                       (display.width - x_inset, display.height - y_inset),
                       (x_inset, display.height - y_inset)])


def get_virtual_display():
    """Returns the dimensions of the display that xrandr creates to stitch all the screens together."""
    xrandr_raw = subprocess.check_output(["xrandr", "-q"]).decode(SUBPROCESS_ENCODING)
    # For now, we assume the virtual screen to always be the 1st one listed.
    virtual_screen_line = xrandr_raw.splitlines()[0]

    match = XRANDR_TOTAL_SCREEN_REGEX.search(virtual_screen_line)
    if match:
        return Display("Screen 0", 0, 0, int(match.group("width")), int(match.group("height")))
    else:
        print("Error, could not find virtual display dimensions")
        exit(1)


def get_user_pentablet_selection():
    xinput_raw = subprocess.check_output(["xinput", "list", "--short"]).decode(SUBPROCESS_ENCODING)
    entries = xinput_raw.split("↳")
    # Filter only pointer devices
    pointer_entries = list(filter(lambda val: "slave  pointer" in val, entries))

    pointers_with_matrices = []

    for entry in pointer_entries:
        id_label = "id="
        name_end_idx = entry.find(id_label)
        name = entry[0:name_end_idx].strip()

        id_start_idx = name_end_idx + len(id_label)
        id_end_idx = entry.find("\t", id_start_idx)
        device_id = entry[id_start_idx:id_end_idx]

        # No use presenting the user a device that doesn't have the necessary matrix.
        if input_device_has_coordinate_matrix(device_id):
            pointers_with_matrices.append(name)

    for i, device in enumerate(pointers_with_matrices):
        print("{}: {}".format(i, device))

    selection = get_user_input_in_range(range(0, len(pointers_with_matrices)), "Which input device is the pen tablet?")
    return pointers_with_matrices[selection]


def input_device_has_coordinate_matrix(device_id):
    props = subprocess.check_output(["xinput", "list-props", str(device_id)]).decode(SUBPROCESS_ENCODING)
    return COORDINATE_TRANSFORM_MATRIX_PROPERTY in props


def get_user_display_selection():
    display_output = subprocess.check_output(["xrandr", "-q"]).decode(SUBPROCESS_ENCODING).splitlines()
    displays = []
    for line in display_output:
        match = XRANDR_MONITOR_REGEX.search(line)
        if match:
            orientation = Orientation.NORMAL
            if match.group("orientation"):
                orientation = Orientation[match.group("orientation").upper()]
            displays.append(Display(match.group("name"),
                                    int(match.group("x")),
                                    int(match.group("y")),
                                    int(match.group("w")),
                                    int(match.group("h")),
                                    orientation))

    for i, display in enumerate(displays):
        print("{}: {}".format(i, display))

    selection = get_user_input_in_range(range(0, len(displays)), "Which display should the tablet be mapped to?")
    return displays[selection]


def get_user_input_in_range(input_range, message):
    number = None
    while number is None:
        raw_input = input("{} [{}-{}] ".format(message, input_range.start, input_range.stop - 1))

        try:
            value = int(raw_input)
            if value in input_range:
                number = value
            else:
                print("Please enter a number in the given range.")
        except ValueError:
            print("Please enter a number.")

    return number


class Orientation(Enum):
    NORMAL = 1
    LEFT = 2
    INVERTED = 3
    RIGHT = 4

    def __str__(self):
        return self.name


class Display:
    def __init__(self, name, x, y, width, height, orientation=Orientation.NORMAL):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.orientation = orientation

    def __str__(self):
        return "{} {}x{} at ({}, {}), orientation: {}".format(
            self.name, self.width, self.height, self.x, self.y, self.orientation)


if __name__ == '__main__':
    main()
