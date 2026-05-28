#!/bin/bash

KLIPPER_PORT=/tmp/printer

# exercise with sd card
# card inserted at X12 Y22
CARD_X=5
CARD_Y=23
CARD_Y_INSERT=23
CARD_Y_STORE=21
FEEDRATE=18000

SLOTS="203 186.5 170.5 154.5 138 122.5 106.5 90.5 74.5 58.5 42.5 26.5"

function safe_rehome()
{
  timeout 0.1 cat "$KLIPPER_PORT" >/dev/null 2>&1

  echo "CHECK_HOMED" >"$KLIPPER_PORT"
  status=$(timeout 0.5 cat "$KLIPPER_PORT")
  if echo "$status" | grep -q "AXIS_STATUS: READY"; then
      echo "Axes are homed"
  else
      echo "G28" > "$KLIPPER_PORT"
  fi
}

function readjust_with_card() {
cat <<BABOR >/tmp/printer
G1 Y5 F$FEEDRATE
G1 X$CARD_X F$FEEDRATE
G1 Y$CARD_Y_INSERT
G4 P100
GRIPOR_OPEN
G1 Y16      ; retract to close the beak
GRIPOR_CLOSE
G1 Y22      ; push in
G1 Y16
GRIPOR_OPEN
G1 Y$CARD_Y
GRIPOR_CLOSE
G1 Y5
BABOR
}

function insert_card_into_reader() {
cat <<BABOR >/tmp/printer
G1 Y5 F$FEEDRATE
G1 X$CARD_X F$FEEDRATE
G1 Y$CARD_Y_INSERT
G4 P100
GRIPOR_OPEN
G1 Y16      ; retract to close the beak
GRIPOR_CLOSE
G1 Y22 F1000     ; push in
G1 Y5 F$FEEDRATE
GRIPOR_OPEN
BABOR
}

function insert_card_into_store() {
cat <<BABOR >/tmp/printer
G1 Y5 F$FEEDRATE
G1 Y$CARD_Y_STORE
G4 P100
GRIPOR_OPEN

;; G1 Y$((CARD_Y_STORE-2))
;; GRIPOR_CLOSE
;; G1 Y$CARD_Y_STORE
;; GRIPOR_OPEN
;; 
;; ;G1 Y$((CARD_Y_STORE-2))
;; ;GRIPOR_CLOSE
;; ;G1 Y$CARD_Y_STORE
;; ;GRIPOR_OPEN
;; 
;; G1 Y14      ; retract to close the beak
;; GRIPOR_CLOSE
;; G1 Y$((CARD_Y_STORE-3))      ; push in slightly
G1 Y5
GRIPOR_OPEN
BABOR
}

function pick_card_from_store() {
cat <<BABOR >/tmp/printer
G1 Y5 F$FEEDRATE
GRIPOR_OPEN
G4 P100
G1 Y$((CARD_Y_STORE+1))
GRIPOR_CLOSE
G1 Y5
BABOR
}

function pick_card_from_reader() {
cat <<BABOR >/tmp/printer
G1 Y5 F$FEEDRATE
GRIPOR_OPEN
G1 X$CARD_X F$FEEDRATE
G1 Y$CARD_Y_INSERT
G4 P100
GRIPOR_CLOSE
G1 Y5
BABOR
}

function move_to_x()
{
cat <<BABOR >/tmp/printer
G1 Y5 F$FEEDRATE
G1 X$1 F$FEEDRATE
BABOR
}

function move_to_y()
{
cat <<BABOR >/tmp/printer
G1 Y5 F1000
G1 Y$1 F500
BABOR
}

function wait_for_completion() {
    echo -n "$1: "
    echo "M400" > "$KLIPPER_PORT"
    echo "RESPOND MSG=\"MOTION_DONE\"" > "$KLIPPER_PORT"
    while read -r line < "$KLIPPER_PORT" ; do
        if [[ "$line" == *"MOTION_DONE"* ]]; then
            echo "ok"
            break
        fi
    done
}

echo "Will exercise the robot. Make sure that the card inserted in the reader"
echo "Press enter to continue..."
read bob

safe_rehome

wait_for_completion "HOMING"

#insert_card_into_reader
#exit
pick_card_from_reader
wait_for_completion "PICK CARD FROM READER"

for slot_x in $SLOTS; do
  echo "MOVING THE CARD TO SLOT AT $slot_x"
  move_to_x $slot_x
  wait_for_completion "MOVE TO SLOT AT $slot_x"
  #move_to_y 23
  insert_card_into_store
  wait_for_completion "PUT CARD TO STORE AT $slot_x"
  #echo -e "press enter"
  #read dummy
  sleep 2
  pick_card_from_store
  wait_for_completion "GET CARD FROM STORE AT $slot_x"

  #readjust_with_card
  insert_card_into_reader
  wait_for_completion "INSERT CARD IN READER"
  #echo -e "press enter"
  #read dummy
  sleep 2
  pick_card_from_reader
  wait_for_completion "REMOVE CARD FROM READER"
done

insert_card_into_reader
wait_for_completion "INSERT CARD IN READER"

exit

readjust_with_card
exit


cat <<BABOR >/tmp/printer
GRIPOR_OPEN
G1 Y5 F1000
G1 X$CARD_X F$FEEDRATE
G1 Y$CARD_Y
G4 P1000
GRIPOR_CLOSE
M400
G1 Y5 F8000
BABOR

exit

cat <<BABOR >/tmp/printer
G1 X200
G1 Y$CARD_Y
G1 Y5
G1 X$CARD_X
BABOR

cat <<BABOR >/tmp/printer
G1 P2000
G1 Y$CARD_Y_INSERT
G4 P100
GRIPOR_OPEN
G1 Y16      ; retract to close the beak
GRIPOR_CLOSE
G1 Y22      ; push in
G1 Y16
GRIPOR_OPEN
G1 Y5 
BABOR


#while : ; do 
#cat <<BABOR >/tmp/printer
#GRIPOR_OPEN
#G1 X5 F8000
#
#G1 Y20
#G4 P2000
#G1 Y5
#G1 Y20
#G4 P2000
#GRIPOR_CLOSE
#G1 Y5
#
#G1 X200
#G1 Y20
#G1 Y5
#G1 Y20
#G1 Y5
#
#G1 X5
#G1 Y5
#G1 Y20
#GRIPOR_OPEN
#G1 Y5
#G1 X200
#
#BABOR
#sleep 15
#done 
