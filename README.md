# RealSense Person Follow Demo with OpenClaw

A Python application that detects and follows humans using a RealSense depth camera, with OpenClaw as the AI supervisor.

## Phase 1: Mac Development (Current)

Python-only implementation that prints detection status and Twist commands to console.
No ROS2 dependency - runs natively on macOS.

## Phase 2: Linux Deployment (Future)

Port to ROS2 on Linux with actual `/cmd_vel` publishing to robot.

---

## Prerequisites

- **Python 3.9** (must match pyrealsense2 build version)
- Intel RealSense camera (D400 series)
- librealsense + pyrealsense2 built from source (in `~/Projects/librealsense`)
- Ollama with qwen3-vl:2b model
- OpenClaw installed

## Installation

### 1. Set up Python 3.9 environment

pyrealsense2 built from source requires the same Python version it was compiled with.

```bash
# Create a Python 3.9 conda environment
conda create -n realsense python=3.9 -y
conda activate realsense

# Install dependencies
pip install flask mediapipe numpy opencv-python requests ollama
```

### 2. Verify librealsense location

The start script expects librealsense at `~/Projects/librealsense/build/Release`.
If yours is elsewhere, set the `LIBREALSENSE_PATH` environment variable.

### 3. Install Ollama vision model

```bash
ollama pull qwen3-vl:2b
```

## Usage

### Start the application

```bash
# Use the start script (handles sudo and PYTHONPATH)
./start.sh
```

Or manually:

```bash
sudo env PYTHONPATH=/path/to/librealsense/build/Release \
    /path/to/conda/envs/realsense/bin/python run.py
```

**Note:** sudo is required on macOS for USB access to the RealSense camera.

The app will:
1. Connect to your RealSense camera
2. Start detecting people using MediaPipe Pose
3. Print detection status and Twist commands to console
4. Expose HTTP API on `http://localhost:5050` for OpenClaw

### Console Output

```
[DETECTION] Person #1: x=0.12m, y=0.05m, z=1.35m (conf=0.92)
[TARGET] Following Person #1 (target: 1.0m)
[TWIST] linear_x=0.15 m/s, angular_z=-0.08 rad/s
```

### HTTP API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/start` | POST | Start following (optional: `description` param) |
| `/stop` | POST | Stop following |
| `/set_target` | POST | Set target by description (uses VLM) |
| `/set_distance` | POST | Set target follow distance in meters |
| `/status` | GET | Get current status |
| `/snapshot` | GET | Get annotated camera frame |
| `/mission` | POST | Start autonomous mission with goal |
| `/mission` | GET | Get current mission status |
| `/mission/cancel` | POST | Cancel current mission |
| `/analyze` | POST | Analyze scene with custom VLM prompt |
| `/events` | GET/POST | Configure event webhooks |
| `/events/test` | POST | Test webhook connectivity |
| `/teleop` | POST | Natural language movement command |
| `/move` | POST | Move forward/backward by distance or time |
| `/turn` | POST | Turn left/right by angle |
| `/velocity` | POST | Set raw velocity command |
| `/sequence` | POST | Execute command sequence |
| `/manual/status` | GET | Get manual control status |
| `/find_and_follow` | POST | Search, find, approach, and track object |
| `/find_object` | POST | Find object in scene via VLM |
| `/approach_object` | POST | Find and approach an object |
| `/look_for` | POST | Scan environment for object |
| `/objects` | GET | List all visible objects |
| `/health` | GET | Health check endpoint |

### Autonomous Missions

Start multi-step missions that execute independently:

```bash
# Follow until condition
curl -X POST http://localhost:5050/mission \
  -H "Content-Type: application/json" \
  -d '{"goal": "follow the person in red until they sit down"}'

# Find a specific person
curl -X POST http://localhost:5050/mission \
  -H "Content-Type: application/json" \
  -d '{"goal": "find a person wearing a hat"}'

# Patrol/scan the area
curl -X POST http://localhost:5050/mission \
  -H "Content-Type: application/json" \
  -d '{"goal": "patrol the area and report who you see"}'

# Check mission status
curl http://localhost:5050/mission

# Cancel mission
curl -X POST http://localhost:5050/mission/cancel
```

### Scene Analysis

Use the VLM to analyze the current scene with custom questions:

```bash
curl -X POST http://localhost:5050/analyze \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Is the person heading toward the exit?"}'
```

Example prompts:
- "Is the person sitting or standing?"
- "What is the person doing?"
- "Are there obstacles between me and the target?"
- "How many people are facing the camera?"

### Event Webhooks

