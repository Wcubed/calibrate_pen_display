import subprocess
import re

SUBPROCESS_ENCODING = 'utf-8'

# Parses lines like:
# 0: +*HDMI-0 3440/800x1440/335+1920+0  HDMI-0
# into: 3440, 1440, 1920, 0, HDMI-0
# which is: width, height, x-offset, y-offset, name
XRANDR_MONITOR_REGEX = re.compile(r"(\d+)\/\d+x(\d+)\/\d+([+-]\d+)([+-]\d+) +(\S+)$")


def main():
    display_raw_output = subprocess.check_output(['xrandr', '--listmonitors']).splitlines()
    displays = []
    for raw_bytes in display_raw_output:
        match = XRANDR_MONITOR_REGEX.search(raw_bytes.decode(SUBPROCESS_ENCODING))
        if match:
            displays.append(Display(match.group(5), match.group(3), match.group(4), match.group(1), match.group(2)))

    selected_display = None
    for i, display in enumerate(displays):
        print("{}: {}".format(i, display))

    selection = get_user_input_in_range(range(0, len(displays)), "Which display should the tablet be mapped to?")


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
