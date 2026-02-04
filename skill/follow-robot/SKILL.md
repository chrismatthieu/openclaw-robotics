---
name: follow-robot
description: Control a robot that follows people using RealSense camera depth sensing. Supports autonomous missions, scene analysis, and event webhooks.
metadata: { "openclaw": { "emoji": "🤖", "requires": { "bins": ["curl"] } } }
---

# Follow Robot Skill

Control a robot to follow a person using RealSense camera depth sensing.

**IMPORTANT**: When the user asks about the robot, following, tracking persons, distance, missions, or scene analysis - use `exec` to run the curl commands below.

## Quick Commands

Get status (distance, persons detected):
```bash
curl -s http://localhost:5050/status
```

Start following:
```bash
curl -s -X POST http://localhost:5050/start
```

Stop following:
```bash
curl -s -X POST http://localhost:5050/stop
```

Set follow distance (meters):
```bash
curl -s -X POST http://localhost:5050/set_distance -H "Content-Type: application/json" -d '{"distance": 1.5}'
```

Start a mission:
```bash
curl -s -X POST http://localhost:5050/mission -H "Content-Type: application/json" -d '{"goal": "follow the person in red until they sit down"}'
```

Analyze the scene:
```bash
curl -s -X POST http://localhost:5050/analyze -H "Content-Type: application/json" -d '{"prompt": "Is the person heading toward the door?"}'
```

**Manual Control (Teleoperation):**
```bash
# Natural language command
curl -s -X POST http://localhost:5050/teleop -H "Content-Type: application/json" -d '{"command": "move forward 1 meter, turn left, go forward for 5 seconds, stop"}'

# Move forward/backward by distance
curl -s -X POST http://localhost:5050/move -H "Content-Type: application/json" -d '{"distance": 1.0}'

# Turn left/right by angle
curl -s -X POST http://localhost:5050/turn -H "Content-Type: application/json" -d '{"angle": 90}'

# Stop all movement
curl -s -X POST http://localhost:5050/stop
```

**Object Detection (find things other than people):**
```bash
# Find an object
curl -s -X POST http://localhost:5050/find_object -H "Content-Type: application/json" -d '{"object": "red chair"}'

# Approach an object
curl -s -X POST http://localhost:5050/approach_object -H "Content-Type: application/json" -d '{"object": "water bottle", "distance": 0.3}'

# Scan/look for an object
curl -s -X POST http://localhost:5050/look_for -H "Content-Type: application/json" -d '{"object": "trash can"}'

# Find and follow an object (searches if not visible, then tracks)
curl -s -X POST http://localhost:5050/find_and_follow -H "Content-Type: application/json" -d '{"object": "red ball", "distance": 0.5}'

# List all visible objects
curl -s http://localhost:5050/objects
```

## Tools

### follow.start

Start following a person.

**Usage:**
```bash
curl -X POST http://localhost:5050/start
# Or with a target description:
curl -X POST http://localhost:5050/start -H "Content-Type: application/json" -d '{"description": "person in red shirt"}'
```

**Parameters:**
- `description` (optional): Natural language description of the person to follow (e.g., "person wearing blue jacket", "the person on the left")

**Example responses:**
- Success: `{"status": "ok", "message": "Started following", "target": "person in red shirt"}`
- Already running: `{"status": "ok", "message": "Already following"}`

### follow.stop

Stop following and halt the robot.

**Usage:**
```bash
curl -X POST http://localhost:5050/stop
```

**Example response:**
`{"status": "ok", "message": "Stopped following"}`

### follow.set_target

Use the vision model to identify and lock onto a specific person.

**Usage:**
```bash
curl -X POST http://localhost:5050/set_target -H "Content-Type: application/json" -d '{"description": "the person wearing a red shirt"}'
```

**Parameters:**
- `description` (required): Natural language description of the target person

**Example response:**
`{"status": "ok", "person_id": 2, "confidence": 0.8, "reasoning": "VLM identified person #2"}`

### follow.set_distance

Set the target follow distance in meters.

**Usage:**
```bash
curl -X POST http://localhost:5050/set_distance -H "Content-Type: application/json" -d '{"distance": 1.5}'
```

**Parameters:**
- `distance` (required): Target distance in meters (0.3 to 5.0)

**Example response:**
`{"status": "ok", "target_distance": 1.5}`

### follow.status

Get the current status of the follower.

**Usage:**
```bash
curl http://localhost:5050/status
```

**Example response:**
```json
{
  "enabled": true,
  "tracking": true,
  "target_distance": 1.0,
  "current_distance": 1.35,
  "target_person_id": 1,
  "target_description": "person in red shirt",
  "persons_detected": 2,
  "twist": {
    "linear_x": 0.15,
    "angular_z": -0.08
  }
}
```

