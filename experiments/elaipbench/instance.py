"""Per-question instance processing for ELAIPBench benchmark."""

import json
import threading
import traceback
from pathlib import Path

import yaml

from config import ELAIPBenchResult
from evaluate import parse_answer
from prompts import MA_MCQ_PROMPT, SA_MCQ_PROMPT

_print_lock = threading.Lock()


def _safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


def run_instance(
    idx: int,
    total: int,
    instance: dict,
    args,
    output_dir: Path,
) -> ELAIPBenchResult:
    """Run the agent on a single ELAIPBench question."""
    qid = instance["id"]
    qtype = instance["question_type"]
    preview = instance["question"][:80].replace("\n", " ")

    _safe_print(f"\n[{idx}/{total}] Question {qid} ({qtype}): {preview}...")

    try:
        from harness.agent import AgentSPEX
        from harness.types.config import EffectiveArgs
        from mcp_client.client import MCPClient

        # ELAIP workflows declare `enabled_tools: []` (the agent reasons purely from
        # the paper text), so no sandbox MCP server is needed: skip the eager connect
        # and expose an empty tool list (AgentSPEX fetches tools at construction).
        mcp_client = MCPClient(connect=False)
        mcp_client.list_tools = lambda: []
        agent = AgentSPEX(mcp_client=mcp_client)

        custom_yaml_file = prepare_yaml_for_question(
            args.workflow_file,
            instance,
            output_dir,
            qtype,
        )

        # Create per-question log directory
        question_log_dir = output_dir / f"logs/question_{qid}"
        question_log_dir.mkdir(parents=True, exist_ok=True)

        # Create a copy of args with per-question output_dir for isolated logging
        class _ArgsWithOutputDir:
            def __init__(self, original_args, output_dir):
                self.__dict__.update(
                    {
                        k: getattr(original_args, k)
                        for k in dir(original_args)
                        if not k.startswith("__")
                    }
                )
                self.output_dir = str(output_dir)

        per_question_args = _ArgsWithOutputDir(args, question_log_dir)

        agent_args = EffectiveArgs(
            workflow_file=custom_yaml_file,
            model=args.model if args.model else "gpt-4.1",
            _original_args=per_question_args,
        )

        agent_output = agent.run(agent_args)
        response_text = (
            agent_output if isinstance(agent_output, str) else str(agent_output or "")
        )

        parsed_answer = parse_answer(response_text, qtype)
        is_correct = parsed_answer == instance["answer"]

        result = ELAIPBenchResult(
            question_id=qid,
            question=instance["question"],
            question_type=qtype,
            correct_answer=instance["answer"],
            paper_id=instance["paper_id"],
            status="completed",
            response=response_text,
            parsed_answer=parsed_answer,
            is_correct=is_correct,
        )

        save_result(result, output_dir)
        status = (
            "CORRECT" if is_correct else ("REFUSED" if not parsed_answer else "WRONG")
        )
        _safe_print(
            f"  [{qid}] {status} (parsed={parsed_answer}, correct={instance['answer']})"
        )
        return result

    except Exception as e:
        _safe_print(f"  [{qid}] Error: {e}")
        traceback.print_exc()
        result = ELAIPBenchResult(
            question_id=qid,
            question=instance["question"],
            question_type=qtype,
            correct_answer=instance["answer"],
            paper_id=instance["paper_id"],
            status="failed",
            error=str(e),
        )
        save_result(result, output_dir)
        return result


def prepare_yaml_for_question(
    yaml_file: str,
    question: dict,
    output_dir: Path,
    qtype: str,
) -> str:
    """Create a customized YAML file for one ELAIPBench question."""
    template_path = Path(yaml_file).resolve()
    with open(template_path, "r", encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f)

    if "parameters" not in yaml_data:
        yaml_data["parameters"] = {}

    yaml_data["parameters"]["paper_content"] = question["paper_content"]
    yaml_data["parameters"]["question"] = question["question"]
    yaml_data["parameters"]["question_type"] = qtype
    yaml_data["parameters"]["question_type_instruction"] = (
        SA_MCQ_PROMPT if qtype == "SA-MCQ" else MA_MCQ_PROMPT
    )

    custom_yaml_path = output_dir / f"question_{question['id']}.yaml"
    with open(custom_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

    return str(custom_yaml_path)


def save_result(result: ELAIPBenchResult, output_dir: Path) -> None:
    """Save an ELAIPBench result as JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{result.question_id}.json"

    data = {
        "question_id": result.question_id,
        "question": result.question,
        "question_type": result.question_type,
        "correct_answer": result.correct_answer,
        "paper_id": result.paper_id,
        "status": result.status,
        "response": result.response,
        "parsed_answer": result.parsed_answer,
        "is_correct": result.is_correct,
    }
    if result.error:
        data["error"] = result.error

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
