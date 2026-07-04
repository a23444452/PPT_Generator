"""大綱與投影片生成邏輯。"""

from app.generation.outline import OutlineError, generate_outline, validate_outline
from app.generation.slides import generate_slides

__all__ = ["OutlineError", "generate_outline", "validate_outline", "generate_slides"]