### follow.snapshot

Get a description of all visible persons (uses VLM).

**Usage:**
```bash
curl http://localhost:5050/snapshot
```

**Example response:**
```json
{
  "persons": [
    {"id": 1, "distance": 1.35, "description": "Person wearing red t-shirt, standing in center"},
    {"id": 2, "distance": 2.10, "description": "Person in blue jacket, on the left side"}
  ],
  "frame_base64": "..."
}
```

### follow.mission

Start an autonomous mission with a goal description. The robot will execute the mission independently.

**Usage:**
```bash
# Start a mission
curl -X POST http://localhost:5050/mission -H "Content-Type: application/json" -d '{"goal": "follow the person in red until they sit down"}'

# Check mission status
curl http://localhost:5050/mission

# Cancel mission
curl -X POST http://localhost:5050/mission/cancel
```

**Supported Mission Types:**
- `"follow X until Y"` - Follow a person until a condition is met
- `"find a person wearing X"` - Search for and lock onto a specific person
- `"patrol the area"` / `"scan for people"` - Survey and report on visible persons
- `"approach the person in X"` - Move toward a person until reaching target distance

**Example response:**
```json
{
  "status": "ok",
  "mission_id": "mission_1",
  "goal": "follow the person in red until they sit down"
}
```

### follow.analyze

Analyze the current scene with a custom question using the VLM.

**Usage:**
```bash
curl -X POST http://localhost:5050/analyze -H "Content-Type: application/json" -d '{"prompt": "Is the person heading toward the exit?"}'
```

**Example prompts:**
- "Is the person I'm following sitting down?"
- "Are there obstacles between me and the target?"
- "What is the person doing?"
- "How many people are in the room?"

**Example response:**
```json
{
  "status": "ok",
  "prompt": "Is the person heading toward the exit?",
  "analysis": "No, the person appears to be standing still in the center of the room, facing the camera.",
  "persons_detected": 1
}
```

### follow.events

Configure event webhooks to receive notifications when things happen.

**Usage:**
```bash
# Get current config
curl http://localhost:5050/events

# Configure webhooks
curl -X POST http://localhost:5050/events -H "Content-Type: application/json" -d '{"webhook_url": "http://localhost:18789/webhook", "enabled": true}'

# Test webhook
curl -X POST http://localhost:5050/events/test
```

**Event types:**
- `person_lost` - Target person no longer visible
- `person_found` - Person detected after being lost
- `mission_completed` - Autonomous mission finished successfully
- `mission_failed` - Mission encountered an error
- `target_reached` - Robot reached the target follow distance

### follow.teleop

Execute natural language movement commands.

**Usage:**
```bash
curl -X POST http://localhost:5050/teleop -H "Content-Type: application/json" -d '{"command": "move forward 1 meter then turn left and go forward for 5 seconds"}'
```

**Supported commands:**
- `"move forward 1 meter"` - Move forward by distance
- `"move backward 50 cm"` - Move backward
- `"go forward for 3 seconds"` - Move for duration
- `"turn left"` / `"turn right"` - Turn 90 degrees
- `"turn left 45 degrees"` - Turn specific angle
- `"turn around"` - Turn 180 degrees
- `"stop"` / `"halt"` - Stop all movement
- Chain commands with "then", "and", or commas

**Example response:**
```json
{
  "status": "ok",
  "message": "Executing sequence of 3 commands",
  "parsed_commands": [
    {"type": "move", "distance": 1.0},
    {"type": "turn", "angle": 90},
    {"type": "move", "duration": 5, "velocity": 0.3}
  ]
}
```

### follow.move

Move the robot forward or backward.

**Usage:**
```bash
# By distance
curl -X POST http://localhost:5050/move -H "Content-Type: application/json" -d '{"distance": 1.0}'

# By duration
curl -X POST http://localhost:5050/move -H "Content-Type: application/json" -d '{"duration": 3.0, "velocity": 0.3}'

# Backward
curl -X POST http://localhost:5050/move -H "Content-Type: application/json" -d '{"distance": -0.5}'
```

**Parameters:**
- `distance`: Distance in meters (positive=forward, negative=backward)
- `duration`: Time in seconds (alternative to distance)
- `velocity`: Speed in m/s (default: 0.3, max: 0.5)

### follow.turn

Turn the robot left or right.

**Usage:**
```bash
# Turn left 90 degrees
curl -X POST http://localhost:5050/turn -H "Content-Type: application/json" -d '{"angle": 90}'

# Turn right 45 degrees
curl -X POST http://localhost:5050/turn -H "Content-Type: application/json" -d '{"angle": -45}'
```

