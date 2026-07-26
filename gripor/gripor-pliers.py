#!/usr/bin/env python3
from build123d import *
from bd_warehouse.fastener import *
from ocp_vscode import show
import math
from math import atan2

# GRIPOR: pliers-style gripper
#
# (c) svofski 2026 CC-BY-SA ~ this means you can use it, can modify and even sell,
# but you must keep attribution and publicly share your modifications
#
# Extra hardware needed:
#
#  - 4x bearings 3x6x2.5 (ID-OD-thickness)
#    4x 3mm dia round pins approx 20mm long
#  2xM2 screws for servo mount (optionally use M2 threaded inserts)
#       M3 threaded inserts optionally recommended for mounting holes
#    1x MG90S micro servo

# Some assembly required
#
# Glue thin pieces of rubber eraser to the inner surfaces of the pliers' tips, it immensely improves the grip.
#

also_export = True
with_text = False
turd_steps = 30 # groove cutter steps, more than 30 doesn't seem to make a difference

# =========================
# PARAMETERS
# =========================

cam_radius = 10.5          # cam wheel radius (20mm diameter)
cam_thickness = 5
cam_z_offset = -4
servo_shaft_clearance = 0.15
cam_shaft_hole_r = (4.5 + servo_shaft_clearance)/2   # radius for 5mm servo shaft, must be very tight fit

servo_z_offset = -15.5 + cam_z_offset


pin_radius = 1.5            # follower pin radius
pin_to_jaw_clearance = 0.1  # must be a tight fit
clearance = 0.2             # general clearance
turd_clearance = 0.1        # for the groove
groove_r = pin_radius + turd_clearance

jaw_height = 10          # bearings 3x6x2.5 x 2 -> 5mm thicc

# bracket
bracket_thicz = 3   # shelf thickness (z-height)
bottom_bracket_thicz = 6 # servo side shelf thickness
bracket_thicy = 7   # vertical thickness
bracket_clearance = 0.2
bracket_right = 20
bracket_left = 5
bracket_topshelf_left = 5-13
bracket_mounting_left = 6 + bracket_clearance
bracket_mounting_z = servo_z_offset + 2.7 + bracket_clearance
bracket_topshelf_top =  jaw_height + bracket_thicz + 2  # top shelf has extra thicc
bracket_topshelf_bottom = jaw_height + bracket_clearance

bracket_breadth = 32 # size along -x axis

# jaw pivot axle
jaw_pivot_axis_r = 1.5  # jaw pivot bearing ID/2
jaw_pivot_bearing_od = 6  # 3x6x2.5 bearings, 3mm axle
jaw_pivot_bearing_height = 2.5
jaw_pivot_axle_length = jaw_height + bracket_thicz * 2 + 2

# bearing 3x6x2.5
with BuildPart() as bearing:
    Cylinder(radius=jaw_pivot_bearing_od/2 + clearance/2, height=jaw_pivot_bearing_height + clearance, 
             align=(Align.CENTER, Align.CENTER, Align.MIN))
    #Hole(jaw_pivot_axis_r)  # holes are fancy but bearing is a tool for cutout
    bearing.part.color = Color("skyblue")
    bearing.label = f"Bearing {2*jaw_pivot_axis_r}x{jaw_pivot_bearing_od}x{jaw_pivot_bearing_height}"

jaw_pts = [ (2.5,-6),
            (2.1,-1.6),
            (2, 0),
            (2.25,1.4),
            (1.44,7),
            (0.26,11.8),
            (-0.4,11.6),
            (-3, 0),
            (-2.1,-1.6),
            (-1,-6)]
with BuildSketch() as sketch:
    scale_factor = 2
    scaled_pts = [(x * scale_factor, y * scale_factor) for x, y in jaw_pts]
    poly = Polygon(scaled_pts, align=(None, None))
    jaw_face = scale(poly, 1)
jaw = extrude(jaw_face, jaw_height).clean()
jaw = jaw + Cylinder(radius=6, height=jaw_height, align=(Align.CENTER,Align.CENTER,Align.MIN))

