---
name: follow-robot
description: Control a robot that follows people using RealSense camera depth sensing.
metadata: { "openclaw": { "emoji": "🤖", "requires": { "bins": ["curl"] } } }
---

# Follow Robot Skill

Control a robot to follow a person using RealSense camera depth sensing.

**IMPORTANT**: When the user asks about the robot, following, tracking persons, or distance - use `exec` to run the curl commands below.

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

## Safety Notes

- The robot has velocity limits (0.5 m/s forward, 1.0 rad/s turning)
- A watchdog stops the robot if no person is detected for 500ms
- You can call `follow.stop()` at any time for emergency stop
- The robot will not move backwards faster than 0.5 m/s

## Troubleshooting

- **"No persons detected"**: Make sure a person is visible to the RealSense camera
- **"VLM not available"**: Ensure Ollama is running with qwen3-vl:2b model
- **"Connection refused"**: Start the follow-robot app with `python run.py`
