import cv2
import os
import logging
from focus_detector import FocusDetector
from camera_interface import CameraInterface
from focus_state import FocusState
from focus_timer_thread import FocusTimerThread 

HEADLESS = os.environ.get("DISPLAY", "") == ""

def main():
    camera = CameraInterface()
    detector = FocusDetector()
    focus_state = FocusState()
    focus_thread = FocusTimerThread(focus_state)
    focus_thread.start()

    while True:
        frame, gray = camera.get_frame()
        focused, faces, eyes = detector.is_focused(gray)
        logging.info(f"Focused: {focused}, Faces detected: {len(faces)}")
        focus_state.set(focused)
        
        print(HEADLESS)

        status = "Focused" if focused else "Distracted"
        color = (0, 255, 0) if focused else (0, 0, 255)

        if not HEADLESS:
            # Draw rectangles around detected faces
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            
            # Draw dots on detected eyes
            for (ex, ey) in eyes:
                cv2.circle(frame, (ex, ey), 5, (255, 0, 0), -1)  # Blue filled circles
            
            cv2.putText(frame, status, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            
            cv2.namedWindow("Focus Finder", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Focus Finder", 800, 480)
            cv2.imshow("Focus Finder", frame)
            
            if cv2.waitKey(1) == 27:  # ESC to quit
                break
        

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