The robot can post events to OpenClaw or other services:

```bash
# Get current webhook config
curl http://localhost:5050/events

# Configure webhook
curl -X POST http://localhost:5050/events \
  -H "Content-Type: application/json" \
  -d '{"webhook_url": "http://localhost:18789/webhook", "enabled": true}'

# Test webhook
curl -X POST http://localhost:5050/events/test
```

**Events posted automatically:**
- `person_lost` - Target lost for >2 seconds
- `person_found` - Person detected after being lost
- `mission_completed` - Mission finished successfully
- `mission_failed` - Mission encountered an error
- `target_reached` - Robot at target follow distance

### Manual Teleoperation

Control the robot with natural language commands via the `/teleop` endpoint:

```bash
# Natural language command (parsed and executed)
curl -X POST http://localhost:5050/teleop \
  -H "Content-Type: application/json" \
  -d '{"command": "move forward 1 meter, turn left, go forward for 5 seconds, stop"}'

# Move by distance
curl -X POST http://localhost:5050/move \
  -H "Content-Type: application/json" \
  -d '{"distance": 1.0}'

# Move for duration
curl -X POST http://localhost:5050/move \
  -H "Content-Type: application/json" \
  -d '{"duration": 3.0, "velocity": 0.3}'

# Turn (positive=left, negative=right)
curl -X POST http://localhost:5050/turn \
  -H "Content-Type: application/json" \
  -d '{"angle": 90}'

# Command sequence
curl -X POST http://localhost:5050/sequence \
  -H "Content-Type: application/json" \
  -d '{"commands": [
    {"type": "move", "distance": 1.0},
    {"type": "turn", "angle": -90},
    {"type": "move", "duration": 5, "velocity": 0.3}
  ]}'
```

**Supported teleop commands:**
- `"move forward/backward X meters"` - Move by distance
- `"go forward for X seconds"` - Move for duration
- `"turn left/right"` - Turn 90 degrees
- `"turn left/right X degrees"` - Turn specific angle
- `"turn around"` - Turn 180 degrees
- `"stop"` / `"halt"` - Stop all movement
- Chain commands with "then", "and", or commas

### Object Detection

Find and approach objects (not just people) using VLM:

```bash
# Find an object
curl -X POST http://localhost:5050/find_object \
  -H "Content-Type: application/json" \
  -d '{"object": "red chair"}'

# Approach an object
curl -X POST http://localhost:5050/approach_object \
  -H "Content-Type: application/json" \
  -d '{"object": "water bottle", "distance": 0.3}'

# Scan for an object (rotate to search)
curl -X POST http://localhost:5050/look_for \
  -H "Content-Type: application/json" \
  -d '{"object": "trash can"}'

# List all visible objects
curl http://localhost:5050/objects
```

**Can find any describable object:**
- Furniture: chairs, tables, couches, desks
- Electronics: laptops, phones, monitors, TVs
- Household: bottles, cups, bags, boxes
- Other: doors, plants, toys, books, balls, etc.

The VLM provides position estimates (left/center/right) and distance estimates (close/medium/far) which are converted to movement commands.

### Find and Follow (Smart Object Tracking)

The `/find_and_follow` endpoint is the most powerful object tracking command:

```bash
curl -X POST http://localhost:5050/find_and_follow \
  -H "Content-Type: application/json" \
  -d '{"object": "red ball", "distance": 0.5, "track": true}'
```

**Behavior:**
1. Checks if object is visible in current camera view
2. If not found, **rotates to search** (30° increments, up to 540° by default)
3. Once found, turns to face and approaches
4. When at target distance, continues tracking (adjusting position as object moves)
5. If object is lost, attempts to re-find it

This means you can say "find and follow the red ball" even if the ball is behind the robot - it will search, locate, and pursue it.

### OpenClaw Integration

#### 1. Initial OpenClaw Setup

If you haven't set up OpenClaw yet:

```bash
# Install OpenClaw
npm install -g openclaw

# Run onboarding (sets up workspace, gateway, etc.)
openclaw onboard
```

#### 2. Configure OpenAI API Key

OpenClaw needs an OpenAI API key for the chat model:

```bash
# Run configuration wizard
openclaw configure --section model
```

Follow the prompts to enter your OpenAI API key.

#### 3. Set the Model to gpt-4o-mini

Edit `~/.openclaw/openclaw.json` and ensure the model is set to a chat model (not a code completion model):

```json
{
  "agents": {
    "defaults": {
      "models": {
        "primary": "openai/gpt-4o-mini"
      }
    }
  }
}
```

**Note:** The default `openai/codex-mini-latest` is a code completion model and won't work for chat.

