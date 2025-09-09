from quart import jsonify
import cv2
from typing import Any, Dict, Optional, Tuple

from stepper_hat_pigpio import Controller


def find_markers(frame) -> Dict[str, Any]:
    """
    Extracted from calibrate: detect ArUco markers and compute marker centers and conditions.
    Returns a plain dict (not a Response), so calibrate can jsonify it.
    """
    # Verify ArUco module availability
    aruco = getattr(cv2, 'aruco', None)
    if aruco is None:
        return {
            "status": "error",
            "message": "cv2.aruco is not available. Ensure opencv-contrib-python is installed."
        }

    # Select original ArUco dictionary to match stepper controller configuration
    try:
        if hasattr(aruco, 'getPredefinedDictionary'):
            dictionary = aruco.getPredefinedDictionary(aruco.DICT_ARUCO_ORIGINAL)
        else:
            dictionary = aruco.Dictionary_get(aruco.DICT_ARUCO_ORIGINAL) \
                if hasattr(aruco, 'DICT_ARUCO_ORIGINAL') \
                else aruco.Dictionary_get(aruco.DICT_ARUCO_ORIGINAL)

        # Create detector parameters in a version-agnostic way
        parameters = None
        if hasattr(aruco, 'DetectorParameters'):
            try:
                parameters = aruco.DetectorParameters()
            except Exception:
                try:
                    parameters = aruco.DetectorParameters.create()
                except Exception:
                    parameters = None
        if parameters is None and hasattr(aruco, 'DetectorParameters_create'):
            try:
                parameters = aruco.DetectorParameters_create()
            except Exception:
                parameters = None
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to initialize ArUco detector: {e}. cv2={cv2.__version__}, aruco_has=[ArucoDetector:{hasattr(aruco, 'ArucoDetector')}, DetectorParameters:{hasattr(aruco, 'DetectorParameters')}, DetectorParameters_create:{hasattr(aruco, 'DetectorParameters_create')}]"
        }

    try:
        if hasattr(aruco, 'ArucoDetector'):
            try:
                detector = aruco.ArucoDetector(dictionary, parameters) if parameters is not None else aruco.ArucoDetector(dictionary)
            except TypeError:
                detector = aruco.ArucoDetector(dictionary)
            corners, ids, _ = detector.detectMarkers(frame)
        else:
            if parameters is not None:
                corners, ids, _ = aruco.detectMarkers(frame, dictionary, parameters=parameters)
            else:
                corners, ids, _ = aruco.detectMarkers(frame, dictionary)
    except Exception as e:
        return {"status": "error", "message": f"Error during ArUco detection: {e}"}

    result = {
        "status": "success",
        "found": False,
        "markers": {},
        "conditions": {"id1_top_right": False, "id2_bottom_left": False},
        "image_size": {"width": int(frame.shape[1]), "height": int(frame.shape[0])}
    }

    if ids is not None and len(ids) > 0:
        id_list = [int(x) for x in ids.flatten().tolist()]
        for idx, marker_id in enumerate(id_list):
            pts = corners[idx][0]
            cx = float(pts[:, 0].mean())
            cy = float(pts[:, 1].mean())
            norm_x = cx / frame.shape[1]
            norm_y = cy / frame.shape[0]
            result["markers"][str(marker_id)] = {
                "center": {"x": cx, "y": cy},
                "center_norm": {"x": norm_x, "y": norm_y}
            }
        id1 = result["markers"].get("1")
        id2 = result["markers"].get("2")
        if id1:
            result["conditions"]["id1_top_right"] = (id1["center_norm"]["x"] >= 0.66 and id1["center_norm"]["y"] <= 0.33)
        if id2:
            result["conditions"]["id2_bottom_left"] = (id2["center_norm"]["x"] <= 0.33 and id2["center_norm"]["y"] >= 0.66)
        result["found"] = (id1 is not None) or (id2 is not None)
    else:
        result["message"] = "No ArUco markers detected"

    return result


def centre_on_markers(camera, controller: Controller, markers: Dict[str, Any]) -> Dict[str, Any]:
    """
    Placeholder for step 2 (centering logic). For this step, do nothing yet; return stub.
    """
    return {"status": "not_implemented", "message": "centering logic will be implemented later"}


def calibrate(camera, controller: Controller):
    """
       Step 1 refactor: call find_markers; once two markers are found, call centre_on_markers.
    """
    # Attempt to read a single frame
    success, frame = camera.read()
    if not success or frame is None:
        return jsonify({"status": "error", "message": "Failed to read frame for calibration"})

    detection = find_markers(frame)
    # If detection itself failed (status error), return it as-is
    if detection.get("status") != "success":
        return jsonify(detection)

    # If we have both markers 1 and 2, call centre_on_markers (but keep it a no-op for now)
    markers = detection.get("markers", {})

    if len(markers) == 2:
        _ = centre_on_markers(camera, controller, markers)

    return jsonify(detection)