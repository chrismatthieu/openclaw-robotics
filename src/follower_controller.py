"""
FollowerController - Robot Follow Control Logic

Computes Twist commands (linear_x, angular_z) for a differential drive robot
to follow a target person at a specified distance.
"""

import time
from dataclasses import dataclass
from typing import Optional
import math

from .person_tracker import DetectedPerson


@dataclass
class Twist:
    """ROS-compatible Twist message structure."""
    linear_x: float = 0.0   # Forward/backward velocity (m/s)
    linear_y: float = 0.0   # Lateral velocity (m/s) - usually 0 for diff drive
    linear_z: float = 0.0   # Vertical velocity (m/s) - usually 0
    angular_x: float = 0.0  # Roll rate (rad/s) - usually 0
    angular_y: float = 0.0  # Pitch rate (rad/s) - usually 0
    angular_z: float = 0.0  # Yaw rate (rad/s) - turning

    def __repr__(self):
        return f"Twist(linear_x={self.linear_x:.3f} m/s, angular_z={self.angular_z:.3f} rad/s)"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'linear': {'x': self.linear_x, 'y': self.linear_y, 'z': self.linear_z},
            'angular': {'x': self.angular_x, 'y': self.angular_y, 'z': self.angular_z}
        }

    def is_zero(self) -> bool:
        """Check if this is a zero/stop command."""
        return abs(self.linear_x) < 0.001 and abs(self.angular_z) < 0.001


@dataclass
class ControllerConfig:
    """Configuration for the follower controller."""
    # Target distance
    target_distance: float = 1.0  # meters
    
    # Velocity limits
    max_linear_vel: float = 0.5   # m/s
    max_angular_vel: float = 1.0  # rad/s
    
    # Proportional gains
    Kp_distance: float = 0.5  # Gain for distance error
    Kp_angular: float = 1.5   # Gain for angular error
    
    # Deadzones (ignore small errors)
    distance_deadzone: float = 0.05  # 5cm
    angular_deadzone: float = 0.05   # ~3 degrees
    
    # Smoothing (exponential moving average)
    smoothing_factor: float = 0.3  # 0 = no smoothing, 1 = instant response
    
    # Watchdog
    watchdog_timeout: float = 0.5  # seconds without detection before stopping


