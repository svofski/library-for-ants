#!/usr/bin/env python3
from build123d import *
from py_gearworks import *
from bd_warehouse.fastener import *
from ocp_vscode import show, show_object

# parallel gripper with rack and pinion

# general clearance
clearance = 0.2
also_export = True
release_version = True
with_text = True

# 0.1 seems to be a good clearance for a tight fit on servo shaft
servo_shaft_clearance = 0.1

# gear params define all dimensions
gear_module = 1
pinion_nteeth = 12
rack_nteeth = 8

gear_height = 6
rack_height = 8
rail_width = 8

owall_x = 5
owall_y = 3
owall_z = 3

travel_x = 4
liprise = 1.2   # lips rise over the non-touching rails by this much

servo_z_offset = -11

pitch_diameter = pinion_nteeth * gear_module
print(f"Gear pitch diameter={pitch_diameter}")

pinion_gear = SpurGear(number_of_teeth=pinion_nteeth, module=gear_module, height=gear_height)
rack1_rack = InvoluteRack(number_of_teeth=rack_nteeth, module=gear_module, height=gear_height)
rack1_rack.mesh_to(pinion_gear, target_dir=UP, offset=0)

gear = pinion_gear.build_part()
gear.label = "Pinion"
gear.color = "Skyblue"
rack1_teeth = rack1_rack.build_part()

rack_length = rack_nteeth * gear_module * PI
rack1_bb = rack1_teeth.bounding_box()
print(f"rack_length={rack_length}")
rail_body = Box(
                rack_length,
                rail_width, 
                rack_height, 
                align=(Align.CENTER, Align.CENTER, Align.CENTER))

# slots
slot_width = rail_width/2.5
slot_side_width = (rail_width - slot_width) / 2 # the remaining width is split in 2
slot_height = rack_height/3
rail_slot_bottom = Box(rack_length, slot_width, slot_height)
rail_slot_bottom.move(Location((0, 0, -rack_height/2+slot_height/2)))

rail_slot_top = Box(rack_length, slot_width, slot_height)
rail_slot_top.move(Location((0, 0, +rack_height/2-slot_height/2)))

# rail (main body of the rack) offset
teeth_backside_y = rack1_teeth.faces().sort_by(Axis.Y, reverse=True)[0].center().Y
rail_offset = Location((0, teeth_backside_y, 0))  \
    * Location((0, rail_body.width/2, rack_height/2)) 

print(f"teeth_backside_y={teeth_backside_y}")
rail_slot_oppo = Box(rack_length, slot_width - clearance * 2, slot_height - clearance)
rail_slot_oppo.move(Location((0, -2*(teeth_backside_y+rail_body.width/2), +rack_height/2-(slot_height-clearance)/2)))

# lip zero-y is at Plane.XZ, Y = 0
# extrudes left by slot_width, right by (distance between rails) + slot_side_width
distance_between_rails = teeth_backside_y * 2

lip_width = slot_width-clearance # left extension
lip_width += slot_side_width # the main attachment to the rack
lip_width += distance_between_rails 
lip_width += slot_side_width # the other side not attached
lip_width += slot_width # oppo rail 

lip_length = 15
lip_fat = 7
lip_thin = 2
pts = [(-0.1, 0),
       (-0.1, lip_length),
       (-lip_thin, lip_length),
       (-lip_thin, lip_length-3),
       (-lip_fat, 0)]
ln = Polyline(pts, close=True)
sk = (Location((0, slot_width-clearance, 0)) * # offset back before extrusion, so it's on both sides
        make_face(Plane.XZ * ln))
ex = extrude(sk, amount=lip_width-clearance).clean()
ex.move(Location((0, -slot_width/2, rack_height/2)))

# make the top and bottom grooves
rail_body_w_slots = rail_body - (rail_slot_bottom + rail_slot_top) + ex + rail_slot_oppo
# make a clearance gap above the opposite rail
rst = Box(rack_length, slot_width, slot_height)
rst.move(Location((0, 0, +rack_height/2-slot_height/2 + liprise + clearance)))
rail_body_w_slots -= rst
rst2 = Box(rack_length, distance_between_rails + slot_side_width + clearance, slot_height, align=(Align.CENTER, Align.MAX, Align.CENTER))
rst2.move(Location((0, -rail_width/2, +rack_height/2-slot_height/2 + liprise + clearance)))
rail_body_w_slots -= rst2

rail_body_w_slots.move(rail_offset)

# fuse with the teeth
rack1 = rack1_teeth + rail_body_w_slots
rack2 = Rotation(0, 0, 180) * rack1

