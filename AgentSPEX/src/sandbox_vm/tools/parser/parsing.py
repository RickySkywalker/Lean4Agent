import asyncio
import os

from bs4 import BeautifulSoup
from fastmcp import Context
from openai import AsyncOpenAI
from PyPDF2 import PdfReader

from sandbox_vm.mcp.utils import filename_to_path, path_to_filename
from sandbox_vm.tools.parser.utils import _image_to_data_uri
from sandbox_vm.tools.session_management import MANAGER
from sandbox_vm.tools.utils import _sid

VISION_MODEL = os.environ.get("VISION_MODEL", "gpt-4o")


async def extract_text_from_file(
    file_path: str, output_dir: str = "text_output", summary_length: int = 5000
) -> dict:
    """
    Extracts text from a local PDF or HTML file, saves it to a .txt file, and returns a summary.

    Args:
        file_path: Path to the local input file (.pdf or .html).
        output_dir: Directory to save the extracted .txt file.
        summary_length: Maximum number of characters in the summary.

    Returns:
        A dictionary containing:
            - "local_filename" (str): Path to the saved .txt file (string form).
            - "summary" (str): A summary of the extracted content, truncated.
    """
    path = filename_to_path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist.")

    ext = path.suffix.lower()
    if ext not in [".pdf", ".html", ".htm"]:
        raise ValueError(f"Unsupported file extension: {ext}")

    output_dir = filename_to_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / (path.stem + ".txt")

    if ext == ".pdf":
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        html = path.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")

    cleaned_text = text.strip()
    output_file.write_text(cleaned_text, encoding="utf-8")

    # Create truncated summary
    summary = cleaned_text
    if len(summary) > summary_length:
        summary = summary[:summary_length].rsplit(" ", 1)[0] + " ..."

    return {
        "local_filename": path_to_filename(output_file),
        "summary": summary,
    }


async def extract_text_from_files(
    file_paths: list, output_dir: str = "text_output", summary_length: int = 5000
) -> dict:
    """
    Extracts text from multiple local PDF or HTML files, saves them to separate files,
    and returns truncated summaries as (filename, summary) pairs.

    Args:
        file_paths: List of paths to the local input files (.pdf or .html).
        output_dir: Directory to save the extracted .txt files.
        summary_length: Maximum number of characters in each summary.

    Returns:
        A dictionary containing:
            - "results" (list): List of dict {local_filename: str, summary: str} .
    """
    results = []

    async def process_file(file_path):
        try:
            result = await extract_text_from_file(file_path, output_dir, summary_length)
            results.append(
                {
                    "local_filename": result["local_filename"],
                    "summary": result["summary"],
                }
            )
        except Exception as e:
            print(f"Error processing file {file_path}: {e}")

    tasks = [process_file(file_path) for file_path in file_paths]
    await asyncio.gather(*tasks)

    return {"results": results}


async def analyze_screenshot(ctx: Context, file_path: str, query: str) -> dict:
    """
    Use this tool to analyze screenshots or images.

    Args:
        file_path (str): file path to the image (may be a session-relative vpath like /shots/shot-X.png)
        query (str): query to be answered

    Returns:
        dict: {"response": "<AI generated answer>"}
    """
    client = AsyncOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("BASE_URL", "https://api.openai.com/v1"),
    )

    # Resolve vpath (session-relative) to actual filesystem path via session manager
    rt = MANAGER.get(_sid(ctx))
    resolved = rt.root / file_path.lstrip("/")
    image_uri = _image_to_data_uri(resolved)
    messages = [
        {"role": "system", "content": "You are a helpful AI assistant."},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"Given the provided image, answer the following query.\nQuery: {query}",
                },
                {"type": "image_url", "image_url": {"url": image_uri}},
            ],
        },
    ]

    resp = await client.chat.completions.create(
        model=VISION_MODEL,
        messages=messages,
        temperature=0.2,
    )
    content = (resp.choices[0].message.content or "").strip()
    return {"response": content}