jaw = jaw - Cylinder(radius=jaw_pivot_axis_r + clearance, height=jaw_height, align=(Align.CENTER,Align.CENTER,Align.MIN))  # 4x8 bearing
jaw = jaw - bearing.part
jaw = jaw - bearing.part.moved(Location((0, 0, jaw_height - jaw_pivot_bearing_height)))

bottom_corners = (jaw.edges().filter_by(Axis.Z).filter_by_position(Axis.Y, -13, 5))
#jaw = chamfer(bottom_corners, length=1.5)
jaw = fillet(bottom_corners, radius = 1.5)

# pivots
left_jaw_pivot = (-6.2,11,0)
right_jaw_pivot = (+6.2,11,0)

# guide pin
guide_pin_peek = 2
guide_pin_height = jaw_height + cam_thickness + abs(cam_z_offset) + guide_pin_peek
jaw_pin_pos = (1, -8, jaw_height + guide_pin_peek)
right_jaw_pin_pos = (-1, -8, jaw_height + guide_pin_peek)
jaw_pin = Cylinder(radius=jaw_pivot_axis_r, 
                height=guide_pin_height,
                align=(Align.CENTER,Align.CENTER,Align.MAX))
jaw_pin = jaw_pin.move(Location(jaw_pin_pos))
jaw_pin.color = "skyblue"

jaw_pin_hole = Cylinder(radius=jaw_pivot_axis_r + pin_to_jaw_clearance, 
                height=guide_pin_height,
                align=(Align.CENTER,Align.CENTER,Align.MAX))
jaw_pin_hole = jaw_pin_hole.move(Location(jaw_pin_pos))

jaw_with_pin_hole = jaw - jaw_pin_hole


# presumably M3 screws passing through 3x6 bearings
jaw_axle = Cylinder(radius=jaw_pivot_axis_r, height=jaw_pivot_axle_length, align=(Align.CENTER,Align.CENTER,Align.MIN))  # axis draft
jaw_axle.move(Location(((0,0,-bracket_thicz))))
jaw_axle.label = "Jaw axle"
jaw_axle.color = Color("pink", alpha = 0.9)

jaw_right = mirror(jaw_with_pin_hole, about=Plane.YZ)
jaw_left  = jaw_with_pin_hole


jaw_angle = 0 # 14 for closed
jaw_left =  Location(left_jaw_pivot) * Rotation(0, 0,  -jaw_angle) * jaw_left
jaw_right = Location(right_jaw_pivot) * Rotation(0, 0, +jaw_angle) * jaw_right

guide_pin_left = Location(left_jaw_pivot) *jaw_pin #* mirror(jaw_pin, about=Plane.YZ)
guide_pin_right = Location(right_jaw_pivot) * mirror(jaw_pin, about=Plane.YZ)
guide_pin_left.color = "skyblue"
guide_pin_right.color = "skyblue"
guide_pin_left.label = "Guide pin"
guide_pin_right.label = "Guide pin"

# compute a simple bounding box for making a window in the bracket later
jawsbox = Compound(
    [
        Location(left_jaw_pivot) * jaw, 
        Location(right_jaw_pivot) * mirror(jaw, about=Plane.YZ)
    ]
    ).bounding_box()
jaws_envelope = Box(jawsbox.size.X, jawsbox.size.Y, jawsbox.size.Z + 2 * clearance).move(Location(jawsbox.center()))

jaw_axle_left = Location(left_jaw_pivot) * jaw_axle
jaw_axle_right = Location(right_jaw_pivot) * jaw_axle

jaw_left.label = "Jaw Left"
jaw_right.label = "Jaw Right"