# load MG90S model, simplify, make watertight, orient and put in position
def import_servo(loc=(0,0,0), rot=Rotation(0,0,0)):
    full_servo_geom = import_step("M90S_ali.step")
    # discard the fluff
    servo_geom = Compound([c for c in full_servo_geom.children if c.label in ("base001", "axe")])

    with BuildPart() as servo:
        with Locations(Location(loc) * rot):
            add(servo_geom)
            Cylinder(radius=2, height=28.4, mode=Mode.ADD)    # remove the thread
            Cylinder(radius=3, height=20.4, mode=Mode.ADD)    # remove the gap between the axle and body
        servo.color = Color("black")

    return servo

servo = import_servo((0, 0, servo_z_offset), Rotation(0, 0, 0))

# enclosure
def make_solid_box(bb: Vector, add: tuple) -> Solid:
    return Box(bb.size.X + 2*add[0], bb.size.Y + 2*add[1], bb.size.Z + 2*add[2]).move(Location(bb.center()))

bbox_bb = Compound([rack1, rack2]).bounding_box()
bbox_inner_x = bbox_bb.size.X + travel_x * 2 + clearance * 2
bbox_outer_x = bbox_inner_x + owall_x * 2 - clearance * 2
bbox_outer_y = bbox_bb.size.Y + owall_y * 2

bigbox_inner_wall = make_solid_box(bbox_bb, (clearance + travel_x, clearance, clearance))
bigbox_outer_wall = make_solid_box(bbox_bb, (owall_x + travel_x, owall_y, owall_z))
bigbox = bigbox_outer_wall - bigbox_inner_wall

bigbox = bigbox.split(Plane.XY.offset(rack_height + clearance + owall_y), keep=Keep.BOTTOM)

bb_rail = Box(bbox_inner_x, slot_width - clearance * 2, slot_height - clearance,
               align=(Align.CENTER, Align.CENTER, Align.MIN))
bb_rail1 = bb_rail.moved(Location((0, +(distance_between_rails/2 + rail_width/2), -clearance)))
bb_rail2 = bb_rail.moved(Location((0, -(distance_between_rails/2 + rail_width/2), -clearance)))

bigbox += bb_rail1 + bb_rail2

# servo mounting enthickener
bigbox_bottom_face = bigbox.faces().filter_by(Axis.Z).sort_by(Axis.Z)[0]
mount_height = 5.0
mount = extrude(bigbox_bottom_face, amount = mount_height)
bigbox_bottom_z = bigbox_bottom_face.position.Z - mount_height
bigbox += mount

if release_version:
    minus_servo = offset(servo.part, 0.3)
else:
    minus_servo = servo.part # for debugging offset is too slow
bigbox -= minus_servo

# enclosure lid

boxlip = 1.5
lidbox_z = owall_z/2 + rack_height + clearance
lidbox_y = bbox_bb.size.Y + 2 * owall_y - boxlip * 2
lidbox = Box(bbox_outer_x - boxlip * 2, lidbox_y, owall_z)
lidbox.move(Location((0, 0, lidbox_z)))
bigbox -= scale(lidbox, (1.005, 1.005, 1.005))

bigbox.name = "Box"
bigbox.color = Color("cadetblue", alpha=1)


windowbox = Box(travel_x * 2 + lip_fat * 2, distance_between_rails + slot_side_width * 2 + slot_width * 2, owall_z * 2)
windowbox.move(Location((0, 0, owall_z/2 + rack_height + clearance)))
lidbox -= windowbox

# probably impossible cover
coverbox = Box(travel_x * 2 + lip_fat * 2, distance_between_rails - clearance, liprise - clearance)
coverbox.move(Location((0, 0, liprise/2 + rack_height + clearance/2)))
coverbox.color = "red"
lidbox += coverbox

lidbox.name = "Lid"
lidbox.color = Color("teal", alpha=1)

m2screw = SocketHeadCapScrew("M2-0.4", length=5)
m3screw = SocketHeadCapScrew("M3-0.5", length=5)
# threaded insert for M2 mounting screws (3.2mm)
m2insert = Cylinder(radius=3/2, height=3, align=(Align.CENTER, Align.CENTER, Align.MAX))

# m2screw scaled + threaded inserts
m2screw_tool = scale(m2screw, (1.1, 1.1, 1)) + m2insert.moved(Location((0,0,-2)))
#m2screw_tool = m2screw
mscrew1 = m2screw_tool.moved(Location((+(bbox_outer_x/2 - 3), +(lidbox_y/2 - owall_y/2), lidbox_z + owall_z/2 - 1)))
mscrew2 = m2screw_tool.moved(Location((+(bbox_outer_x/2 - 3), -(lidbox_y/2 - owall_y/2), lidbox_z + owall_z/2 - 1)))
mscrew3 = m2screw_tool.moved(Location((-(bbox_outer_x/2 - 3), +(lidbox_y/2 - owall_y/2), lidbox_z + owall_z/2 - 1)))
mscrew4 = m2screw_tool.moved(Location((-(bbox_outer_x/2 - 3), -(lidbox_y/2 - owall_y/2), lidbox_z + owall_z/2 - 1)))

