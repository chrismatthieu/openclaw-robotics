"""
FollowRobotApp - Main Application

Ties together PersonTracker, PersonIdentifier, and FollowerController.
Exposes HTTP API for OpenClaw integration.
"""

import time
import threading
import base64
from typing import Optional
from flask import Flask, request, jsonify

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

from .person_tracker import PersonTracker, DetectedPerson
from .person_identifier import PersonIdentifier
from .follower_controller import FollowerController, ControllerConfig


class FollowRobotApp:
    """
    Main application that coordinates person tracking, identification,
    and robot control, with HTTP API for OpenClaw.
    """

    def __init__(self, port: int = 5050, use_camera: bool = True,
                 use_vlm: bool = True, target_distance: float = 1.0):
        self.port = port
        
        # Initialize components
        self.tracker = PersonTracker(use_camera=use_camera)
        self.identifier = PersonIdentifier(use_vlm=use_vlm)
        
        config = ControllerConfig(target_distance=target_distance)
        self.controller = FollowerController(config=config)
        
        # Control loop state
        self._running = False
        self._control_thread: Optional[threading.Thread] = None
        
        # Flask app
        self.app = Flask(__name__)
        self._setup_routes()
        
        print(f"[INFO] FollowRobotApp initialized")
        print(f"[INFO] Camera: {'enabled' if use_camera else 'disabled (mock mode)'}")
        print(f"[INFO] VLM: {'enabled' if use_vlm else 'disabled'}")
        print(f"[INFO] Target distance: {target_distance}m")

    def _setup_routes(self):
        """Set up Flask HTTP routes."""
        
        @self.app.route('/start', methods=['POST'])
        def start_following():
            data = request.get_json(silent=True) or {}
            description = data.get('description')
            
            if description:
                # Use VLM to identify target
                frame = self.tracker.latest_frame
                persons = self.tracker.persons
                
                if frame is not None and persons:
                    result = self.identifier.identify_person(description, frame, persons)
                    if result.success:
                        self.controller.set_target_person(result.person_id)
                        self.controller.start(target_description=description)
                        return jsonify({
                            'status': 'ok',
                            'message': 'Started following',
                            'target': description,
                            'person_id': result.person_id,
                            'confidence': result.confidence
                        })
                    else:
                        self.controller.start(target_description=description)
                        return jsonify({
                            'status': 'ok',
                            'message': 'Started following (target not yet identified)',
                            'target': description,
                            'reasoning': result.reasoning
                        })
                else:
                    self.controller.start(target_description=description)
                    return jsonify({
                        'status': 'ok',
                        'message': 'Started following (no persons visible yet)',
                        'target': description
                    })
            else:
                self.controller.start()
                return jsonify({
                    'status': 'ok',
                    'message': 'Started following closest person'
                })

        @self.app.route('/stop', methods=['POST'])
        def stop_following():
            self.controller.stop()
            return jsonify({
                'status': 'ok',
                'message': 'Stopped following'
            })

        @self.app.route('/set_target', methods=['POST'])
        def set_target():
            data = request.get_json(silent=True) or {}
            description = data.get('description')
            
            if not description:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing description parameter'
                }), 400
            
            frame = self.tracker.latest_frame
            persons = self.tracker.persons
            
            if frame is None or not persons:
                return jsonify({
                    'status': 'error',
                    'message': 'No persons detected'
                }), 404
            
            result = self.identifier.identify_person(description, frame, persons)
            
            if result.success:
                self.controller.set_target_person(result.person_id)
                self.controller.target_description = description
                return jsonify({
                    'status': 'ok',
                    'person_id': result.person_id,
                    'confidence': result.confidence,
                    'reasoning': result.reasoning
                })
            else:
                return jsonify({
                    'status': 'error',
                    'message': 'Could not identify target',
                    'reasoning': result.reasoning
                }), 404

        @self.app.route('/set_distance', methods=['POST'])
        def set_distance():
            data = request.get_json(silent=True) or {}
            distance = data.get('distance')
            
            if distance is None:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing distance parameter'
                }), 400
            
            try:
                distance = float(distance)
            except ValueError:
                return jsonify({
                    'status': 'error',
                    'message': 'Invalid distance value'
                }), 400
            
            self.controller.set_target_distance(distance)
            return jsonify({
                'status': 'ok',
                'target_distance': self.controller.config.target_distance
            })

        @self.app.route('/status', methods=['GET'])
        def get_status():
            persons = self.tracker.persons
            target_person = self._get_target_person()
            
            status = self.controller.get_status()
            status['tracking'] = target_person is not None
            status['current_distance'] = target_person.z if target_person else None
            status['persons_detected'] = len(persons)
            status['persons'] = [
                {
                    'id': p.id,
                    'x': round(p.x, 3),
                    'y': round(p.y, 3),
                    'z': round(p.z, 3),
                    'distance': round(p.distance, 3),
                    'confidence': round(p.confidence, 2)
                }
                for p in persons
            ]
            
            return jsonify(status)

        @self.app.route('/snapshot', methods=['GET'])
        def get_snapshot():
            frame = self.tracker.get_annotated_frame()
            persons = self.tracker.persons
            
            response = {
                'persons': []
            }
            
            # Get VLM descriptions if available
            if frame is not None and persons:
                descriptions = self.identifier.describe_persons(frame, persons)
                
                for i, p in enumerate(persons):
                    response['persons'].append({
                        'id': p.id,
                        'distance': round(p.distance, 2),
                        'x': round(p.x, 2),
                        'z': round(p.z, 2)
                    })
                
                response['description'] = descriptions
                
                # Encode frame as base64
                if CV2_AVAILABLE and frame is not None:
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    response['frame_base64'] = base64.b64encode(buffer).decode('utf-8')
            
            return jsonify(response)

        @self.app.route('/health', methods=['GET'])
        def health_check():
            return jsonify({
                'status': 'ok',
                'tracker_running': self.tracker.running,
                'controller_enabled': self.controller.enabled,
                'persons_detected': len(self.tracker.persons)
            })

    def _get_target_person(self) -> Optional[DetectedPerson]:
        """Get the current target person to follow."""
        persons = self.tracker.persons
        
        if not persons:
            return None
        
        # If we have a specific target ID, find that person
        if self.controller.target_person_id is not None:
            for p in persons:
                if p.id == self.controller.target_person_id:
                    return p
            # Target lost, clear it
            print(f"[WARN] Target Person #{self.controller.target_person_id} lost")
            
            # Try to re-identify if we have a description
            if self.controller.target_description:
                frame = self.tracker.latest_frame
                if frame is not None:
                    result = self.identifier.identify_person(
                        self.controller.target_description, frame, persons
                    )
                    if result.success:
                        self.controller.set_target_person(result.person_id)
                        print(f"[INFO] Re-identified target as Person #{result.person_id}")
                        return self.tracker.get_person_by_id(result.person_id)
        
        # Fall back to closest person
        return self.tracker.get_closest_person()

    def _control_loop(self):
        """Main control loop running at ~30 Hz."""
        print("[INFO] Control loop started")
        
        while self._running:
            try:
                # Get target person
                target = self._get_target_person()
                
                # Update controller
                twist = self.controller.update(target)
                
                # In Phase 2, this would publish to ROS2 /cmd_vel
                # For now, the controller prints to console
                
                time.sleep(1/30)  # 30 Hz
                
            except Exception as e:
                print(f"[ERROR] Control loop error: {e}")
                time.sleep(0.1)
        
        print("[INFO] Control loop stopped")

    def run(self):
        """Start the application."""
        print("\n" + "="*60)
        print("  RealSense Person Follow Demo - Phase 1")
        print("  OpenClaw Integration Ready")
        print("="*60)
        print(f"\n  HTTP API: http://localhost:{self.port}")
        print("  Endpoints: /start, /stop, /set_target, /set_distance, /status, /snapshot")
        print("\n  Press Ctrl+C to stop\n")
        print("="*60 + "\n")
        
        # Start tracker
        self.tracker.start()
        
        # Start control loop
        self._running = True
        self._control_thread = threading.Thread(target=self._control_loop, daemon=True)
        self._control_thread.start()
        
        # Start Flask (blocking)
        # Using threaded=True allows handling multiple requests
        # Setting use_reloader=False prevents double-starting in debug mode
        self.app.run(
            host='0.0.0.0',
            port=self.port,
            threaded=True,
            use_reloader=False
        )

    def stop(self):
        """Stop the application."""
        print("\n[INFO] Shutting down...")
        
        self._running = False
        
        if self._control_thread:
            self._control_thread.join(timeout=1.0)
        
        self.controller.stop()
        self.tracker.stop()
        
        print("[INFO] Shutdown complete")


def main():
    """Entry point when run as module."""
    app = FollowRobotApp()
    try:
        app.run()
    except KeyboardInterrupt:
        app.stop()


if __name__ == '__main__':
    main()
