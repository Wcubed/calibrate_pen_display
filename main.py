import subprocess
import re

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
    tablet = get_user_pentabled_selection()
    tablet_display = get_user_display_selection()

    matrix = calculate_coordinate_transform_matrix(virtual_display, tablet_display)

    apply_matrix_to_device(tablet[0], matrix)
    print("Done")


def apply_matrix_to_device(device_name, matrix):
    print("")
    print("Mapping tablet: '{}'".format(device_name))
    print("With matrix:", matrix)

    mapping_command = ["xinput", "set-prop", device_name, "--type=float", COORDINATE_TRANSFORM_MATRIX_PROPERTY]

    for entry in matrix:
        mapping_command.append(str(entry))

    subprocess.check_output(mapping_command)


def calculate_coordinate_transform_matrix(total_display, target_display):
    return [target_display.width / total_display.width, 0, target_display.x / total_display.width,
            0, target_display.height / total_display.height, target_display.y / total_display.height,
            0, 0, 1]


def get_virtual_display():
    """Returns the dimensions of the display that xrandr creates to stitch all the screens together."""
    xrandr_raw = subprocess.check_output(["xrandr"]).decode(SUBPROCESS_ENCODING)
    # The virtual screen should always be the 1st one.
    virtual_screen_line = xrandr_raw.splitlines()[0]

    match = XRANDR_TOTAL_SCREEN_REGEX.search(virtual_screen_line)
    if match:
        return Display("Screen 0", 0, 0, int(match.group(1)), int(match.group(2)))
    else:
        print("Error, could not find virtual display dimensions")
        exit(1)


def get_user_pentabled_selection():
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