lidscrews = Compound([mscrew1, mscrew2, mscrew3, mscrew4])

# servo screws
m2screw_tool2 = scale(m2screw, (1.1, 1.1, 1)) + m2insert.moved(Location((0,0,-2.7)))
sscrew1 = m2screw_tool2.rotate(Axis.Y, 180).moved(Location((-19.45, 0, servo_z_offset)))
sscrew2 = m2screw_tool2.rotate(Axis.Y, 180).moved(Location(( 8.5, 0, servo_z_offset)))
servoscrews = Compound([sscrew1, sscrew2])

# external mounting screws
m3screw_tool = m3screw + Cylinder(radius=4/2, height=5.8, align=(Align.CENTER, Align.CENTER, Align.MAX))
m3screw_z = bigbox_bottom_z/2
m3screw_y = lidbox_y/2 + owall_y/2
m3screw_x = 10 #bbox_outer_x / 4    # put screws 20mm apart for the pliers gripor compat
m3screw1 = m3screw_tool.rotate(Axis.X, +90).moved(Location((+m3screw_x, -m3screw_y, m3screw_z )))
m3screw2 = m3screw_tool.rotate(Axis.X, +90).moved(Location((-m3screw_x, -m3screw_y, m3screw_z )))
m3screw3 = m3screw_tool.rotate(Axis.X, -90).moved(Location((+m3screw_x, +m3screw_y, m3screw_z )))
m3screw4 = m3screw_tool.rotate(Axis.X, -90).moved(Location((-m3screw_x, +m3screw_y, m3screw_z )))

# oriented along x axis
m3xscrew_x = bbox_outer_x/2
m3xscrew_y = 10 # bbox_outer_y/3
m3screw1x = m3screw_tool.rotate(Axis.Y, +90).moved(Location((+m3xscrew_x, +m3xscrew_y, m3screw_z)))
m3screw2x = m3screw_tool.rotate(Axis.Y, -90).moved(Location((-m3xscrew_x, +m3xscrew_y, m3screw_z)))
m3screw3x = m3screw_tool.rotate(Axis.Y, +90).moved(Location((+m3xscrew_x, -m3xscrew_y, m3screw_z)))
m3screw4x = m3screw_tool.rotate(Axis.Y, -90).moved(Location((-m3xscrew_x, -m3xscrew_y, m3screw_z)))

mountscrews = Compound([m3screw1, m3screw2, m3screw3, m3screw4,
                        m3screw1x, m3screw2x, m3screw3x, m3screw4x])

lidbox -= lidscrews
bigbox -= lidscrews + servoscrews + mountscrews

screws = Compound([lidscrews, servoscrews, mountscrews])
screws.name = "Screws"
screws.color = "mediumorchid"

if with_text:
    bloody_face = lidbox.faces().filter_by(Axis.Z).sort_by(Axis.Z)[-1]
    with BuildPart() as bp:
        add(lidbox)

        with BuildSketch(Plane(bloody_face)) as s:
            with Locations((-(distance_between_rails/2 + 4),0)):
                Text("GRIPOR", font="Alien Encounters", font_size=8, align=(Align.CENTER, Align.MIN), rotation=90)
            with Locations((+(distance_between_rails/2 + 4),0)):
                Text("SVOFSKI 2026", font="Good Times", font_size=3, align=(Align.CENTER, Align.MAX), rotation=90)

        extrude(amount=+0.4, mode=Mode.ADD)

    lidbox = bp.part

chamfer_edges = bigbox.edges().filter_by(Axis.Z).sort_by_distance((0,0,0))[-4:]
bigbox = chamfer(chamfer_edges, length = 1)

servo_axle = Cylinder(radius=(4.5 + servo_shaft_clearance)/2, height=10)
gear_with_hole = gear - servo_axle
final_gear = gear_with_hole


from ocp_vscode.config import Camera

rack1.color = "coral"
rack2.color = "peru"

all_parts = [
    final_gear, servo, rack1, rack2,
    bigbox, lidbox,
    # not exported
    screws,
]

show(all_parts,
    reset_camera=Camera.KEEP)

def unwrap(obj):
    """Returns the underlying geometry from a builder or the object itself."""
    return obj.part if hasattr(obj, "part") else obj
if also_export:
    all_parts_clean = [unwrap(x) for x in all_parts[0:-1]]
    clean_combined = Compound(children = all_parts_clean)
    export_step(clean_combined, "gripor-gears-combined.step")
    export_stl(clean_combined, "gripor-gears-combined.stl")