**Parameters:**
- `angle`: Angle in degrees (positive=left/CCW, negative=right/CW)
- `angular_velocity`: Turn speed in rad/s (default: 0.5)

### follow.sequence

Execute a sequence of movement commands.

**Usage:**
```bash
curl -X POST http://localhost:5050/sequence -H "Content-Type: application/json" -d '{
  "commands": [
    {"type": "move", "distance": 1.0},
    {"type": "turn", "angle": -90},
    {"type": "move", "duration": 5.0, "velocity": 0.3},
    {"type": "wait", "duration": 1.0},
    {"type": "turn", "angle": 90}
  ]
}'
```

### follow.find_object

Find an object in the scene using VLM.

**Usage:**
```bash
curl -X POST http://localhost:5050/find_object -H "Content-Type: application/json" -d '{"object": "red chair"}'
```

**Parameters:**
- `object`: Description of object to find (e.g., "red chair", "water bottle", "laptop")

**Example response:**
```json
{
  "status": "ok",
  "found": true,
  "object": "red chair",
  "position": "LEFT",
  "horizontal_offset": -0.5,
  "distance_estimate": "MEDIUM",
  "estimated_distance": 2.0,
  "confidence": 0.7
}
```

### follow.approach_object

Find and approach an object.

**Usage:**
```bash
curl -X POST http://localhost:5050/approach_object -H "Content-Type: application/json" -d '{"object": "water bottle", "distance": 0.3}'
```

**Parameters:**
- `object`: Description of object to approach
- `distance`: Target distance from object in meters (default: 0.5)

**Example response:**
```json
{
  "status": "ok",
  "message": "Approaching water bottle",
  "turn_angle": 15.5,
  "estimated_distance": 1.8,
  "move_distance": 1.3,
  "commands": [
    {"type": "turn", "angle": 15.5},
    {"type": "move", "distance": 1.3}
  ]
}
```

### follow.look_for

Scan the environment by rotating, looking for an object.

**Usage:**
```bash
curl -X POST http://localhost:5050/look_for -H "Content-Type: application/json" -d '{"object": "trash can"}'
```

**Parameters:**
- `object`: Description of object to search for
- `max_rotations`: Maximum full rotations to make (default: 1)

### follow.objects

List all visible objects in the scene.

**Usage:**
```bash
curl http://localhost:5050/objects
```

**Example response:**
```json
{
  "status": "ok",
  "count": 4,
  "objects": [
    {"name": "Chair", "details": "left, medium"},
    {"name": "Table", "details": "center, close"},
    {"name": "Laptop", "details": "center, close"},
    {"name": "Plant", "details": "right, far"}
  ]
}
```

### follow.find_and_follow

**The main object tracking command.** Search for an object (rotating if needed), approach it, and optionally keep tracking it.

**Usage:**
```bash
# Basic - stop when target is lost
curl -X POST http://localhost:5050/find_and_follow -H "Content-Type: application/json" -d '{"object": "person", "distance": 1.0}'

# Continuous mode - search for new target when lost
curl -X POST http://localhost:5050/find_and_follow -H "Content-Type: application/json" -d '{"object": "person", "continuous": true}'
```

**Parameters:**
- `object`: Description of object to find and follow (use "person" for people)
- `distance`: Target distance from object in meters (default: 0.5)
- `track`: Keep tracking after reaching (default: true)
- `continuous`: If target is lost, search for new target (default: false)
- `max_search_rotations`: Max full rotations to search (default: 1.5)

**Behavior:**
1. Checks if object is visible in current view
2. If not found, rotates incrementally (30° at a time) to search
3. Once found, turns to face and approaches
4. When at target distance, continues tracking (adjusting position)
5. If target is lost:
   - **continuous=false** (default): Mission ends, robot stops
   - **continuous=true**: Robot searches for a new target and continues

**Example response:**
```json
{
  "status": "ok",
  "message": "Searching for red ball...",
  "mission_id": "find_follow_1",
  "object": "red ball",
  "target_distance": 0.5,
  "tracking": true
}
```

**Check mission progress:**
```bash
curl http://localhost:5050/mission
```

**Cancel tracking:**
```bash
curl -X POST http://localhost:5050/mission/cancel
```

## Example Conversations

### Basic Following
- User: "Start following the closest person"
- Assistant: *calls follow.start()* "I've started following. The robot will track the nearest person and maintain a 1 meter distance."

### Target by Description
- User: "Follow the person in the red shirt"
- Assistant: *calls follow.set_target("person wearing red shirt")* "I've identified the person in red and locked onto them. The robot will now follow only that person."

### Adjust Distance
- User: "Stay a bit further back, like 2 meters"
- Assistant: *calls follow.set_distance(2.0)* "Done. The robot will now maintain a 2 meter following distance."