#### 4. Install the Follow-Robot Skill

```bash
# Copy skill to OpenClaw workspace
cp -r skill/follow-robot ~/.openclaw/workspace/skills/
```

#### 5. Add Robot to TOOLS.md

Add the following to `~/.openclaw/workspace/TOOLS.md` so the agent knows about the robot:

```markdown
## Active Devices

### 🤖 Follow Robot (RealSense Camera)

A robot follower system running at `http://localhost:5050` with RealSense depth camera.

**When to use:** Any question about robots, following, tracking, persons, distance, or commands like "start following", "stop", "who do you see", "how far away".

**Quick commands (use exec with curl):**
- Status: `curl -s http://localhost:5050/status`
- Start: `curl -s -X POST http://localhost:5050/start`
- Stop: `curl -s -X POST http://localhost:5050/stop`
- Set distance: `curl -s -X POST http://localhost:5050/set_distance -H "Content-Type: application/json" -d '{"distance": 1.5}'`

See `skills/follow-robot/SKILL.md` for full documentation.
```

#### 6. Restart the Gateway

```bash
# Clear any cached sessions and restart
rm -f ~/.openclaw/agents/main/sessions/sessions.json
openclaw gateway restart
```

#### 7. Open WebChat

```bash
openclaw webchat
```

Or navigate to http://127.0.0.1:18789/ in your browser.

#### Chat Commands

Once everything is configured, chat naturally:
- "How far away is the person?"
- "Start following"
- "Stop following"
- "Set the follow distance to 1.5 meters"
- "What's the robot status?"
- "Follow the person in the red shirt"

#### Troubleshooting OpenClaw

**"NO_REPLY" in chat:**
- Clear the session cache: `rm -f ~/.openclaw/agents/main/sessions/sessions.json`
- Restart gateway: `openclaw gateway restart`

**Agent doesn't respond to robot commands:**
- Ensure TOOLS.md has the robot section (step 5 above)
- Verify the skill is installed: `openclaw skills list | grep follow`

**API key issues:**
- Re-run: `openclaw configure --section model`
- Check `~/.openclaw/.env` contains your `OPENAI_API_KEY`

**Check gateway status:**
```bash
openclaw gateway status
```

## Architecture

### Two-Loop Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    OpenClaw (Slow Loop ~1-5 Hz)                  │
│                                                                  │
│   • Natural language interface                                   │
│   • Autonomous missions & goals                                  │
│   • Scene understanding via VLM                                  │
│   • High-level decision making                                   │
│   • Proactive monitoring (heartbeats)                            │
│                                                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP API (commands, queries, events)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Python App (Fast Loop @ 30 Hz)                  │
│                                                                  │
│   RealSense Camera ──► PersonTracker (MediaPipe)                │
│                              │                                   │
│                              ├──► PersonIdentifier (VLM @ 1-2Hz) │
│                              │                                   │
│                              ▼                                   │
│                       FollowerController                         │
│                              │                                   │
│                              ▼                                   │
│                    Twist Commands (Console)                      │
│                              │                                   │
│                              ▼                                   │
│                    [Phase 2: ROS2 /cmd_vel]                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Fast Loop (Python):** Handles real-time perception, safety, and control at 30Hz.

**Slow Loop (OpenClaw):** Handles high-level reasoning, missions, and user interaction at 1-5Hz.

## Configuration

Edit `src/follower_controller.py` to adjust:

- `target_distance`: Default 1.0m
- `max_linear_vel`: Default 0.5 m/s
- `max_angular_vel`: Default 1.0 rad/s
- `Kp_distance`: Proportional gain for distance
- `Kp_angular`: Proportional gain for centering

## Troubleshooting

### "pyrealsense2 not available - using mock camera"

The Python environment can't find pyrealsense2. Make sure:
1. You're using Python 3.9 (same version used to build pyrealsense2)
2. PYTHONPATH includes the librealsense build directory
3. Use `./start.sh` which sets these automatically

### "No module named 'flask'"

You're using system Python instead of the conda environment. Use:
```bash
./start.sh
```

### Camera requires sudo

On macOS, USB access to RealSense requires elevated permissions. The `start.sh` script handles this automatically.

### Custom librealsense location

If your librealsense is not at `~/Projects/librealsense`, set:
```bash
LIBREALSENSE_PATH=/your/path/to/librealsense/build/Release ./start.sh
```

### Custom Python location

If your conda Python 3.9 is not at the default location:
```bash
CONDA_PYTHON=/your/path/to/python ./start.sh
```

## License

MIT
