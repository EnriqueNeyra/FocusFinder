import cv2
import numpy as np
from picamera2 import Picamera2
import time

class FocusDetector:
    def __init__(self, cascade_path=None):
        if cascade_path is None:
            cascade_path = "./model_files/haarcascade_frontalface_alt.xml"
        self.face_cascade = cv2.CascadeClassifier(cascade_path)
        
        self.eye_cascade = cv2.CascadeClassifier("./model_files/haarcascade_eye.xml")

        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))

    def is_face_frontal(self, face_roi, face_x, face_y):
        """Check if face is roughly frontal by detecting both eyes"""
        face_roi_eq = self.clahe.apply(face_roi)
        eyes = self.eye_cascade.detectMultiScale(
            face_roi_eq, 
            scaleFactor=1.15, 
            minNeighbors=4,
            )
        
        # Filter eyes based on position within face
        valid_eyes = []
        face_width = face_roi.shape[1]
        face_height = face_roi.shape[0]
        
        for (ex, ey, ew, eh) in eyes: 
            # Eyes should be in upper half of face
            if ey < face_height * 0.5:
                # Eyes shouldn't be too close to edges
                eye_center_x = ex + ew//2
                if 0.15 * face_width < eye_center_x < 0.85 * face_width:
                    valid_eyes.append((ex, ey, ew, eh))
        
        # Convert eye coordinates from face ROI to full image coordinates
        global_eyes = []
        for (ex, ey, ew, eh) in valid_eyes:
            global_ex = face_x + ex + ew//2  # Center of eye
            global_ey = face_y + ey + eh//2  # Center of eye
            global_eyes.append((global_ex, global_ey))
        
        # Frontal faces should have 2 visible eyes
        return len(valid_eyes) >= 2, global_eyes

    def is_focused(self, frame_gray):

        frame_gray_eq = self.clahe.apply(frame_gray)
        faces = self.face_cascade.detectMultiScale(
            frame_gray_eq, 
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(40, 40),
        )
        
        # Filter faces to only include frontal ones
        frontal_faces = []
        all_eyes = []
        
        for (x, y, w, h) in faces:
            face_roi = frame_gray[y:y+h, x:x+w]
            is_frontal, eyes = self.is_face_frontal(face_roi, x, y)
            if is_frontal:
                frontal_faces.append((x, y, w, h))
                all_eyes.extend(eyes)
        
        return len(frontal_faces) > 0, frontal_faces, all_eyes