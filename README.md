Library for ants
================
Robotic microSD card changer that wants to be a tape robot when it grows up

![photo](bloh/IMG_20260621_160534.jpg)

It's a microSD card changer. 

![photo](bloh/IMG_20260621_160512.jpg)

It can pick and insert one out of 12 cards in the magazine into a fixed microSD card reader.

![photo](bloh/shove.gif)

The SD card is held using GRIPOR, which is an interesting project in itself.

![photo](bloh/gripor1.gif)

Robotnik
--------
The control program is written in Python using Textual. 
Some setup is needed to configure a fresh Linux to work with Klipper. 
The scripts are [here](scripts). From experience, every distro needs a bit of persuasion them to work so they're only provided as hints.

GRIPOR
------
The gripper design files are [here](gripor)
There are two Gripors: the pliers version (used in Library for ants) and the parallel version. Both are tested and working.

Mechanics
---------
The printables for the main assembly are all in one 3mf project [here](cad/printables/middleT-project.3mf)
FreeCAD and STEP files will be made available as well.