class FollowerController:
    """
    Computes velocity commands to follow a target person.
    
    Uses proportional control with smoothing, deadzones, and safety limits.
    """

    def __init__(self, config: Optional[ControllerConfig] = None):
        self.config = config or ControllerConfig()
        
        # State
        self.enabled = False
        self.target_person_id: Optional[int] = None
        self.target_description: Optional[str] = None
        
        # Smoothing state
        self._smoothed_linear = 0.0
        self._smoothed_angular = 0.0
        
        # Watchdog
        self._last_detection_time = 0.0
        
        # Last computed twist
        self._last_twist = Twist()
        
        # Statistics
        self._update_count = 0
        self._start_time = time.time()

    def start(self, target_description: Optional[str] = None):
        """Start following."""
        self.enabled = True
        self.target_description = target_description
        self._last_detection_time = time.time()
        print(f"[CONTROLLER] Started following" + 
              (f" target: '{target_description}'" if target_description else ""))

    def stop(self):
        """Stop following and zero velocities."""
        self.enabled = False
        self._smoothed_linear = 0.0
        self._smoothed_angular = 0.0
        self._last_twist = Twist()
        print("[CONTROLLER] Stopped following")

    def set_target_distance(self, distance: float):
        """Set the target follow distance in meters."""
        self.config.target_distance = max(0.3, min(5.0, distance))  # Clamp 0.3-5m
        print(f"[CONTROLLER] Target distance set to {self.config.target_distance:.2f}m")

    def set_target_person(self, person_id: int):
        """Lock onto a specific person ID."""
        self.target_person_id = person_id
        print(f"[CONTROLLER] Locked onto Person #{person_id}")

    def clear_target_person(self):
        """Clear target lock, follow closest person."""
        self.target_person_id = None
        self.target_description = None
        print("[CONTROLLER] Target cleared, following closest person")

    def update(self, target_person: Optional[DetectedPerson]) -> Twist:
        """
        Compute velocity command based on target person position.
        
        Args:
            target_person: The person to follow, or None if not detected
            
        Returns:
            Twist command
        """
        self._update_count += 1
        current_time = time.time()
        
        # If disabled, return zero
        if not self.enabled:
            return Twist()
        
        # Watchdog check
        if target_person is None:
            if current_time - self._last_detection_time > self.config.watchdog_timeout:
                # Watchdog triggered - stop
                if self._update_count % 30 == 0:  # Print every ~1 second at 30Hz
                    print("[CONTROLLER] Watchdog: No person detected, stopping")
                self._smoothed_linear = 0.0
                self._smoothed_angular = 0.0
                self._last_twist = Twist()
                return Twist()
            else:
                # Brief dropout, maintain last command
                return self._last_twist
        
        self._last_detection_time = current_time
        
        # Calculate errors
        distance_error = target_person.z - self.config.target_distance
        angular_error = -math.atan2(target_person.x, target_person.z)  # Negative because x>0 means person is to the right
        
        # Apply deadzones
        if abs(distance_error) < self.config.distance_deadzone:
            distance_error = 0.0
        if abs(angular_error) < self.config.angular_deadzone:
            angular_error = 0.0
        
        # Compute raw velocities (proportional control)
        linear_cmd = self.config.Kp_distance * distance_error
        angular_cmd = self.config.Kp_angular * angular_error
        
        # Clamp to limits
        linear_cmd = max(-self.config.max_linear_vel, 
                         min(self.config.max_linear_vel, linear_cmd))
        angular_cmd = max(-self.config.max_angular_vel, 
                          min(self.config.max_angular_vel, angular_cmd))
        
        # Apply smoothing (exponential moving average)
        alpha = self.config.smoothing_factor
        self._smoothed_linear = alpha * linear_cmd + (1 - alpha) * self._smoothed_linear
        self._smoothed_angular = alpha * angular_cmd + (1 - alpha) * self._smoothed_angular
        
        # Create twist
        twist = Twist(
            linear_x=self._smoothed_linear,
            angular_z=self._smoothed_angular
        )
        
        self._last_twist = twist
        
        # Print status periodically
        if self._update_count % 10 == 0:  # Every ~0.3s at 30Hz
            self._print_status(target_person, twist, distance_error, angular_error)
        
        return twist

    def _print_status(self, person: DetectedPerson, twist: Twist,
                      dist_err: float, ang_err: float):
        """Print formatted status to console."""
        print(f"[DETECTION] Person #{person.id}: "
              f"x={person.x:.2f}m, y={person.y:.2f}m, z={person.z:.2f}m "
              f"(conf={person.confidence:.2f})")
        
        print(f"[TARGET] Following Person #{person.id} "
              f"(target: {self.config.target_distance:.1f}m, "
              f"error: {dist_err:+.2f}m)")
        
        print(f"[TWIST] linear_x={twist.linear_x:+.3f} m/s, "
              f"angular_z={twist.angular_z:+.3f} rad/s")
        print()  # Blank line for readability

    def get_status(self) -> dict:
        """Get current controller status."""
        return {
            'enabled': self.enabled,
            'target_distance': self.config.target_distance,
            'target_person_id': self.target_person_id,
            'target_description': self.target_description,
            'last_twist': self._last_twist.to_dict(),
            'max_linear_vel': self.config.max_linear_vel,
            'max_angular_vel': self.config.max_angular_vel,
            'watchdog_timeout': self.config.watchdog_timeout,
            'update_count': self._update_count,
            'uptime': time.time() - self._start_time
        }

    @staticmethod
    def print_twist(twist: Twist):
        """Print a twist command in ROS-compatible format."""
        print("---")
        print("linear:")
        print(f"  x: {twist.linear_x:.6f}")
        print(f"  y: {twist.linear_y:.6f}")
        print(f"  z: {twist.linear_z:.6f}")
        print("angular:")
        print(f"  x: {twist.angular_x:.6f}")
        print(f"  y: {twist.angular_y:.6f}")
        print(f"  z: {twist.angular_z:.6f}")
        print("---")
