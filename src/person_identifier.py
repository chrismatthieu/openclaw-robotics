"""
PersonIdentifier - VLM-based Person Identification

Uses Ollama with qwen3-vl:2b to identify specific people
based on natural language descriptions.
"""

import base64
import time
import threading
from typing import Optional
from dataclasses import dataclass
import io

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    print("[WARN] ollama package not available - VLM disabled")

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

from .person_tracker import DetectedPerson


@dataclass
class IdentificationResult:
    """Result of a person identification query."""
    success: bool
    person_id: Optional[int]
    description: str
    confidence: float
    reasoning: str


class PersonIdentifier:
    """
    Uses a Vision Language Model (VLM) to identify people by description.
    
    Throttled to 1-2 Hz to avoid overloading the model.
    """

    def __init__(self, model: str = "qwen3-vl:2b", use_vlm: bool = True):
        self.model = model
        self.use_vlm = use_vlm and OLLAMA_AVAILABLE
        
        self._last_query_time = 0.0
        self._min_query_interval = 0.5  # Minimum 500ms between queries
        self._lock = threading.Lock()
        
        # Cache for recent identifications
        self._cache: dict[str, IdentificationResult] = {}
        self._cache_ttl = 5.0  # Cache results for 5 seconds
        
        if self.use_vlm:
            self._verify_model()

    def _verify_model(self):
        """Verify the VLM model is available."""
        try:
            # List available models
            models = ollama.list()
            model_names = [m.model for m in models.models] if hasattr(models, 'models') else []
            
            if self.model not in model_names and f"{self.model}:latest" not in model_names:
                print(f"[WARN] Model {self.model} not found. Available: {model_names}")
                print(f"[INFO] Run: ollama pull {self.model}")
                self.use_vlm = False
            else:
                print(f"[INFO] VLM model {self.model} available")
                
        except Exception as e:
            print(f"[WARN] Could not verify VLM model: {e}")
            print("[INFO] Make sure Ollama is running: ollama serve")
            self.use_vlm = False

    def _encode_image(self, image: np.ndarray) -> str:
        """Encode image to base64 for VLM."""
        if not CV2_AVAILABLE:
            return ""
        
        # Resize for faster processing
        max_dim = 512
        h, w = image.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            image = cv2.resize(image, (int(w * scale), int(h * scale)))
        
        # Encode as JPEG
        _, buffer = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return base64.b64encode(buffer).decode('utf-8')

    def _annotate_frame_with_numbers(self, frame: np.ndarray, 
                                      persons: list[DetectedPerson]) -> np.ndarray:
        """Annotate frame with person numbers for VLM reference."""
        if not CV2_AVAILABLE:
            return frame
        
        annotated = frame.copy()
        
        for i, person in enumerate(persons, 1):
            x, y, w, h = person.bbox
            
            # Draw bounding box
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)
            
            # Draw large number
            label = str(i)
            font_scale = 2.0
            thickness = 3
            
            (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 
                                                   font_scale, thickness)
            
            # Background for number
            cv2.rectangle(annotated, 
                         (x, y - text_h - 10), 
                         (x + text_w + 10, y),
                         (0, 255, 0), -1)
            
            # Number text
            cv2.putText(annotated, label, (x + 5, y - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thickness)
        
        return annotated

    def identify_person(self, description: str, frame: np.ndarray,
                        persons: list[DetectedPerson]) -> IdentificationResult:
        """
        Identify which person matches the description.
        
        Args:
            description: Natural language description (e.g., "person in red shirt")
            frame: Current camera frame
            persons: List of detected persons with bounding boxes
            
        Returns:
            IdentificationResult with matched person ID
        """
        if not persons:
            return IdentificationResult(
                success=False,
                person_id=None,
                description=description,
                confidence=0.0,
                reasoning="No persons detected in frame"
            )
        
        # If only one person, just return that one
        if len(persons) == 1:
            return IdentificationResult(
                success=True,
                person_id=persons[0].id,
                description=description,
                confidence=0.9,
                reasoning="Only one person visible"
            )
        
        # Check cache
        cache_key = f"{description}_{len(persons)}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if time.time() - self._last_query_time < self._cache_ttl:
                return cached
        
        # Throttle queries
        with self._lock:
            now = time.time()
            if now - self._last_query_time < self._min_query_interval:
                # Return first person as fallback when throttled
                return IdentificationResult(
                    success=True,
                    person_id=persons[0].id,
                    description=description,
                    confidence=0.5,
                    reasoning="Query throttled, using closest person"
                )
            self._last_query_time = now
        
        if not self.use_vlm:
            # Fallback: return closest person
            closest = min(persons, key=lambda p: p.distance)
            return IdentificationResult(
                success=True,
                person_id=closest.id,
                description=description,
                confidence=0.5,
                reasoning="VLM not available, using closest person"
            )
        
        # Annotate frame with numbers
        annotated = self._annotate_frame_with_numbers(frame, persons)
        image_b64 = self._encode_image(annotated)
        
        # Build prompt
        prompt = f"""Look at this image showing {len(persons)} people, each labeled with a number (1, 2, etc).

Which person matches this description: "{description}"

Reply with ONLY the number of the matching person (1, 2, 3, etc).
If no person matches, reply with "0".
If you're unsure, reply with the number of your best guess.

Answer:"""

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': [image_b64]
                }],
                options={
                    'temperature': 0.1,
                    'num_predict': 10
                }
            )
            
            answer = response['message']['content'].strip()
            
            # Parse the number from response
            import re
            numbers = re.findall(r'\d+', answer)
            
            if numbers:
                person_num = int(numbers[0])
                
                if 1 <= person_num <= len(persons):
                    matched_person = persons[person_num - 1]
                    result = IdentificationResult(
                        success=True,
                        person_id=matched_person.id,
                        description=description,
                        confidence=0.8,
                        reasoning=f"VLM identified person #{person_num}"
                    )
                    self._cache[cache_key] = result
                    return result
            
            # No valid match
            return IdentificationResult(
                success=False,
                person_id=None,
                description=description,
                confidence=0.0,
                reasoning=f"VLM response could not be parsed: {answer}"
            )
            
        except Exception as e:
            print(f"[ERROR] VLM query failed: {e}")
            # Fallback to closest person
            closest = min(persons, key=lambda p: p.distance)
            return IdentificationResult(
                success=True,
                person_id=closest.id,
                description=description,
                confidence=0.3,
                reasoning=f"VLM error, using closest person: {e}"
            )

    def describe_persons(self, frame: np.ndarray, 
                         persons: list[DetectedPerson]) -> str:
        """
        Get a description of all visible persons.
        
        Returns natural language description of each person.
        """
        if not persons:
            return "No persons detected."
        
        if not self.use_vlm:
            # Simple description without VLM
            descriptions = []
            for i, p in enumerate(persons, 1):
                descriptions.append(f"Person #{i}: {p.z:.1f}m away")
            return "\n".join(descriptions)
        
        # Throttle
        with self._lock:
            now = time.time()
            if now - self._last_query_time < self._min_query_interval:
                return "Please wait before requesting another description."
            self._last_query_time = now
        
        # Annotate and encode
        annotated = self._annotate_frame_with_numbers(frame, persons)
        image_b64 = self._encode_image(annotated)
        
        prompt = f"""Describe each person visible in this image. They are numbered 1 through {len(persons)}.

For each person, provide:
- Their approximate clothing (color, style)
- Any distinguishing features
- Their position (left, center, right)

Keep each description to 1-2 sentences."""

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': [image_b64]
                }],
                options={
                    'temperature': 0.3,
                    'num_predict': 200
                }
            )
            
            return response['message']['content'].strip()
            
        except Exception as e:
            print(f"[ERROR] VLM describe failed: {e}")
            # Fallback
            descriptions = []
            for i, p in enumerate(persons, 1):
                descriptions.append(f"Person #{i}: {p.z:.1f}m away, position x={p.x:.2f}m")
            return "\n".join(descriptions)

    def clear_cache(self):
        """Clear the identification cache."""
        self._cache.clear()

    def analyze_scene(self, frame: np.ndarray, persons: list[DetectedPerson], 
                      prompt: str) -> str:
        """
        Analyze the scene with a custom prompt.
        
        Useful for questions like:
        - "Is the person heading toward the exit?"
        - "Are there obstacles in the frame?"
        - "What is happening in this scene?"
        - "Is this condition true: 'person is sitting down'?"
        
        Args:
            frame: Current camera frame
            persons: List of detected persons
            prompt: Custom analysis prompt/question
            
        Returns:
            VLM analysis as a string
        """
        if not self.use_vlm:
            return "VLM not available for scene analysis."
        
        # Throttle
        with self._lock:
            now = time.time()
            if now - self._last_query_time < self._min_query_interval:
                return "Please wait before requesting another analysis."
            self._last_query_time = now
        
        # Annotate frame with person numbers if there are people
        if persons:
            annotated = self._annotate_frame_with_numbers(frame, persons)
        else:
            annotated = frame
        
        image_b64 = self._encode_image(annotated)
        
        # Build context-aware prompt
        context = f"There are {len(persons)} person(s) visible in this image"
        if persons:
            context += ", numbered 1 through " + str(len(persons))
            context += ". Person positions:\n"
            for i, p in enumerate(persons, 1):
                context += f"  Person #{i}: {p.z:.1f}m away, x={p.x:.2f}m\n"
        context += "\n"
        
        full_prompt = f"""{context}
{prompt}

Please provide a helpful, concise answer."""

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': full_prompt,
                    'images': [image_b64]
                }],
                options={
                    'temperature': 0.3,
                    'num_predict': 300
                }
            )
            
            return response['message']['content'].strip()
            
        except Exception as e:
            print(f"[ERROR] VLM analysis failed: {e}")
            return f"Analysis failed: {e}"

    def check_condition(self, frame: np.ndarray, persons: list[DetectedPerson],
                        condition: str) -> tuple[bool, str]:
        """
        Check if a condition is true in the current scene.
        
        Args:
            frame: Current camera frame
            persons: List of detected persons
            condition: Condition to check (e.g., "person is sitting down")
            
        Returns:
            Tuple of (is_true, explanation)
        """
        prompt = f"""Is this condition currently TRUE or FALSE: "{condition}"

Answer with exactly one word first (TRUE or FALSE), then explain in one sentence."""

        analysis = self.analyze_scene(frame, persons, prompt)
        
        is_true = analysis.upper().startswith("TRUE") or "TRUE" in analysis.upper()[:20]
        
        return is_true, analysis

    def find_object(self, frame: np.ndarray, object_description: str) -> dict:
        """
        Find an object in the scene and return its approximate location.
        
        Args:
            frame: Current camera frame
            object_description: Description of object to find (e.g., "red chair", "water bottle")
            
        Returns:
            Dict with found status, position (left/center/right), and confidence
        """
        if not self.use_vlm:
            return {
                'found': False,
                'reason': 'VLM not available'
            }
        
        # Throttle
        with self._lock:
            now = time.time()
            if now - self._last_query_time < self._min_query_interval:
                return {
                    'found': False,
                    'reason': 'Please wait before requesting another search'
                }
            self._last_query_time = now
        
        image_b64 = self._encode_image(frame)
        
        prompt = f"""Look at this image and find: "{object_description}"

If you can see this object, respond with:
FOUND: [position]
Position should be one of: FAR_LEFT, LEFT, CENTER_LEFT, CENTER, CENTER_RIGHT, RIGHT, FAR_RIGHT
Also estimate if it appears CLOSE (within 1m), MEDIUM (1-3m), or FAR (more than 3m).

If you cannot see this object, respond with:
NOT_FOUND: [reason]

Example responses:
- FOUND: CENTER, MEDIUM
- FOUND: LEFT, CLOSE
- NOT_FOUND: No red chair visible in the scene

Your response:"""

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': [image_b64]
                }],
                options={
                    'temperature': 0.1,
                    'num_predict': 50
                }
            )
            
            answer = response['message']['content'].strip().upper()
            
            if 'FOUND' in answer and 'NOT_FOUND' not in answer:
                # Parse position
                position = 'CENTER'
                horizontal_offset = 0.0  # -1.0 (far left) to 1.0 (far right)
                
                if 'FAR_LEFT' in answer or 'FAR LEFT' in answer:
                    position = 'FAR_LEFT'
                    horizontal_offset = -0.8
                elif 'CENTER_LEFT' in answer or 'CENTER LEFT' in answer:
                    position = 'CENTER_LEFT'
                    horizontal_offset = -0.3
                elif 'CENTER_RIGHT' in answer or 'CENTER RIGHT' in answer:
                    position = 'CENTER_RIGHT'
                    horizontal_offset = 0.3
                elif 'FAR_RIGHT' in answer or 'FAR RIGHT' in answer:
                    position = 'FAR_RIGHT'
                    horizontal_offset = 0.8
                elif 'LEFT' in answer:
                    position = 'LEFT'
                    horizontal_offset = -0.5
                elif 'RIGHT' in answer:
                    position = 'RIGHT'
                    horizontal_offset = 0.5
                else:
                    position = 'CENTER'
                    horizontal_offset = 0.0
                
                # Parse distance estimate
                distance_estimate = 'MEDIUM'
                estimated_distance = 2.0
                
                if 'CLOSE' in answer:
                    distance_estimate = 'CLOSE'
                    estimated_distance = 0.7
                elif 'FAR' in answer and 'FAR_LEFT' not in answer and 'FAR_RIGHT' not in answer:
                    distance_estimate = 'FAR'
                    estimated_distance = 4.0
                else:
                    distance_estimate = 'MEDIUM'
                    estimated_distance = 2.0
                
                return {
                    'found': True,
                    'object': object_description,
                    'position': position,
                    'horizontal_offset': horizontal_offset,
                    'distance_estimate': distance_estimate,
                    'estimated_distance': estimated_distance,
                    'raw_response': answer,
                    'confidence': 0.7
                }
            else:
                return {
                    'found': False,
                    'object': object_description,
                    'reason': answer.replace('NOT_FOUND:', '').strip(),
                    'raw_response': answer
                }
                
        except Exception as e:
            print(f"[ERROR] VLM find_object failed: {e}")
            return {
                'found': False,
                'object': object_description,
                'reason': f'VLM error: {e}'
            }

    def get_object_direction(self, frame: np.ndarray, object_description: str) -> tuple[float, float, str]:
        """
        Get direction to turn and estimated distance to reach an object.
        
        Args:
            frame: Current camera frame
            object_description: Description of object to find
            
        Returns:
            Tuple of (turn_angle_degrees, estimated_distance_meters, status_message)
        """
        result = self.find_object(frame, object_description)
        
        if not result['found']:
            return 0.0, 0.0, f"Object not found: {result.get('reason', 'unknown')}"
        
        # Convert horizontal offset to turn angle
        # Assuming ~60 degree horizontal FOV
        fov_degrees = 60
        horizontal_offset = float(result.get('horizontal_offset', 0.0))
        estimated_distance = float(result.get('estimated_distance', 2.0))
        
        turn_angle = -horizontal_offset * (fov_degrees / 2)
        
        return float(turn_angle), float(estimated_distance), f"Found {object_description} at {result['position']}"
