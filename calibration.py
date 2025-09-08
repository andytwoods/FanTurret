from quart import jsonify
import cv2


def calibrate(camera):
    """
       Starts a minimal calibration routine by detecting ArUco markers (IDs 1 and 2)
       in the current camera frame. It checks whether marker 1 appears top-right and
       marker 2 bottom-left in the image.

       Returns:
           JSON: Detection results including whether required markers were found and their positions.
       """


    # Attempt to read a single frame
    success, frame = camera.read()
    if not success or frame is None:
        return jsonify({
            "status": "error",
            "message": "Failed to read frame for calibration"
        })

    # Verify ArUco module availability
    aruco = getattr(cv2, 'aruco', None)

    if aruco is None:
        return jsonify({
            "status": "error",
            "message": "cv2.aruco is not available. Ensure opencv-contrib-python is installed."
        })

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
        # Newer OpenCV (some builds) expose a class constructor
        if hasattr(aruco, 'DetectorParameters'):
            try:
                parameters = aruco.DetectorParameters()
            except Exception:
                # Some versions use factory method on the class
                try:
                    parameters = aruco.DetectorParameters.create()
                except Exception:
                    parameters = None
        # Older OpenCV exposes a module-level factory function
        if parameters is None and hasattr(aruco, 'DetectorParameters_create'):
            try:
                parameters = aruco.DetectorParameters_create()
            except Exception:
                parameters = None

        # If still None, we'll proceed with defaults (API allows parameters to be optional in some versions)
    except Exception as e:
        # Provide extra debug context
        return jsonify({
            "status": "error",
            "message": f"Failed to initialize ArUco detector: {e}. cv2={cv2.__version__}, aruco_has=[ArucoDetector:{hasattr(aruco, 'ArucoDetector')}, DetectorParameters:{hasattr(aruco, 'DetectorParameters')}, DetectorParameters_create:{hasattr(aruco, 'DetectorParameters_create')}]"
        })

    try:
        # For OpenCV >= 4.7, use ArucoDetector class if available
        if hasattr(aruco, 'ArucoDetector'):
            try:
                detector = aruco.ArucoDetector(dictionary,
                                               parameters) if parameters is not None else aruco.ArucoDetector(
                    dictionary)
            except TypeError:
                # Constructor signature differences across versions
                detector = aruco.ArucoDetector(dictionary)
            corners, ids, _ = detector.detectMarkers(frame)
        else:
            # Older API
            if parameters is not None:
                corners, ids, _ = aruco.detectMarkers(frame, dictionary, parameters=parameters)
            else:
                # Some versions accept only (image, dictionary)
                corners, ids, _ = aruco.detectMarkers(frame, dictionary)
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error during ArUco detection: {e}"
        })

    result = {
        "status": "success",
        "found": False,
        "markers": {},
        "conditions": {
            "id1_top_right": False,
            "id2_bottom_left": False
        },
        "image_size": {
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0])
        }
    }

    if ids is not None and len(ids) > 0:
        # Flatten ids to a Python list of ints
        id_list = [int(x) for x in ids.flatten().tolist()]
        for idx, marker_id in enumerate(id_list):
            pts = corners[idx][0]  # 4x2 array
            cx = float(pts[:, 0].mean())
            cy = float(pts[:, 1].mean())
            norm_x = cx / frame.shape[1]
            norm_y = cy / frame.shape[0]
            result["markers"][str(marker_id)] = {
                "center": {"x": cx, "y": cy},
                "center_norm": {"x": norm_x, "y": norm_y}
            }

        # Evaluate positions for IDs 1 and 2
        id1 = result["markers"].get("1")
        id2 = result["markers"].get("2")
        if id1:
            # Top-right: y small (closer to 0), x large (closer to 1)
            result["conditions"]["id1_top_right"] = (
                        id1["center_norm"]["x"] >= 0.66 and id1["center_norm"]["y"] <= 0.33)
        if id2:
            # Bottom-left: y large (closer to 1), x small (closer to 0)
            result["conditions"]["id2_bottom_left"] = (
                        id2["center_norm"]["x"] <= 0.33 and id2["center_norm"]["y"] >= 0.66)

        result["found"] = (id1 is not None) or (id2 is not None)
    else:
        result["message"] = "No ArUco markers detected"

    return jsonify(result)