def calc_groove_turd(pivot, pin_pos, jaw_angle_max):
    jaw_pin_x = pin_pos[0]
    jaw_pin_y = pin_pos[1]
    #jaw_pin_distance = math.dist((jaw_pin_x, jaw_pin_y), (0,0))
    pin_path = []
    jaw_angle = 0
    wheel_angle = 0
    wheel_range = 90     # how much the cam turns
    nsteps = turd_steps
    for step in range(0,nsteps+1):
        jaw_angle = (step / nsteps) * jaw_angle_max
        wheel_angle = (step / nsteps) * wheel_range
        # x, y  of pin in jaw coordinates, we'll be turning the jaw and saving the path
        sintheta = math.sin(math.radians(jaw_angle))
        costheta = math.cos(math.radians(jaw_angle))
        pin_x = pivot[0] + jaw_pin_x * costheta - jaw_pin_y * sintheta
        pin_y = pivot[1] + jaw_pin_x * sintheta + jaw_pin_y * costheta

        # now turn this point on the disc (around 0,0)
        sintheta = math.sin(math.radians(wheel_angle))
        costheta = math.cos(math.radians(wheel_angle))
        path_x = pin_x * costheta - pin_y * sintheta
        path_y = pin_x * sintheta + pin_y * costheta

        pin_path.append(Vector(path_x, path_y))
        #print(f"angle={angle} ")
    pin_path_pl = Polyline(pin_path)

    num_stamps = 20
    with BuildPart() as boolean_turd:
        points = [pin_path_pl.position_at(v / (num_stamps - 1)) for v in range(num_stamps)]
        with Locations(points):
            Cylinder(radius=groove_r, height=cam_thickness*4).moved(Location(((0,0,cam_z_offset))))
    return boolean_turd

left_groove_turd = calc_groove_turd(left_jaw_pivot, jaw_pin_pos, -15)
right_groove_turd = calc_groove_turd(right_jaw_pivot, right_jaw_pin_pos, 15)

with BuildPart() as cam:
    with BuildSketch():
        Circle(cam_radius, )
    extrude(amount=-cam_thickness)

    # shaft hole
    with Locations((0,0)):
        Hole(radius=cam_shaft_hole_r, depth=cam_thickness)

    cam.part.move(Location((0,0,cam_z_offset)))

cam.part -= left_groove_turd.part
cam.part -= right_groove_turd.part
cam.label = "Cam"

servo = import_step("M90S_ali.step")
servo_rotated = Rotation(0,0,90) * servo
servo_aligned = servo_rotated.moved(Location((0, 0, servo_z_offset))) # put in place
servo_aligned.label = "MG90S"

# make sure the bore is solid and one piece with the body
servo_without_stupid = servo + Cylinder(radius=3, height=20)
servo_without_stupid = Rotation(0,0,90) * servo_without_stupid
servo_without_stupid = servo_without_stupid.moved(Location((0, 0, servo_z_offset)))



# THE BRACKET
# mirror E shape
bracket_pts = [
    (bracket_mounting_left, bracket_mounting_z), # bottom of middle shelf, bottom-left corner
    (bracket_right, bracket_mounting_z),
    (bracket_right,         bracket_topshelf_top),
    (bracket_topshelf_left, bracket_topshelf_top),  # top shelf
    (bracket_topshelf_left,         bracket_topshelf_bottom),
    (bracket_right - bracket_thicy, bracket_topshelf_bottom),
    (bracket_right - bracket_thicy,            - bracket_clearance), # top of middle shelf
    (bracket_left,                             - bracket_clearance),
    (bracket_left,                             + cam_z_offset + bracket_clearance), # bottom of middle shelf
    (bracket_right - bracket_thicy*1.2,            + cam_z_offset + bracket_clearance),
    (bracket_right - bracket_thicy*1.2,              bracket_mounting_z + bottom_bracket_thicz),
    (bracket_mounting_left,                      bracket_mounting_z + bottom_bracket_thicz),
]

#bracket_poly = Polyline(bracket_pts, close=True)
with BuildSketch(Plane.YZ) as sketch:
    with BuildLine():
        Polyline(bracket_pts, close=True)
    make_face()
bracket_side = sketch.sketch

bracket = extrude(sketch.sketch, amount = bracket_breadth).clean().moved(Location((-bracket_breadth/2, 0, 0)))

# remove the window for the jaws
bracket = bracket - jaws_envelope - jaw_axle_left - jaw_axle_right

with BuildPart() as top_window:
    Box(20, 6, 20)
    chamfer(top_window.edges(), 1)
    top_window.part.move(Location((0, 3, jaw_height - clearance)))

