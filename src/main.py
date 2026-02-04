"""
FollowRobotApp - Main Application

Ties together PersonTracker, PersonIdentifier, and FollowerController.
Exposes HTTP API for OpenClaw integration.

Features:
- Real-time person tracking at 30Hz
- VLM-based person identification
- Autonomous mission execution
- Scene analysis via VLM
- Event webhooks to OpenClaw
"""

import time
import threading
import base64
import json
import requests
from typing import Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from flask import Flask, request, jsonify

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

from .person_tracker import PersonTracker, DetectedPerson
from .person_identifier import PersonIdentifier
from .follower_controller import FollowerController, ControllerConfig


class MissionStatus(Enum):
    """Status of an autonomous mission."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Mission:
    """Represents an autonomous mission."""
    id: str
    goal: str
    status: MissionStatus = MissionStatus.IDLE
    steps_completed: list = field(default_factory=list)
    current_step: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    result: str = ""
    error: str = ""


@dataclass
class EventConfig:
    """Configuration for event webhooks."""
    webhook_url: str = "http://localhost:18789/webhook"
    enabled: bool = True
    events: list = field(default_factory=lambda: [
        "person_lost", "person_found", "mission_completed", 
        "mission_failed", "target_reached", "obstacle_detected"
    ])


class FollowRobotApp:
    """
    Main application that coordinates person tracking, identification,
    and robot control, with HTTP API for OpenClaw.
    
    Features:
    - Real-time control loop at 30Hz
    - Autonomous mission execution
    - Event webhooks to OpenClaw
    - VLM scene analysis
    """

    def __init__(self, port: int = 5050, use_camera: bool = True,
                 use_vlm: bool = True, target_distance: float = 1.0,
                 webhook_url: str = "http://localhost:18789/webhook"):
        self.port = port
        
        # Initialize components
        self.tracker = PersonTracker(use_camera=use_camera)
        self.identifier = PersonIdentifier(use_vlm=use_vlm)
        
        config = ControllerConfig(target_distance=target_distance)
        self.controller = FollowerController(config=config)
        
        # Control loop state
        self._running = False
        self._control_thread: Optional[threading.Thread] = None
        
        # Mission system
        self._current_mission: Optional[Mission] = None
        self._mission_thread: Optional[threading.Thread] = None
        self._mission_counter = 0
        
        # Event system
        self._event_config = EventConfig(webhook_url=webhook_url)
        self._last_person_count = 0
        self._person_lost_time: Optional[float] = None
        self._target_reached_notified = False
        
        # Flask app
        self.app = Flask(__name__)
        self._setup_routes()
        
        print(f"[INFO] FollowRobotApp initialized")
        print(f"[INFO] Camera: {'enabled' if use_camera else 'disabled (mock mode)'}")
        print(f"[INFO] VLM: {'enabled' if use_vlm else 'disabled'}")
        print(f"[INFO] Target distance: {target_distance}m")
        print(f"[INFO] Webhook URL: {webhook_url}")

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

        # ============================================
        # NEW: Mission System
        # ============================================
        
        @self.app.route('/mission', methods=['POST'])
        def start_mission():
            """Start an autonomous mission with a goal description."""
            data = request.get_json(silent=True) or {}
            goal = data.get('goal')
            
            if not goal:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing goal parameter'
                }), 400
            
            # Check if mission already running
            if self._current_mission and self._current_mission.status == MissionStatus.RUNNING:
                return jsonify({
                    'status': 'error',
                    'message': 'A mission is already running',
                    'current_mission': self._get_mission_status()
                }), 409
            
            # Create new mission
            self._mission_counter += 1
            mission = Mission(
                id=f"mission_{self._mission_counter}",
                goal=goal,
                status=MissionStatus.RUNNING,
                started_at=time.time()
            )
            self._current_mission = mission
            
            # Start mission in background thread
            self._mission_thread = threading.Thread(
                target=self._execute_mission, 
                args=(mission,),
                daemon=True
            )
            self._mission_thread.start()
            
            return jsonify({
                'status': 'ok',
                'message': 'Mission started',
                'mission_id': mission.id,
                'goal': goal
            })

        @self.app.route('/mission', methods=['GET'])
        def get_mission_status():
            """Get current mission status."""
            return jsonify(self._get_mission_status())

        @self.app.route('/mission/cancel', methods=['POST'])
        def cancel_mission():
            """Cancel the current mission."""
            if not self._current_mission:
                return jsonify({
                    'status': 'ok',
                    'message': 'No active mission'
                })
            
            if self._current_mission.status == MissionStatus.RUNNING:
                self._current_mission.status = MissionStatus.CANCELLED
                self._current_mission.completed_at = time.time()
                self._current_mission.result = "Mission cancelled by user"
                self.controller.stop()
            
            return jsonify({
                'status': 'ok',
                'message': 'Mission cancelled',
                'mission': self._get_mission_status()
            })

        # ============================================
        # NEW: VLM Scene Analysis
        # ============================================
        
        @self.app.route('/analyze', methods=['POST'])
        def analyze_scene():
            """
            Analyze the current scene with a custom prompt.
            
            Use for questions like:
            - "Is the person heading toward the exit?"
            - "Are there obstacles between me and the target?"
            - "What is happening in the scene?"
            """
            data = request.get_json(silent=True) or {}
            prompt = data.get('prompt') or data.get('question')
            
            if not prompt:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing prompt parameter'
                }), 400
            
            frame = self.tracker.latest_frame
            persons = self.tracker.persons
            
            if frame is None:
                return jsonify({
                    'status': 'error',
                    'message': 'No camera frame available'
                }), 503
            
            # Use VLM to analyze
            analysis = self.identifier.analyze_scene(frame, persons, prompt)
            
            return jsonify({
                'status': 'ok',
                'prompt': prompt,
                'analysis': analysis,
                'persons_detected': len(persons),
                'timestamp': time.time()
            })

        # ============================================
        # NEW: Event Webhook Configuration
        # ============================================
        
        @self.app.route('/events', methods=['GET'])
        def get_events_config():
            """Get current event webhook configuration."""
            return jsonify({
                'webhook_url': self._event_config.webhook_url,
                'enabled': self._event_config.enabled,
                'events': self._event_config.events
            })

        @self.app.route('/events', methods=['POST'])
        def configure_events():
            """Configure event webhooks."""
            data = request.get_json(silent=True) or {}
            
            if 'webhook_url' in data:
                self._event_config.webhook_url = data['webhook_url']
            if 'enabled' in data:
                self._event_config.enabled = bool(data['enabled'])
            if 'events' in data:
                self._event_config.events = data['events']
            
            return jsonify({
                'status': 'ok',
                'config': {
                    'webhook_url': self._event_config.webhook_url,
                    'enabled': self._event_config.enabled,
                    'events': self._event_config.events
                }
            })

        @self.app.route('/events/test', methods=['POST'])
        def test_webhook():
            """Send a test event to the webhook."""
            success = self._post_event("test", {
                "message": "Test event from follow-robot",
                "timestamp": time.time()
            })
            
            return jsonify({
                'status': 'ok' if success else 'error',
                'message': 'Test event sent' if success else 'Failed to send event',
                'webhook_url': self._event_config.webhook_url
            })

        # ============================================
        # NEW: Manual Teleoperation Control
        # ============================================

        @self.app.route('/move', methods=['POST'])
        def move():
            """
            Move the robot forward or backward.
            
            Parameters:
            - distance: Distance in meters (positive=forward, negative=backward)
            - velocity: Optional speed in m/s (default: 0.3)
            - duration: Alternative - move for this many seconds
            """
            data = request.get_json(silent=True) or {}
            
            distance = data.get('distance')
            duration = data.get('duration')
            velocity = data.get('velocity', 0.3)
            
            if distance is not None:
                result = self.controller.move(float(distance), float(velocity))
            elif duration is not None:
                result = self.controller.move_for_time(float(duration), float(velocity))
            else:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing distance or duration parameter'
                }), 400
            
            return jsonify(result)

        @self.app.route('/turn', methods=['POST'])
        def turn():
            """
            Turn the robot left or right.
            
            Parameters:
            - angle: Angle in degrees (positive=left/CCW, negative=right/CW)
            - angular_velocity: Optional turn speed in rad/s (default: 0.5)
            """
            data = request.get_json(silent=True) or {}
            
            angle = data.get('angle')
            
            if angle is None:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing angle parameter'
                }), 400
            
            angular_vel = data.get('angular_velocity', 0.5)
            result = self.controller.turn(float(angle), float(angular_vel))
            
            return jsonify(result)

        @self.app.route('/velocity', methods=['POST'])
        def set_velocity():
            """
            Set raw velocity command.
            
            Parameters:
            - linear: Linear velocity in m/s (forward/backward)
            - angular: Angular velocity in rad/s (turning)
            - duration: Optional duration in seconds
            """
            data = request.get_json(silent=True) or {}
            
            linear = data.get('linear', 0.0)
            angular = data.get('angular', 0.0)
            duration = data.get('duration')
            
            result = self.controller.set_velocity(
                float(linear), 
                float(angular), 
                float(duration) if duration else None
            )
            
            return jsonify(result)

        @self.app.route('/sequence', methods=['POST'])
        def execute_sequence():
            """
            Execute a sequence of movement commands.
            
            Parameters:
            - commands: List of command objects, e.g.:
                [
                    {"type": "move", "distance": 1.0},
                    {"type": "turn", "angle": -90},
                    {"type": "move", "distance": 2.0},
                    {"type": "wait", "duration": 1.0}
                ]
            """
            data = request.get_json(silent=True) or {}
            
            commands = data.get('commands', [])
            
            if not commands:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing commands array'
                }), 400
            
            result = self.controller.execute_sequence(commands)
            
            return jsonify(result)

        @self.app.route('/teleop', methods=['POST'])
        def teleop():
            """
            Parse natural language movement command.
            
            Parameters:
            - command: Natural language command like:
                - "move forward 1 meter"
                - "turn left 90 degrees"
                - "go backward for 2 seconds"
                - "move forward 1 meter, turn left, then go forward for 5 seconds"
            """
            data = request.get_json(silent=True) or {}
            
            command = data.get('command', '')
            
            if not command:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing command parameter'
                }), 400
            
            # Parse the command
            commands = self._parse_teleop_command(command)
            
            if not commands:
                return jsonify({
                    'status': 'error',
                    'message': f'Could not parse command: {command}'
                }), 400
            
            # Execute the parsed commands
            if len(commands) == 1:
                cmd = commands[0]
                if cmd['type'] == 'move':
                    if 'duration' in cmd:
                        result = self.controller.move_for_time(cmd['duration'], cmd.get('velocity', 0.3))
                    else:
                        result = self.controller.move(cmd.get('distance', 1.0), cmd.get('velocity', 0.3))
                elif cmd['type'] == 'turn':
                    result = self.controller.turn(cmd.get('angle', 90))
                elif cmd['type'] == 'stop':
                    self.controller.stop()
                    result = {'status': 'ok', 'message': 'Stopped'}
                else:
                    result = {'status': 'error', 'message': f'Unknown command type: {cmd["type"]}'}
            else:
                result = self.controller.execute_sequence(commands)
            
            result['parsed_commands'] = commands
            return jsonify(result)

        @self.app.route('/manual/status', methods=['GET'])
        def get_manual_status():
            """Get status of manual control."""
            return jsonify(self.controller.get_manual_status())

        # ============================================
        # NEW: Object Detection and Approach
        # ============================================

        @self.app.route('/find_object', methods=['POST'])
        def find_object():
            """
            Find an object in the scene using VLM.
            
            Parameters:
            - object: Description of object to find (e.g., "red chair", "water bottle")
            """
            data = request.get_json(silent=True) or {}
            
            obj_description = data.get('object') or data.get('description')
            
            if not obj_description:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing object parameter'
                }), 400
            
            frame = self.tracker.latest_frame
            
            if frame is None:
                return jsonify({
                    'status': 'error',
                    'message': 'No camera frame available'
                }), 503
            
            result = self.identifier.find_object(frame, obj_description)
            result['status'] = 'ok' if result['found'] else 'not_found'
            
            return jsonify(result)

        @self.app.route('/approach_object', methods=['POST'])
        def approach_object():
            """
            Find and approach an object.
            
            Parameters:
            - object: Description of object to approach
            - distance: Target distance from object in meters (default: 0.5)
            """
            data = request.get_json(silent=True) or {}
            
            obj_description = data.get('object') or data.get('description')
            target_distance = data.get('distance', 0.5)
            
            if not obj_description:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing object parameter'
                }), 400
            
            frame = self.tracker.latest_frame
            
            if frame is None:
                return jsonify({
                    'status': 'error',
                    'message': 'No camera frame available'
                }), 503
            
            # Find the object
            result = self.identifier.find_object(frame, obj_description)
            
            if not result['found']:
                return jsonify({
                    'status': 'not_found',
                    'message': f"Could not find: {obj_description}",
                    'reason': result.get('reason', 'Object not visible')
                }), 404
            
            # Calculate approach commands
            turn_angle, est_distance, _ = self.identifier.get_object_direction(frame, obj_description)
            
            # Build command sequence
            commands = []
            
            # First, turn to face the object
            if abs(turn_angle) > 5:  # Only turn if > 5 degrees off
                commands.append({
                    'type': 'turn',
                    'angle': turn_angle
                })
            
            # Then move toward it (leave some margin)
            move_distance = max(0, est_distance - target_distance)
            if move_distance > 0.1:  # Only move if > 10cm away
                commands.append({
                    'type': 'move',
                    'distance': move_distance
                })
            
            if commands:
                self.controller.execute_sequence(commands)
                return jsonify({
                    'status': 'ok',
                    'message': f"Approaching {obj_description}",
                    'object': result,
                    'commands': commands,
                    'turn_angle': turn_angle,
                    'estimated_distance': est_distance,
                    'move_distance': move_distance
                })
            else:
                return jsonify({
                    'status': 'ok',
                    'message': f"Already close to {obj_description}",
                    'object': result
                })

        @self.app.route('/look_for', methods=['POST'])
        def look_for():
            """
            Scan the environment looking for an object by rotating.
            
            Parameters:
            - object: Description of object to find
            - max_rotations: Maximum full rotations to make (default: 1)
            """
            data = request.get_json(silent=True) or {}
            
            obj_description = data.get('object') or data.get('description')
            max_rotations = data.get('max_rotations', 1)
            
            if not obj_description:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing object parameter'
                }), 400
            
            # Start a search mission
            goal = f"scan and find {obj_description}"
            
            # Check if already visible
            frame = self.tracker.latest_frame
            if frame is not None:
                result = self.identifier.find_object(frame, obj_description)
                if result['found']:
                    return jsonify({
                        'status': 'found',
                        'message': f"Found {obj_description} immediately",
                        'object': result
                    })
            
            # Not visible - start rotating search
            # Queue turn commands with checks in between
            commands = []
            turn_increment = 45  # degrees
            total_turns = int(360 * max_rotations / turn_increment)
            
            for i in range(total_turns):
                commands.append({
                    'type': 'turn',
                    'angle': turn_increment
                })
                commands.append({
                    'type': 'wait',
                    'duration': 0.5  # Pause to check
                })
            
            self.controller.execute_sequence(commands)
            
            return jsonify({
                'status': 'searching',
                'message': f"Scanning for {obj_description}",
                'object': obj_description,
                'search_pattern': f"{total_turns} turns of {turn_increment}°",
                'note': 'Check /find_object periodically to see if object is found'
            })

        @self.app.route('/objects', methods=['GET'])
        def list_objects():
            """
            List all visible objects in the scene using VLM.
            """
            frame = self.tracker.latest_frame
            
            if frame is None:
                return jsonify({
                    'status': 'error',
                    'message': 'No camera frame available'
                }), 503
            
            # Use VLM to describe all objects
            prompt = """List all distinct objects you can see in this image.
