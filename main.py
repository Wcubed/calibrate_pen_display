import subprocess
import re
from tkinter import *
import cv2
import numpy as np

SUBPROCESS_ENCODING = 'utf-8'
COORDINATE_TRANSFORM_MATRIX_PROPERTY = "Coordinate Transformation Matrix"

# Parses lines like:
# 0: +*HDMI-0 3440/800x1440/335+1920+0  HDMI-0
# into: 3440, 1440, 1920, 0, HDMI-0
# which is: width, height, x-offset, y-offset, name
XRANDR_MONITOR_REGEX = re.compile(r"(\d+)\/\d+x(\d+)\/\d+([+-]\d+)([+-]\d+) +(\S+)$")

# Parses a line like:
# Screen 0: minimum 8 x 8, current 5360 x 2520, maximum 32767 x 32767
# into: 5360, 2520
# which is: width, height
XRANDR_TOTAL_SCREEN_REGEX = re.compile(r"current (\d+) x (\d+),")


def main():
    virtual_display = get_virtual_display()
    tablet = get_user_pentablet_selection()
    target_display = get_user_display_selection()

    # The pen first needs to be calibrated loosely to the screen, otherwise we aren't going to pick up any clicks.
    print("Mapping tablet to selected display.")
    screen_matrix = calculate_screen_transformation(virtual_display, target_display)
    apply_matrix_to_device(tablet[0], screen_matrix)

    print("Starting fine calibration.")
    calibration = CalibrationWindow(target_display)
    calibration.run()

    fine_matrix = calculate_fine_coordinate_transform_matrix(calibration.calibration_points, calibration.clicked_points)
    # xinput expects the translation to be scaled so that the full virtual display is 1.
    fine_matrix[0][2] /= virtual_display.width
    fine_matrix[1][2] /= virtual_display.height

    total_matrix = screen_matrix.dot(fine_matrix)
    print(total_matrix)

    apply_matrix_to_device(tablet[0], total_matrix)
    print("Done")


class CalibrationWindow:
    def __init__(self, target_display):
        self.target_display = target_display

        self.root = Tk()
        self.root.geometry("+{}+{}".format(target_display.x, target_display.y))
        self.root.attributes("-fullscreen", True)

        self.root.bind("<Button-1>", self.calibration_pen_click)
        self.root.bind("<Escape>", self.exit_by_escape)

        self.canvas = Canvas(self.root)
        self.canvas.pack(fill=BOTH, expand=True)

        x_inset = target_display.width * 0.1
        y_inset = target_display.height * 0.1
        # Ordering of points is clockwise starting from the upper-left.
        self.calibration_points = np.float32([(x_inset, y_inset),
                                              (target_display.width - x_inset, y_inset),
                                              (target_display.width - x_inset, target_display.height - y_inset),
                                              (x_inset, target_display.height - y_inset)])
        self.clicked_points = np.zeros((4, 2), dtype="float32")
        self.current_point = 0

    def run(self):
        self.draw_next_crosshair()
        self.root.mainloop()

    def draw_next_crosshair(self):
        self.canvas.delete("all")

        point = self.calibration_points[self.current_point]
        self.draw_crosshair(point[0], point[1])

    def draw_crosshair(self, x, y):
        size = 20
        inner_size = 3
        width = 1
        color = "black"

        self.canvas.create_line(x - (size + inner_size), y, x - inner_size, y, fill=color, width=width)
        self.canvas.create_line(x + inner_size, y, x + inner_size + size, y, fill=color, width=width)
        self.canvas.create_line(x, y - (size + inner_size), x, y - inner_size, fill=color, width=width)
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

    print(mapping_command)

    subprocess.check_output(mapping_command)


def calculate_screen_transformation(virtual_display, target_display):
    return np.float32([(target_display.width / virtual_display.width, 0, target_display.x / virtual_display.width),
                       (0, target_display.height / virtual_display.height, target_display.y / virtual_display.height),
                       (0, 0, 1)])


def calculate_fine_coordinate_transform_matrix(calibration_points, actual_points):
    return cv2.getPerspectiveTransform(actual_points, calibration_points)


def get_virtual_display():
    """Returns the dimensions of the display that xrandr creates to stitch all the screens together."""
    xrandr_raw = subprocess.check_output(["xrandr"]).decode(SUBPROCESS_ENCODING)
    # For now we assume the virtual screen to always be the 1st one listed.
    virtual_screen_line = xrandr_raw.splitlines()[0]

    match = XRANDR_TOTAL_SCREEN_REGEX.search(virtual_screen_line)
    if match:
        return Display("Screen 0", 0, 0, int(match.group(1)), int(match.group(2)))
    else:
        print("Error, could not find virtual display dimensions")
        exit(1)


def get_user_pentablet_selection():
    xinput_raw = subprocess.check_output(["xinput", "list", "--long"]).decode(SUBPROCESS_ENCODING)
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
        if not input_device_has_coordinate_matrix(device_id):
            continue

        button_labels_idx = entry.find("Button labels: ")
        button_labels_end_idx = entry.find("\n", button_labels_idx)
        labels = entry[button_labels_idx:button_labels_end_idx]

        pointers_with_matrices.append((name, labels))

    for i, device in enumerate(pointers_with_matrices):
        print("{}: {}".format(i, device[0]))
        print("      ", device[1])

    selection = get_user_input_in_range(range(0, len(pointers_with_matrices)), "Which input device is the pen tablet?")
    return pointers_with_matrices[selection]


def input_device_has_coordinate_matrix(device_id):
    props = subprocess.check_output(["xinput", "list-props", str(device_id)]).decode(SUBPROCESS_ENCODING)
    return COORDINATE_TRANSFORM_MATRIX_PROPERTY in props


def get_user_display_selection():
    display_output = subprocess.check_output(["xrandr", "--listmonitors"]).decode(SUBPROCESS_ENCODING).splitlines()
    displays = []
    for line in display_output:
        match = XRANDR_MONITOR_REGEX.search(line)
        if match:
            displays.append(Display(match.group(5),
                                    int(match.group(3)),
                                    int(match.group(4)),
                                    int(match.group(1)),
                                    int(match.group(2))))

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


class Display:
    def __init__(self, name, x, y, width, height):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    def __str__(self):
        return "{} {}x{} at ({}, {})".format(self.name, self.width, self.height, self.x, self.y)


if __name__ == '__main__':
    main()
