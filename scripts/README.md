## Environment setup stuff

### Automount

mnt-robot_media.* 
  -> /etc/systemd/system/

systemctl daemon-reload 
systemctl enable --now mnt-robot_media.automount

### udev hotplug 

Avoid annoying device name changes etc

99-klipper-hotplug.rules
99-usb-serial.rules 
  -> /etc/udev/rules.d/
sudo udevadm control --reload-rules

### pythong

pip3 install -r requirements.txt


