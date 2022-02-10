At the moment (2022-02-10) the beta gui program for linux doesn't have a calibration button
(It should be under "Work Area -> Screen"), see also [this reddit question](https://www.reddit.com/r/XPpen/comments/s7ijo4/no_calibration_option_for_linux_artist_133_pro/).
So for now, manual calibration is necessary. 
The process below was taken from [this github issue](https://github.com/DIGImend/digimend-kernel-drivers/issues/221)
and the [Calibrating Touchscreens page on the arch wiki](https://wiki.archlinux.org/title/Calibrating_Touchscreen).

This is a nicely overengineerd script that automates the calibration.

Assumes you have the commands `xrandr` and `xinput` available.