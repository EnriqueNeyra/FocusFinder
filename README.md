# FocusFinder — A Desk Productivity Helper, Using a Transparent OLED + Pi Camera Module, Powered Raspberry Pi + Python OpenCV

<img width="1633" height="999" alt="image" src="https://github.com/user-attachments/assets/1f1b2b09-88cc-4f34-92ae-d8a03c3a54cc" />  
<!--- https://github.com/user-attachments/assets/f6f684d5-3cc5-4730-a2d7-3b7bf26ac90d --->

### The **FocusFinder** is a small desktop productivity tracker/timer that uses a Transparent OLED with a Pi camera module hidden behind it. The FocusFinder uses Python OpenCV to track focus through face detection. 
### The timer will count up if you are focused on the screen/monitor in front of you. Spend too much time looking away, and the timer will reset!
---

## Contents

- [Required Hardware](#required-hardware)
- [Pi Setup](#pi-setup)
- [Assembly](#assembly)
- [Using FocusFinder](#using-focusfinder)

---

## Required Hardware

| Item | Link |
|------|------|
| Raspberry Pi Zero 2 W | [Amazon](https://amzn.to/3YBvaBV) |
| Pi Power Supply | [Amazon](https://amzn.to/42dMak0) |
| Waveshare 1.54" Transparent OLED  | [Amazon](https://amzn.to/4jjJQNH) |
| Arducam Pi Camera Module V2  | [Amazon](https://amzn.to/3WtWmBk) |
| Micro SD Card (for Pi OS image) | [Amazon](https://amzn.to/3Z0md5n) |
| Enclosure 3D Print Files | [Printables](https://www.printables.com/model/1381066-focus-timer) |

<p align="center">
  <img src="https://github.com/user-attachments/assets/d6c2cf2b-c63b-4921-aac8-436558935e4c" width="48%">
  <img src="https://github.com/user-attachments/assets/0821d3cb-df40-4a72-b2a1-0dd9873f9ca7" width="48%">
</p>


## Pi Setup

**Before starting**, ensure that your Pi is running Raspberry Pi OS (Bookworm) and is connected to your home network.
If you need help installing Raspberry Pi OS, follow the [official guide](https://www.raspberrypi.com/documentation/computers/getting-started.html#installing-the-operating-system).

Once your Pi has booted, open Command Prompt (Windows) or Terminal (Mac), and SSH into the Pi:

```bash
ssh pi@pi.local
```

Then run the following to clone the project and begin setup:

```bash
git clone https://github.com/EnriqueNeyra/FocusFinder.git
cd FocusFinder
sudo bash setup.sh
```

Be sure to **reboot** the Pi after the setup script completes.

---

## Assembly

### 1. Attach the Pi Camera Module to the Pi Zero 2W
<p align="center"><img src="https://github.com/user-attachments/assets/ec961bdc-30c5-4786-a86c-816595282d59" width="700"></p>

### 2. Wire the OLED Display + Driver Board to the [Appropriate Pi Pin Headers](https://www.waveshare.com/wiki/1.51inch_Transparent_OLED#Hardware_connection)
<p align="center"><img src="https://github.com/user-attachments/assets/612fa4d0-b570-4eef-b0b2-a1798f7c4b53" width="700"></p>

### 3. Insert the Pi Into the Base of the Enclosure
<p align="center"><img src="https://github.com/user-attachments/assets/b9720704-1d30-434e-aa53-e2e81e823a92" width="700"></p>

### 4. Slot Display into Display/Camera Holder
<p align="center"><img src="https://github.com/user-attachments/assets/0a0e8a1a-9691-4217-96db-34e10a57ea1a" width="700"></p>

### 5. Slot Camera into Display/Camera Holder
<p align="center"><img src="https://github.com/user-attachments/assets/8a65e2a6-d7b7-4068-af9d-f802761fbe5c" width="700"></p>

### 6. Secure Display/Camera Holder to Base
<p align="center"><img src="https://github.com/user-attachments/assets/fb09dd8a-c53b-4391-a5bc-1c72f37a2aed" width="700"></p>

### 7. Place the Display Driver Board into the Rear Slot, Tuck Wires, and Attach Enclosure Cover
<p align="center"><img src="https://github.com/user-attachments/assets/d0c952c6-68ad-46dd-8ed0-06403e491481" width="700"></p>
<p align="center"><img src="https://github.com/user-attachments/assets/451485cd-8236-41b0-a6d5-85b735af0141" width="700"></p>

### Assembly is now complete!
<p align="center"><img src="https://github.com/user-attachments/assets/fcf0a72d-e128-4cfc-baa7-99e4690f7e58" width="700"></p>

---

## Using FocusFinder

Connect the power cable to the Pi. Place it on a flat surface on your desk, directly in front of you. Angle the display so that it is aimed squarely at your face, and ensure that there is sufficient lighting on your face. Poor lighting will prevent your face from being detected.
From the initial state (00:00), you must be 'focused' and looking in front of you for ~3 seconds before the timer will begin counting. When 'distracted' and looking away, there is a grace period of ~10 seconds before the timer will reset.

### Below is a summary of the different states of Focus Finder

### When the user is idle or away from their desk, the timer stays at 00:00, and the eyes will look around curiously 
![GitHub GIF Idle](https://github.com/user-attachments/assets/ef831756-cf41-49e5-b8e5-110ec7c91546)  


### When the user's face is detected for more than ~3s, the timer begins counting. Eyes will occasionally be 'happy'
![Github GIF Active](https://github.com/user-attachments/assets/6a7ed84b-1acf-477f-9ad6-c48413fa44d3)  


### When the user is 'distracted' (face not detected or looking off too far to either side), eyes will be 'mad/upset', and 'DISTRACTED' text will show. 
### If the user becomes 'focused' again in under ~10s, the timer will keep counting. 
![Github GIF Distracted Without Reset](https://github.com/user-attachments/assets/a9afa4be-8639-4832-a024-c23a851be9ac)  


### If the user remains 'distracted' for greater than ~10s, the timer will reset, and eyes will be 'sad'
![Github GIF Distracted With Reset](https://github.com/user-attachments/assets/5392530f-364c-40cc-a89b-6f3700410134)  


### Credits
This project uses the [micropython-roboeyes](https://github.com/mchobby/micropython-roboeyes) library  
© 2018 MCHobby, licensed under the GNU General Public License v3.0 (GPL-3.0).  
See the [LICENSE](https://github.com/mchobby/micropython-roboeyes/blob/main/LICENSE.txt) file in their repository for details.
