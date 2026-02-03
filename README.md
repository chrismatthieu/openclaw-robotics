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

```
RealSense Camera
      │
      ▼
PersonTracker (MediaPipe @ 30Hz)
      │
      ├──► PersonIdentifier (qwen3-vl @ 1-2Hz)
      │
      ▼
FollowerController
      │
      ▼
Console Output (Twist commands)
      │
      ▼
[Phase 2: ROS2 /cmd_vel]
```

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
