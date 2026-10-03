#!/bin/sh

set -eu

exec flatpak run com.visualstudio.code "$@"