### Check Status
- User: "How far away is the person you're following?"
- Assistant: *calls follow.status()* "The target person is currently 1.35 meters away. I'm maintaining the target distance of 1 meter."

### Stop Following
- User: "Stop following"
- Assistant: *calls follow.stop()* "Stopped. The robot has halted."

### Describe Scene
- User: "Who do you see?"
- Assistant: *calls follow.snapshot()* "I can see two people: Person #1 is wearing a red t-shirt and is about 1.3 meters away in the center. Person #2 is wearing a blue jacket and is 2.1 meters away on the left."

### Autonomous Mission
- User: "Follow the person in the blue jacket until they leave the room"
- Assistant: *calls follow.mission("follow the person in blue jacket until they leave the room")* "I've started an autonomous mission. I'll follow the person in the blue jacket and stop when they leave the room. I'll let you know when the mission completes."

### Scene Analysis
- User: "Is the person I'm following looking at me?"
- Assistant: *calls follow.analyze("Is the person looking at the camera/robot?")* "Based on my analysis, the person appears to be looking away from the camera, toward the left side of the room."

### Find Someone
- User: "Find someone wearing a hat"
- Assistant: *calls follow.mission("find a person wearing a hat")* "I'm scanning for someone wearing a hat. I'll start following them when I find them."

### Manual Control
- User: "Move forward 1 meter"
- Assistant: *calls follow.move(1.0)* "Moving forward 1 meter."

### Turn and Move
- User: "Turn left and then move forward 2 meters"
- Assistant: *calls follow.teleop("turn left then move forward 2 meters")* "Turning left, then moving forward 2 meters."

### Complex Sequence
- User: "Move forward 1 meter, turn left, go forward for 5 seconds, then stop"
- Assistant: *calls follow.teleop("move forward 1 meter, turn left, go forward for 5 seconds, then stop")* "Executing movement sequence: forward 1m, turn left, forward for 5s, then stop."

### Quick Stop
- User: "Stop!"
- Assistant: *calls follow.stop()* "Stopped. Robot halted."

### Find an Object
- User: "Can you see a chair?"
- Assistant: *calls follow.find_object("chair")* "Yes, I can see a chair to the left, about 2 meters away."

### Go to an Object
- User: "Go to the red chair"
- Assistant: *calls follow.approach_object("red chair")* "Found the red chair on the left. Turning and approaching it now."

### Look for Something
- User: "Find my water bottle"
- Assistant: *calls follow.look_for("water bottle")* "I don't see it immediately. Let me scan the room..." *robot rotates* "Found it! It's on your right."

### What Do You See?
- User: "What objects do you see?"
- Assistant: *calls follow.objects()* "I can see: a chair on the left, a table in the center, a laptop on the table, and a plant on the right."

### Fetch Something
- User: "Go get the ball"
- Assistant: *calls follow.approach_object("ball", 0.2)* "I see a ball in the center of the room, about 1.5m away. Moving to it now."

### Find and Follow Object (even if behind)
- User: "Find and follow the red ball"
- Assistant: *calls follow.find_and_follow("red ball")* "I'll search for the red ball and follow it once I find it..."
- *robot rotates, scanning*
- Assistant: "Found the red ball behind me! Approaching now and will track it."

### Track a Moving Object
- User: "Follow that toy car"
- Assistant: *calls follow.find_and_follow("toy car", 0.3, true)* "Searching for the toy car... Found it! I'll follow it and keep tracking."

### Continuous Person Following
- User: "Follow anyone who comes by and keep looking for new people"
- Assistant: *calls follow.find_and_follow("person", 1.0, true, true)* "I'll follow anyone I see. If they leave, I'll search for someone else."
- *Person walks by, robot follows*
- *Person leaves frame*
- Robot: "Person lost - searching for new target..."
- *Robot rotates, finds another person*
- Robot: "Found new person! Following them now."

### Find Something Anywhere
- User: "Where's my phone?"
- Assistant: *calls follow.find_and_follow("phone", 0.5, false)* "Let me look around for your phone..." *scans room* "Found it on the table to your left. I'll move toward it."

## Safety Notes

- The robot has velocity limits (0.5 m/s forward, 1.0 rad/s turning)
- A watchdog stops the robot if no person is detected for 500ms
- You can call `follow.stop()` at any time for emergency stop
- The robot will not move backwards faster than 0.5 m/s

## Troubleshooting

- **"No persons detected"**: Make sure a person is visible to the RealSense camera
- **"VLM not available"**: Ensure Ollama is running with qwen3-vl:2b model
- **"Connection refused"**: Start the follow-robot app with `python run.py`