# extend the bottom side of the bracket for servo mount
bottom_shelf = bracket.faces().sort_by(Axis.Z, reverse=True).filter_by_position(Axis.Z, servo_z_offset - bracket_thicy, servo_z_offset + bracket_thicy)
extrudable_edge = bottom_shelf.sort_by(Axis.Y)[0]
bottom_plate = extrude(extrudable_edge, amount = 30)

bracket = bracket + bottom_plate - servo_without_stupid.scale(1.05)

# inner chamfer
bob_y = bracket_right - bracket_thicy*1.2
bob =( bracket.edges() 
    .filter_by_position(Axis.Z, minimum=servo_z_offset - 1, maximum=servo_z_offset + 6)
    .filter_by_position(Axis.Y, bob_y, bob_y + 10)
    )
bracket = fillet(bob, radius=5)

# chamfer 2 corners on the longer bracket (servo mounting side)
bob = (
    bracket.edges()
    .filter_by_position(Axis.Y, minimum=-100500,maximum=-20)
    .filter_by(Axis.Z)
)
bracket = chamfer(bob, length=3)

# chamfer 2 corners on the shorter bracket (lips side)
mike = (
    bracket.edges()
    .filter_by_position(Axis.Y, minimum=-10, maximum=-4)
    .filter_by_position(Axis.Z, minimum=0, maximum=100)
    .filter_by(Axis.Z)
)
bracket = chamfer(mike, length=3)

# servo mounting screws M2
screw = SocketHeadCapScrew("M2-0.4", length=5)
screw = screw.rotate(Axis.X, angle=180).move(Location((0, 8.5, servo_z_offset)))
screw2 = screw.moved(Location((0, -28, 0)))

smallscrews = Compound([screw, screw2])
smallscrews.label = "M2 screws"

# threaded insert for M2 mounting screws (3.2mm)
insert = Cylinder(radius=3/2, height=3, align=(Align.CENTER, Align.CENTER, Align.MAX))
# inserts for the servo
insert1 = insert.moved(Location((0, 8.5, servo_z_offset + 3 + 2.5 + clearance)))
insert2 = insert.moved(Location((0, 8.5-28, servo_z_offset + 3 + 2.5 + clearance)))

# inserts for the side brackets
mid_insert_z = cam_z_offset/2       # tongue in E
top_insert_z = (bracket_topshelf_top + bracket_topshelf_bottom)/2 # in the top shelf side

side_insert_x = bracket_breadth/2 
insert3a = insert.rotate(Axis.Y,  90).moved(Location((+side_insert_x, bracket_right - bracket_thicy/2,  mid_insert_z)))
insert3b = insert.rotate(Axis.Y,  90).moved(Location((+side_insert_x, bracket_left + 3,  mid_insert_z)))
insert3c = insert.rotate(Axis.Y,  90).moved(Location((+side_insert_x, bracket_right - bracket_thicy/2, top_insert_z - 4)))
insert3d = insert.rotate(Axis.Y,  90).moved(Location((+side_insert_x, 0,  top_insert_z)))

insert4a=  insert.rotate(Axis.Y, -90).moved(Location((-side_insert_x, bracket_right - bracket_thicy/2, mid_insert_z)))
insert4b = insert.rotate(Axis.Y, -90).moved(Location((-side_insert_x, bracket_left + 3,  mid_insert_z)))
insert4c = insert.rotate(Axis.Y, -90).moved(Location((-side_insert_x, bracket_right - bracket_thicy/2, top_insert_z - 4)))
insert4d = insert.rotate(Axis.Y, -90).moved(Location((-side_insert_x, 0,  top_insert_z)))

inserts = Compound([insert1, insert2, 
                    insert3a, #insert3b,
                    insert3c, insert3d, 
                    insert4a, #insert4b,
                    insert4c, insert4d
    ])
inserts.label = "M2 inserts"

bracket = bracket - inserts

