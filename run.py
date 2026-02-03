#!/usr/bin/env python3
"""
RealSense Person Follow Demo - Entry Point

Starts the person tracking and following application.
"""

import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description='RealSense Person Follow Demo')
    parser.add_argument('--port', type=int, default=5050,
                        help='HTTP API port (default: 5050)')
    parser.add_argument('--no-camera', action='store_true',
                        help='Run without camera (for testing)')
    parser.add_argument('--no-vlm', action='store_true',
                        help='Disable VLM integration')
    parser.add_argument('--target-distance', type=float, default=1.0,
                        help='Initial target follow distance in meters (default: 1.0)')
    args = parser.parse_args()

    # Import here to avoid slow startup for --help
    from src.main import FollowRobotApp

    app = FollowRobotApp(
        port=args.port,
        use_camera=not args.no_camera,
        use_vlm=not args.no_vlm,
        target_distance=args.target_distance
    )

    try:
        app.run()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
        app.stop()
        sys.exit(0)

if __name__ == '__main__':
    main()