For each object, provide:
- Object name
- Position (left, center, right)
- Approximate distance (close, medium, far)

Format each object on its own line like: "Object: position, distance"
Example: "Chair: left, medium"

List only clearly visible objects:"""

            analysis = self.identifier.analyze_scene(frame, [], prompt)
            
            # Parse the response into structured data
            objects = []
            for line in analysis.split('\n'):
                line = line.strip()
                if ':' in line and line:
                    parts = line.split(':')
                    obj_name = parts[0].strip().strip('-').strip('•').strip()
                    if obj_name and len(obj_name) > 1:
                        details = parts[1].strip() if len(parts) > 1 else ''
                        objects.append({
                            'name': obj_name,
                            'details': details
                        })
            
            return jsonify({
                'status': 'ok',
                'objects': objects,
                'count': len(objects),
                'raw_description': analysis
            })

        @self.app.route('/find_and_follow', methods=['POST'])
        def find_and_follow_object():
            """
            Search for an object, and once found, approach and optionally track it.
            
            If the object is not visible, rotates to search for it.
            Once found, approaches and can continue tracking.
            
            Parameters:
            - object: Description of object to find and follow
            - distance: Target distance from object in meters (default: 0.5)
            - track: Keep tracking after reaching (default: true)
            - max_search_rotations: Max full rotations to search (default: 1.5)
            """
            data = request.get_json(silent=True) or {}
            
            obj_description = data.get('object') or data.get('description')
            target_distance = data.get('distance', 0.5)
            track = data.get('track', True)
            max_rotations = data.get('max_search_rotations', 1.5)
            
            if not obj_description:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing object parameter'
                }), 400
            
            # Check if mission already running
            if self._current_mission and self._current_mission.status == MissionStatus.RUNNING:
                return jsonify({
                    'status': 'error',
                    'message': 'A mission is already running. Cancel it first.',
                    'current_mission': self._get_mission_status()
                }), 409
            
            # Create mission
            self._mission_counter += 1
            mission = Mission(
                id=f"find_follow_{self._mission_counter}",
                goal=f"find and follow {obj_description}",
                status=MissionStatus.RUNNING,
                started_at=time.time()
            )
            self._current_mission = mission
            
            # Start mission in background
            self._mission_thread = threading.Thread(
                target=self._mission_find_and_follow_object,
                args=(mission, obj_description, target_distance, track, max_rotations),
                daemon=True
            )
            self._mission_thread.start()
            
            return jsonify({
                'status': 'ok',
                'message': f'Searching for {obj_description}...',
                'mission_id': mission.id,
                'object': obj_description,
                'target_distance': target_distance,
                'tracking': track
            })

    def _parse_teleop_command(self, command: str) -> list[dict]:
        """Parse a natural language teleop command into structured commands."""
        import re
        
        commands = []
        command_lower = command.lower()
        
        # Split on "then", "and then", commas, "and"
        parts = re.split(r',\s*(?:and\s+)?then\s+|,\s*then\s+|,\s*and\s+|,\s+|\s+then\s+|\s+and\s+then\s+', command_lower)
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            cmd = None
            
            # Stop command
            if re.search(r'\b(stop|halt|freeze)\b', part):
                cmd = {'type': 'stop'}
            
            # Move forward/backward
            elif re.search(r'\b(move|go|drive)\b', part):
                # Check direction
                direction = 1.0  # forward by default
                if re.search(r'\b(back|backward|backwards|reverse)\b', part):
                    direction = -1.0
                
                # Check for distance
                dist_match = re.search(r'(\d+\.?\d*)\s*(m|meter|meters|metre|metres|cm|centimeter|centimeters)\b', part)
                if dist_match:
                    distance = float(dist_match.group(1))
                    unit = dist_match.group(2)
                    if 'cm' in unit or 'centimeter' in unit:
                        distance /= 100
                    cmd = {'type': 'move', 'distance': distance * direction}
                
                # Check for duration
                elif re.search(r'(\d+\.?\d*)\s*(s|sec|second|seconds)\b', part):
                    dur_match = re.search(r'(\d+\.?\d*)\s*(s|sec|second|seconds)\b', part)
                    duration = float(dur_match.group(1))
                    velocity = 0.3 * direction
                    cmd = {'type': 'move', 'duration': duration, 'velocity': velocity}
                
                # Default: move 1 meter
                else:
                    cmd = {'type': 'move', 'distance': 1.0 * direction}
            
            # Turn left/right
            elif re.search(r'\b(turn|rotate|spin)\b', part):
                # Check direction
                angle = 90  # default 90 degrees
                if re.search(r'\bright\b', part):
                    angle = -90
                elif re.search(r'\bleft\b', part):
                    angle = 90
                elif re.search(r'\baround\b', part):
                    angle = 180
                
                # Check for specific angle
                angle_match = re.search(r'(\d+\.?\d*)\s*(deg|degree|degrees|°)?\b', part)
                if angle_match:
                    parsed_angle = float(angle_match.group(1))
                    if re.search(r'\bright\b', part):
                        parsed_angle = -parsed_angle
                    angle = parsed_angle
                
                cmd = {'type': 'turn', 'angle': angle}
            
            # Wait/pause
            elif re.search(r'\b(wait|pause|delay)\b', part):
                dur_match = re.search(r'(\d+\.?\d*)\s*(s|sec|second|seconds)\b', part)
                duration = float(dur_match.group(1)) if dur_match else 1.0
                cmd = {'type': 'wait', 'duration': duration}
            
            if cmd:
                commands.append(cmd)
        
        return commands

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

    def _get_mission_status(self) -> dict:
        """Get the current mission status as a dict."""
        if not self._current_mission:
            return {
                'status': 'idle',
                'message': 'No mission active'
            }
        
        m = self._current_mission
        return {
            'mission_id': m.id,
            'goal': m.goal,
            'status': m.status.value,
            'current_step': m.current_step,
            'steps_completed': m.steps_completed,
            'started_at': m.started_at,
            'completed_at': m.completed_at if m.completed_at else None,
            'duration': (m.completed_at or time.time()) - m.started_at,
            'result': m.result,
            'error': m.error
        }

    def _execute_mission(self, mission: Mission):
        """
        Execute an autonomous mission.
        
        This runs in a background thread and breaks down the goal
        into steps, executing them sequentially.
        """
        print(f"[MISSION] Starting: {mission.goal}")
        
        try:
            # Parse the mission goal using VLM
            mission.current_step = "Analyzing goal..."
            
            # Simple goal parsing based on keywords
            goal_lower = mission.goal.lower()
            
            # Example mission types:
            if "follow" in goal_lower and "until" in goal_lower:
                # "Follow person X until Y happens"
                self._mission_follow_until(mission)
            elif "find" in goal_lower:
                # "Find a person wearing X"
                self._mission_find_person(mission)
            elif "patrol" in goal_lower or "scan" in goal_lower:
                # "Patrol the area" or "Scan for people"
                self._mission_patrol(mission)
            elif "approach" in goal_lower or "go to" in goal_lower:
                # "Approach the person in red"
                self._mission_approach(mission)
            else:
                # Generic follow mission
                self._mission_generic_follow(mission)
            
        except Exception as e:
            mission.status = MissionStatus.FAILED
            mission.error = str(e)
            mission.completed_at = time.time()
            print(f"[MISSION] Failed: {e}")
            self._post_event("mission_failed", {
                "mission_id": mission.id,
                "goal": mission.goal,
                "error": str(e)
            })

    def _mission_follow_until(self, mission: Mission):
        """Follow a person until a condition is met."""
        import re
        
        # Parse "follow X until Y"
        match = re.search(r'follow\s+(.+?)\s+until\s+(.+)', mission.goal, re.IGNORECASE)
        if not match:
            mission.current_step = "Starting generic follow"
            self._mission_generic_follow(mission)
            return
        
        target_desc = match.group(1).strip()
        condition = match.group(2).strip()
        
        mission.steps_completed.append(f"Parsed target: {target_desc}")
        mission.steps_completed.append(f"Stop condition: {condition}")
        
        # Start following
        mission.current_step = f"Identifying target: {target_desc}"
        frame = self.tracker.latest_frame
        persons = self.tracker.persons
        
        if frame is not None and persons:
            result = self.identifier.identify_person(target_desc, frame, persons)
            if result.success:
                self.controller.set_target_person(result.person_id)
                mission.steps_completed.append(f"Identified Person #{result.person_id}")
        
        self.controller.start(target_description=target_desc)
        mission.current_step = f"Following {target_desc}"
        mission.steps_completed.append("Started following")
        
        # Monitor for stop condition
        check_interval = 2.0  # Check every 2 seconds
        max_duration = 300.0  # Max 5 minutes
        start_time = time.time()
        
        while mission.status == MissionStatus.RUNNING:
            if time.time() - start_time > max_duration:
                mission.result = "Mission timeout - max duration reached"
                break
            
            # Check condition using VLM
            frame = self.tracker.latest_frame
            if frame is not None:
                analysis = self.identifier.analyze_scene(
                    frame, 
                    self.tracker.persons,
                    f"Is this condition true: '{condition}'? Answer YES or NO and explain briefly."
                )
                
                if analysis and 'YES' in analysis.upper():
                    mission.steps_completed.append(f"Condition met: {condition}")
                    mission.result = f"Condition '{condition}' detected"
                    break
            
            time.sleep(check_interval)
        
        # Stop following
        self.controller.stop()
        mission.status = MissionStatus.COMPLETED
        mission.completed_at = time.time()
        mission.steps_completed.append("Stopped following")
        
        print(f"[MISSION] Completed: {mission.result}")
        self._post_event("mission_completed", {
            "mission_id": mission.id,
            "goal": mission.goal,
            "result": mission.result,
            "duration": mission.completed_at - mission.started_at
        })

    def _mission_find_person(self, mission: Mission):
        """Find a person matching a description."""
        import re
        
        # Parse "find a person wearing X" or "find the person in X"
        match = re.search(r'find\s+(?:a\s+)?(?:person\s+)?(?:wearing\s+|in\s+)?(.+)', 
                         mission.goal, re.IGNORECASE)
        target_desc = match.group(1).strip() if match else mission.goal
        
        mission.current_step = f"Searching for: {target_desc}"
        mission.steps_completed.append(f"Target description: {target_desc}")
        
        # Search loop
        max_duration = 60.0  # Max 1 minute search
        check_interval = 1.0
        start_time = time.time()
        
        while mission.status == MissionStatus.RUNNING:
            if time.time() - start_time > max_duration:
                mission.status = MissionStatus.FAILED
                mission.error = "Person not found within time limit"
                mission.completed_at = time.time()
                self._post_event("mission_failed", {
                    "mission_id": mission.id,
                    "error": "Person not found"
                })
                return
            
            frame = self.tracker.latest_frame
            persons = self.tracker.persons
            
            if frame is not None and persons:
                result = self.identifier.identify_person(target_desc, frame, persons)
                if result.success and result.confidence > 0.6:
                    mission.steps_completed.append(f"Found Person #{result.person_id}")
                    mission.result = f"Found person matching '{target_desc}' - Person #{result.person_id}"
                    
                    # Start following them
                    self.controller.set_target_person(result.person_id)
                    self.controller.start(target_description=target_desc)
                    mission.steps_completed.append("Started following")
                    
                    mission.status = MissionStatus.COMPLETED
                    mission.completed_at = time.time()
                    
                    self._post_event("mission_completed", {
                        "mission_id": mission.id,
                        "goal": mission.goal,
                        "person_id": result.person_id
                    })
                    return
            
            time.sleep(check_interval)

    def _mission_patrol(self, mission: Mission):
        """Patrol/scan mode - report on all detected persons."""
        mission.current_step = "Scanning area..."
        mission.steps_completed.append("Started patrol scan")
        
        # Collect observations over time
        observations = []
        scan_duration = 10.0  # Scan for 10 seconds
        start_time = time.time()
        
        while time.time() - start_time < scan_duration:
            if mission.status != MissionStatus.RUNNING:
                return
            
            persons = self.tracker.persons
            frame = self.tracker.latest_frame
            
            if persons and frame is not None:
                desc = self.identifier.describe_persons(frame, persons)
                observations.append({
                    "time": time.time() - start_time,
                    "count": len(persons),
                    "description": desc
                })
            
            time.sleep(2.0)
        
        mission.result = f"Scan complete. Observed {len(observations)} snapshots."
        mission.steps_completed.append(f"Collected {len(observations)} observations")
        
        if observations:
            latest = observations[-1]
            mission.result += f" Latest: {latest['count']} person(s) detected."
        
        mission.status = MissionStatus.COMPLETED
        mission.completed_at = time.time()
        
        self._post_event("mission_completed", {
            "mission_id": mission.id,
            "goal": mission.goal,
            "observations": len(observations)
        })

    def _mission_approach(self, mission: Mission):
        """Approach a specific person until within target distance."""
        import re
        
        match = re.search(r'(?:approach|go to)\s+(?:the\s+)?(.+)', mission.goal, re.IGNORECASE)
        target_desc = match.group(1).strip() if match else "closest person"
        
        mission.current_step = f"Approaching: {target_desc}"
        
        # Identify and start following
        frame = self.tracker.latest_frame
        persons = self.tracker.persons
        
        if frame is not None and persons:
            result = self.identifier.identify_person(target_desc, frame, persons)
            if result.success:
                self.controller.set_target_person(result.person_id)
                mission.steps_completed.append(f"Identified Person #{result.person_id}")
        
        self.controller.start(target_description=target_desc)
        mission.steps_completed.append("Started approach")
        
        # Monitor until we reach target distance
        target_dist = self.controller.config.target_distance
        tolerance = 0.15  # 15cm tolerance
        max_duration = 60.0
        start_time = time.time()
        
        while mission.status == MissionStatus.RUNNING:
            if time.time() - start_time > max_duration:
                mission.result = "Approach timeout"
                break
            
            target = self._get_target_person()
            if target and abs(target.z - target_dist) < tolerance:
                mission.result = f"Reached target distance ({target.z:.2f}m)"
                mission.steps_completed.append("Target distance reached")
                self._post_event("target_reached", {
                    "distance": target.z,
                    "target_distance": target_dist
                })
                break
            
            time.sleep(0.5)
        
        self.controller.stop()
        mission.status = MissionStatus.COMPLETED
        mission.completed_at = time.time()
        
        self._post_event("mission_completed", {
            "mission_id": mission.id,
            "result": mission.result
        })

    def _mission_find_and_follow_person(self, mission: Mission, description: str,
                                          target_distance: float, track: bool,
                                          max_rotations: float):
        """
        Find and follow a person using MediaPipe tracker (much more reliable than VLM).
        """
        print(f"[MISSION] Find and follow person: {description}")
        
        try:
            # Update target distance
            self.controller.set_target_distance(target_distance)
            
            # Phase 1: Search for person
            mission.current_step = "Searching for person..."
            
            found = False
            total_rotation = 0
            turn_increment = 30
            max_search_degrees = 360 * max_rotations
            
            while not found and mission.status == MissionStatus.RUNNING:
                # Check if any person is detected by MediaPipe
                persons = self.tracker.persons
                
                if persons:
                    found = True
                    person = persons[0]  # Take closest/first person
                    mission.steps_completed.append(
                        f"Found person at {person.z:.1f}m away"
                    )
                    print(f"[MISSION] Found person at {person.z:.1f}m")
                    break
                
                # Not found - rotate to search
                if total_rotation >= max_search_degrees:
                    mission.status = MissionStatus.FAILED
                    mission.error = "Could not find any person after searching"
                    mission.completed_at = time.time()
                    mission.result = "Person not found"
                    
                    self._post_event("mission_failed", {
                        "mission_id": mission.id,
                        "reason": "Person not found",
                        "searched_degrees": total_rotation
                    })
                    return
                
                # Turn and search
                mission.current_step = f"Scanning for person... ({int(total_rotation)}° searched)"
                self.controller.turn(turn_increment)
                time.sleep(1.5)
                total_rotation += turn_increment
            
            if not found or mission.status != MissionStatus.RUNNING:
                return
            
            # Phase 2: Start following using the existing follow system
            mission.current_step = "Following person"
            mission.steps_completed.append("Started following")
            
            # Use the built-in person following system
            self.controller.start(target_description=description)
            
            if track:
                # Phase 3: Track until cancelled or timeout
                mission.current_step = "Tracking person"
                track_start = time.time()
                max_track_time = 120.0  # 2 minutes max
                
                while mission.status == MissionStatus.RUNNING:
                    if time.time() - track_start > max_track_time:
                        mission.result = "Tracking time limit reached"
                        break
                    
                    # Check if we still see the person
                    target = self._get_target_person()
                    if target is None:
                        # Lost person - wait a bit and check again
                        time.sleep(1.0)
                        target = self._get_target_person()
                        if target is None:
                            mission.steps_completed.append("Person lost")
                            # Could add re-search logic here
                    
                    time.sleep(0.5)
            else:
                # Just approach once and stop
                approach_start = time.time()
                max_approach_time = 30.0
                
                while mission.status == MissionStatus.RUNNING:
                    if time.time() - approach_start > max_approach_time:
                        break
                    
                    target = self._get_target_person()
                    if target and abs(target.z - target_distance) < 0.2:
                        mission.steps_completed.append(f"Reached target distance ({target.z:.1f}m)")
                        break
                    
                    time.sleep(0.5)
                
                self.controller.stop()
            
            # Mission complete
            mission.status = MissionStatus.COMPLETED
            mission.completed_at = time.time()
            mission.result = f"Successfully {'tracked' if track else 'reached'} person"
            
            self._post_event("mission_completed", {
                "mission_id": mission.id,
                "description": description,
                "duration": mission.completed_at - mission.started_at
            })
            
            print(f"[MISSION] Completed: {mission.result}")
            
        except Exception as e:
            mission.status = MissionStatus.FAILED
            mission.error = str(e)
            mission.completed_at = time.time()
            print(f"[MISSION] Error: {e}")
            self.controller.stop()
            
            self._post_event("mission_failed", {
                "mission_id": mission.id,
                "error": str(e)
            })

    def _mission_generic_follow(self, mission: Mission):
        """Generic follow mission - follow for a set duration or until cancelled."""
        mission.current_step = "Starting follow mode"
        
        self.controller.start()
        mission.steps_completed.append("Started following")
        
        # Follow for max 2 minutes or until cancelled
        max_duration = 120.0
        start_time = time.time()
        
        while mission.status == MissionStatus.RUNNING:
            if time.time() - start_time > max_duration:
                mission.result = "Follow duration completed"
                break
            time.sleep(1.0)
        
        self.controller.stop()
        mission.status = MissionStatus.COMPLETED
        mission.completed_at = time.time()
        mission.steps_completed.append("Stopped following")
        
        self._post_event("mission_completed", {
            "mission_id": mission.id,
            "duration": time.time() - start_time
        })

    def _mission_find_and_follow_object(self, mission: Mission, obj_description: str,
                                         target_distance: float, track: bool, 
                                         max_rotations: float):
        """
        Find an object (searching if needed) and then approach/track it.
        
        1. Check if object is visible
        2. If not, rotate to search
        3. Once found, approach
        4. Optionally keep tracking
        """
        print(f"[MISSION] Find and follow: {obj_description}")
        
        # Check if looking for a person - use MediaPipe tracker instead of VLM
        is_person = any(word in obj_description.lower() for word in 
                       ['person', 'human', 'people', 'someone', 'somebody', 'man', 'woman', 'guy', 'girl'])
        
        if is_person:
            self._mission_find_and_follow_person(mission, obj_description, target_distance, track, max_rotations)
            return
        
        try:
            # Phase 1: Search for the object
            mission.current_step = f"Searching for {obj_description}"
            
            found = False
            search_start = time.time()
            total_rotation = 0
            turn_increment = 30  # degrees per step
            max_search_degrees = 360 * max_rotations
            
            while not found and mission.status == MissionStatus.RUNNING:
                # Check if object is visible
                frame = self.tracker.latest_frame
                if frame is not None:
                    result = self.identifier.find_object(frame, obj_description)
                    
                    if result['found']:
                        found = True
                        mission.steps_completed.append(
                            f"Found {obj_description} at {result['position']}, "
                            f"~{result['estimated_distance']:.1f}m away"
                        )
                        print(f"[MISSION] Found {obj_description} at {result['position']}")
                        break
                
                # Not found - rotate to search
                if total_rotation >= max_search_degrees:
                    mission.status = MissionStatus.FAILED
                    mission.error = f"Could not find {obj_description} after searching"
                    mission.completed_at = time.time()
                    mission.result = "Object not found"
                    
                    self._post_event("mission_failed", {
                        "mission_id": mission.id,
                        "reason": "Object not found",
                        "searched_degrees": total_rotation
                    })
                    return
                
                # Turn a bit and search again
                mission.current_step = f"Scanning... ({int(total_rotation)}° searched)"
                self.controller.turn(turn_increment)
                
                # Wait for turn to complete
                time.sleep(1.5)  # Allow time for turn + settling
                total_rotation += turn_increment
            
            if not found or mission.status != MissionStatus.RUNNING:
                return
            
            # Phase 2: Approach the object
            mission.current_step = f"Approaching {obj_description}"
            
            approach_attempts = 0
            max_approach_attempts = 10
            
            while mission.status == MissionStatus.RUNNING and approach_attempts < max_approach_attempts:
                frame = self.tracker.latest_frame
                if frame is None:
                    time.sleep(0.5)
                    continue
                
                # Get current object position
                result = self.identifier.find_object(frame, obj_description)
                
                if not result['found']:
                    # Lost the object - try to re-find
                    mission.steps_completed.append("Object lost, re-scanning...")
                    
                    # Do a small search
                    for _ in range(4):  # Check 4 directions
                        self.controller.turn(30)
                        time.sleep(1.0)
                        frame = self.tracker.latest_frame
                        if frame is not None:
                            result = self.identifier.find_object(frame, obj_description)
                            if result['found']:
                                break
                    
                    if not result['found']:
                        mission.status = MissionStatus.FAILED
                        mission.error = "Lost object during approach"
                        mission.completed_at = time.time()
                        self._post_event("mission_failed", {
                            "mission_id": mission.id,
                            "reason": "Lost object"
                        })
                        return
                
                # Calculate approach
                turn_angle, est_distance, _ = self.identifier.get_object_direction(
                    frame, obj_description
                )
                
                # Ensure we have proper floats
                turn_angle = float(turn_angle) if turn_angle else 0.0
                est_distance = float(est_distance) if est_distance else 2.0
                
                # Check if we're close enough
                if est_distance <= target_distance + 0.2:
                    mission.steps_completed.append(
                        f"Reached target distance (~{est_distance:.1f}m)"
                    )
                    print(f"[MISSION] Reached {obj_description}")
                    break
                
                # Turn to face object if needed
                if abs(turn_angle) > 10:
                    self.controller.turn(turn_angle)
                    time.sleep(0.8)
                
                # Move closer
                move_dist = min(0.5, est_distance - target_distance)
                if move_dist > 0.1:
                    self.controller.move(move_dist)
                    time.sleep(move_dist / 0.3 + 0.5)  # Wait for movement
                
                approach_attempts += 1
            
            # Phase 3: Track (if enabled)
            if track and mission.status == MissionStatus.RUNNING:
                mission.current_step = f"Tracking {obj_description}"
                mission.steps_completed.append("Started tracking")
                
                track_start = time.time()
                max_track_time = 120.0  # Track for up to 2 minutes
                
                while mission.status == MissionStatus.RUNNING:
                    if time.time() - track_start > max_track_time:
                        mission.result = "Tracking time limit reached"
                        break
                    
                    frame = self.tracker.latest_frame
                    if frame is None:
                        time.sleep(0.5)
                        continue
                    
                    result = self.identifier.find_object(frame, obj_description)
                    
                    if not result['found']:
                        # Lost it briefly, wait and check again
                        time.sleep(1.0)
                        continue
                    
                    # Adjust position to stay at target distance
                    turn_angle, est_distance, _ = self.identifier.get_object_direction(
                        frame, obj_description
                    )
                    
                    # Ensure we have proper floats
                    turn_angle = float(turn_angle) if turn_angle else 0.0
                    est_distance = float(est_distance) if est_distance else 2.0
                    
                    # Small corrections
                    if abs(turn_angle) > 15:
                        self.controller.turn(turn_angle * 0.5)  # Gentle correction
                    
                    distance_error = est_distance - target_distance
                    if abs(distance_error) > 0.3:
                        move_dist = distance_error * 0.3  # Gentle approach/retreat
                        move_dist = max(-0.2, min(0.3, move_dist))
                        if abs(move_dist) > 0.1:
                            self.controller.move(move_dist)
                    
                    time.sleep(2.0)  # Check every 2 seconds
            
            # Mission complete
            mission.status = MissionStatus.COMPLETED
            mission.completed_at = time.time()
            mission.result = f"Successfully found and {'tracked' if track else 'reached'} {obj_description}"
            
            self._post_event("mission_completed", {
                "mission_id": mission.id,
                "object": obj_description,
                "duration": mission.completed_at - mission.started_at
            })
            
            print(f"[MISSION] Completed: {mission.result}")
            
        except Exception as e:
            mission.status = MissionStatus.FAILED
            mission.error = str(e)
            mission.completed_at = time.time()
            print(f"[MISSION] Error: {e}")
            
            self._post_event("mission_failed", {
                "mission_id": mission.id,
                "error": str(e)
            })

    def _post_event(self, event_type: str, data: dict) -> bool:
        """Post an event to the webhook URL."""
        if not self._event_config.enabled:
            return False
        
        if event_type not in self._event_config.events and event_type != "test":
            return False
        
        payload = {
            "event": event_type,
            "source": "follow-robot",
            "timestamp": time.time(),
            "data": data
        }
        
        try:
            response = requests.post(
                self._event_config.webhook_url,
                json=payload,
                timeout=5.0
            )
            if response.status_code == 200:
                print(f"[EVENT] Posted: {event_type}")
                return True
            else:
                print(f"[EVENT] Failed ({response.status_code}): {event_type}")
                return False
        except Exception as e:
            print(f"[EVENT] Error posting {event_type}: {e}")
            return False

    def _check_events(self, target: Optional[DetectedPerson]):
        """Check for events to post (called from control loop)."""
        persons = self.tracker.persons
        current_count = len(persons)
        
        # Person lost event
        if self._last_person_count > 0 and current_count == 0:
            if self._person_lost_time is None:
                self._person_lost_time = time.time()
            elif time.time() - self._person_lost_time > 2.0:  # Lost for 2+ seconds
                self._post_event("person_lost", {
                    "last_count": self._last_person_count,
                    "duration": time.time() - self._person_lost_time
                })
                self._person_lost_time = None
        
        # Person found event
        if self._last_person_count == 0 and current_count > 0:
            self._post_event("person_found", {
                "count": current_count
            })
            self._person_lost_time = None
        
        # Target reached event
        if target and self.controller.enabled:
            target_dist = self.controller.config.target_distance
            if abs(target.z - target_dist) < 0.1:  # Within 10cm
                if not self._target_reached_notified:
                    self._post_event("target_reached", {
                        "distance": target.z,
                        "target": target_dist
                    })
                    self._target_reached_notified = True
            else:
                self._target_reached_notified = False
        
        self._last_person_count = current_count

    def _control_loop(self):
        """Main control loop running at ~30 Hz."""
        print("[INFO] Control loop started")
        
        event_check_counter = 0
        
        while self._running:
            try:
                # Get target person
                target = self._get_target_person()
                
                # Update controller
                twist = self.controller.update(target)
                
                # In Phase 2, this would publish to ROS2 /cmd_vel
                # For now, the controller prints to console
                
                # Check for events (at ~1 Hz)
                event_check_counter += 1
                if event_check_counter >= 30:
                    self._check_events(target)
                    event_check_counter = 0
                
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
