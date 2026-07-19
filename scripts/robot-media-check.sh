#!/bin/sh

if [ -e /sys/block/sda/size ]; then
    size=$(cat /sys/block/sda/size)

    if [ "$size" = "0" ]; then
        systemctl stop mnt-robot_media.mount
    fi
fi
