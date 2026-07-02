"""Generate research overview figures using Gemini (Nano Banana Pro) image generation."""

import os
import re
from pathlib import Path

from sandbox_vm.tools.utils import _err, _ok


def generate_figure(
    sections_dir: str,
    description_file: str,
    title: str = "",
    output: str = "figures/research_overview.png",
) -> dict:
    """
    Generate a research overview infographic using Gemini image generation.

    Reads a structured description file (written by an LLM), wraps it with visual
    style instructions, and calls Gemini 2.5 Flash Image to generate a colorful
    overview figure. The figure is saved as a PNG in the sections directory.

    Requires GOOGLE_API_KEY environment variable.

    Args:
        sections_dir: Path to the sections directory (relative to /workspace or absolute).
        description_file: Path to a text file containing the LLM-written figure description.
        title: Paper title. If empty, extracted from main.tex automatically.
        output: Output path relative to sections_dir (default: figures/research_overview.png).

    Returns:
        {
            "ok": True,
            "message": str,  # e.g. "FIGURE_GENERATED: path (size)"
            "output_path": str
        } or {"ok": False, "error": str, "message": str}

    Examples:
        >>> result = generate_figure("/workspace/outputs/paper/sections",
        ...     "/workspace/outputs/paper/sections/figure_description.txt")
        >>> print(result["message"])
        "FIGURE_GENERATED: .../figures/research_overview.png (1020KB)"
    """
    if not sections_dir or not isinstance(sections_dir, str):
        return _err("INVALID_INPUT", message="sections_dir must be a non-empty string")
    if not description_file or not isinstance(description_file, str):
        return _err(
            "INVALID_INPUT", message="description_file must be a non-empty string"
        )

    # Resolve paths
    sd = Path(sections_dir)
    if not sd.is_absolute():
        sd = Path("/workspace") / sections_dir.lstrip("/")

    df = Path(description_file)
    if not df.is_absolute():
        df = Path("/workspace") / description_file.lstrip("/")

    output_path = sd / output

    # Skip if figure already exists
    if output_path.exists() and output_path.stat().st_size > 1000:
        return _ok(
            message=f"CACHED: {output_path} already exists ({output_path.stat().st_size} bytes)",
            output_path=str(output_path),
        )

    # Read description
    if not df.exists():
        return _err(
            "FILE_NOT_FOUND", message=f"Description file not found: {description_file}"
        )
    description = df.read_text().strip()
    if not description:
        return _err("EMPTY_FILE", message="Description file is empty")

    # Get title
    if not title:
        main_path = sd / "main.tex"
        if main_path.exists():
            text = main_path.read_text()
            m = re.search(r"\\title\{(.+?)\}", text, re.DOTALL)
            if m:
                title = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", m.group(1))
                title = re.sub(r"[{}\\]", "", title).strip()
        if not title:
            title = "Research Overview"

    # Check API key
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return _err("NO_API_KEY", message="GOOGLE_API_KEY environment variable not set")

    # Generate figure
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        prompt = _build_overview_prompt(title, description)

        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(part.inline_data.data)
                # Auto-crop whitespace to make the figure shorter
                _autocrop(output_path)
                size_kb = output_path.stat().st_size / 1024
                return _ok(
                    message=f"FIGURE_GENERATED: {output_path} ({size_kb:.0f}KB)",
                    output_path=str(output_path),
                )

        return _err("NO_IMAGE", message="No image in Gemini response")

    except Exception as e:
        return _err("GENERATION_FAILED", message=f"Gemini API call failed: {e}")


def _autocrop(image_path, padding=20, bg_threshold=240):
    """Crop whitespace from image edges, keeping a small padding."""
    from PIL import Image, ImageChops

    img = Image.open(image_path).convert("RGB")
    # Create a background reference (top-left pixel color)
    bg = Image.new("RGB", img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg)
    # Convert to grayscale and threshold
    gray = diff.convert("L")
    bbox = gray.point(lambda x: 255 if x > (255 - bg_threshold) else 0).getbbox()
    if not bbox:
        # Fallback: use difference-based bbox
        bbox = gray.getbbox()
    if bbox:
        # Add padding
        left = max(0, bbox[0] - padding)
        top = max(0, bbox[1] - padding)
        right = min(img.width, bbox[2] + padding)
        bottom = min(img.height, bbox[3] + padding)
        cropped = img.crop((left, top, right, bottom))
        cropped.save(image_path)


def _build_overview_prompt(title, description):
    """Build the image generation prompt from title + LLM-written description."""
    system_name = title.split(":")[0].strip() if ":" in title else title

    return f"""Generate a professional **research overview infographic** for an academic paper.

CRITICAL STYLE REQUIREMENT: This must look like an INFOGRAPHIC or POSTER — NOT a
flowchart, NOT an algorithm diagram, NOT a UML diagram. Think of it as a visually
rich, colorful summary poster that a reader can glance at and immediately understand
what the research is about.

Reference style: Think of figures like "system architecture overview" diagrams in
top-tier AI papers — with large colorful rounded-rectangle modules, small icons
inside each module, concise text labels, and clean connecting arrows on a white
background. Similar to overview figures in papers like EmbodiedBench, ToolBench,
or AgentBench.

## Paper Title
{title}

## Visual Style Requirements (MANDATORY — follow ALL of these)

1. **Layout**: Very wide LANDSCAPE orientation (aspect ratio roughly 3:1, i.e. width
   is about 3x the height). The figure should be SHORT and WIDE — like a banner.
   Arrange the major conceptual modules side-by-side in a single horizontal row or
   at most two rows, reflecting their logical relationships (left-to-right flow,
   or hub-and-spoke). Do NOT stack modules vertically — keep the figure flat.

2. **Colored module blocks**: Each major component MUST be a large, visually
   prominent rounded rectangle filled with a DISTINCT soft pastel color:
   - Use colors like: #D4E6F1 (light blue), #D5F5E3 (light green), #FDEBD0 (light orange),
     #E8DAEF (light purple), #FADBD8 (light pink), #FCF3CF (light yellow), #D6EAF8 (sky blue)
   - Each block should have a subtle shadow or border for depth
   - Blocks should be LARGE enough to contain title + description + icon

3. **Icons**: Each block MUST include a small illustrative icon or emoji-style
   symbol that visually represents the concept. Place icons in the top-left corner
   or beside the title of each block.

4. **Text inside blocks**:
   - Bold title (2-4 words, large font)
   - 1-2 short bullet points (under 8 words each, smaller font)
   - All text must be clearly readable

5. **Connections**: Use clean arrows between blocks to show relationships.
   - Arrows should have text labels describing the relationship
   - Use solid arrows for main flow, dashed arrows for secondary relationships
   - Arrow colors should be dark gray or match the source block color

6. **Background**: Pure white or very light gray (#F8F9FA)

7. **Title**: Show "{system_name}" as a prominent header/banner at the top
   of the figure, in a dark colored bar or bold text.

8. **Overall aesthetic**: Clean, modern, professional. The figure should look
   like it belongs in a Nature or Science paper's graphical abstract.

## What this figure must NOT look like
- NO black-and-white flowcharts with plain rectangular boxes
- NO UML diagrams or algorithm pseudocode
- NO thin-bordered boxes with only text (must have colored fill)
- NO cluttered or dense layouts — keep it clean and spacious
- NO tiny fonts — everything must be readable at normal paper size

## Paper-Specific Content (draw exactly these components)

{description}
"""