# main part mounting holes
bigscrews_z = jaw_height + 1 + clearance
bigscrew_high_hat = SocketHeadCapScrew("M3-0.5", length=8)
bigscrew = bigscrew_high_hat.split(Plane.XY.offset(1+clearance*2), keep=Keep.BOTTOM)
bigscrew1 = bigscrew.rotate(Axis.X, angle=180).move(Location((+10, -4, bigscrews_z)))
bigscrew2 = bigscrew.rotate(Axis.X, angle=180).move(Location((-10, -4, bigscrews_z)))
bigscrew3 = bigscrew.rotate(Axis.X, angle=180).move(Location((  0, -4, bigscrews_z)))

# screwhole in front
bigscrew4 = bigscrew.rotate(Axis.X, angle=180).move(
    Location((0, 
              bracket_right - 6/2 - 2,      # M3 screw has 6mm head, 2mm away from the wall
              bigscrews_z))) # flat head M3 is 1mm thick

bigscrews = Compound([bigscrew1, bigscrew2, bigscrew3, bigscrew4])
bigscrews.color = "skyblue"
bigscrews.label = "M3-05"

screwdriver_hole_z = jaw_height
screwdriver_hole = Cylinder(radius=3, height=100, align=(Align.CENTER, Align.CENTER, Align.MAX))
screwdriver_hole1 = screwdriver_hole.moved(Location((+10, -4,                    screwdriver_hole_z)))
screwdriver_hole2 = screwdriver_hole.moved(Location((-10, -4,                    screwdriver_hole_z)))
screwdriver_hole3 = screwdriver_hole.moved(Location((0, bracket_right - 6/2 - 2, screwdriver_hole_z)))

screwdriver_holes = Compound([screwdriver_hole1, screwdriver_hole2, screwdriver_hole3])
screwdriver_holes.label = "Screwdriver holes"

bracket = bracket - bigscrews -  screwdriver_holes - top_window.part

if with_text:
    bloody_face = bracket.faces().filter_by(Axis.Y).sort_by(Axis.Y)[-1]
    with BuildPart() as bp:
        add(bracket)

        with BuildSketch(Plane(bloody_face)) as s:
            with Locations((-5,0)):
                Text("GRIPOR", font="Alien Encounters", font_size=8, align=(Align.CENTER, Align.CENTER), rotation=90)
            with Locations((jaw_height+bracket_thicz/2 + 1, 0)):
                Text("SVOFSKI 2026", font="Good Times", font_size=3, align=(Align.CENTER, Align.CENTER), rotation=90)

        extrude(amount=-0.4, mode=Mode.SUBTRACT)

    bracket = bp.part
else:
    # create recess areas for labels
    bloody_face = bracket.faces().filter_by(Axis.Y).sort_by(Axis.Y)[-1]
    with BuildPart() as bp:
        add(bracket)

        with BuildSketch(Plane(bloody_face)) as s:
            with Locations((-6,0)):
                Rectangle(width=25, height=9.25, rotation=90)
            with Locations((jaw_height+bracket_thicz/2 + 1, 0)):
                Rectangle(width=25, height=3.25, rotation=90)

        extrude(amount=-0.4, mode=Mode.SUBTRACT)

    bracket = bp.part


jaw_left = jaw_left - screwdriver_holes
jaw_right = jaw_right - screwdriver_holes

bracket.color = "peru"
bracket.label = "Braquet"

all_parts=[bigscrews, smallscrews, inserts, servo_aligned, bracket, cam, jaw_left, jaw_right, 
     jaw_axle_left, jaw_axle_right, 
     guide_pin_left, guide_pin_right]

all_printable_parts=[bracket, cam, jaw_left, jaw_right]

show(all_parts,
      reset_camera=False)

def unwrap(obj):
    """Returns the underlying geometry from a builder or the object itself."""
    return obj.part if hasattr(obj, "part") else obj
all_parts_clean = [unwrap(x) for x in all_parts]

if also_export:
    all_parts_clean = [unwrap(x) for x in all_printable_parts]
    clean_combined = Compound(children = all_parts_clean)
    export_step(clean_combined, "gripor-combined.step")
    export_stl(clean_combined, "gripor-combined.stl")

print(f"jaw_pivot_axle_length: {jaw_pivot_axle_length}mm")
print(f"guide_pin_height: {guide_pin_height}mm")

