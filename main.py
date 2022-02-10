import subprocess
import re

SUBPROCESS_ENCODING = 'utf-8'

# Parses lines like:
# 0: +*HDMI-0 3440/800x1440/335+1920+0  HDMI-0
# into: 3440, 1440, 1920, 0, HDMI-0
# which is: width, height, x-offset, y-offset, name
XRANDR_MONITOR_REGEX = re.compile(r"(\d+)\/\d+x(\d+)\/\d+([+-]\d+)([+-]\d+) +(\S+)$")


def main():
    tablet = get_user_pentabled_selection()
    display = get_user_display_selection()


def get_user_pentabled_selection():
    xinput_raw = subprocess.check_output(["xinput", "list", "--long"]).decode(SUBPROCESS_ENCODING)
    entries = xinput_raw.split("↳")
    pointer_entries = list(filter(lambda val: "slave  pointer" in val, entries))

    for i, entry in enumerate(pointer_entries):
        name_end_idx = entry.find("id=")
        name = entry[0:name_end_idx]
        print("{}: {}".format(i, name))

        button_labels_idx = entry.find("Button labels: ")
        button_labels_end_idx = entry.find("\n", button_labels_idx)
        labels = entry[button_labels_idx:button_labels_end_idx]
        print("          ", labels)

    selection = get_user_input_in_range(range(0, len(pointer_entries)), "Which input device is the pen tablet?")
    return selection


def get_user_display_selection():
    display_output = subprocess.check_output(["xrandr", "--listmonitors"]).decode(SUBPROCESS_ENCODING).splitlines()
    displays = []
    for line in display_output:
        match = XRANDR_MONITOR_REGEX.search(line)
        if match:
            displays.append(Display(match.group(5), match.group(3), match.group(4), match.group(1), match.group(2)))

    selected_display = None
    for i, display in enumerate(displays):
        print("{}: {}".format(i, display))

    selection = get_user_input_in_range(range(0, len(displays)), "Which display should the tablet be mapped to?")
    return selection


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
