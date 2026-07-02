import subprocess
from typing import Literal

Task = Literal["bbbp", "clintox", "tox21", "sider"]


def ka_gat(smiles: str, task: Task = "bbbp", timeout: int = 300) -> dict:
    """
    Predict molecular properties using KA-GAT.

    Args:
        smiles: SMILES string (e.g., "CCO" for ethanol)
        task: bbbp, clintox, tox21, or sider
        timeout: Timeout in seconds

    Returns:
        {"output": str} on success, or {"error": str} on failure
    """
    return _run("/opt/tools/ka_gat", "ka_gat", smiles, task, timeout)


def ka_gnn(smiles: str, task: Task = "bbbp", timeout: int = 300) -> dict:
    """
    Predict molecular properties using KA-GNN.

    Args:
        smiles: SMILES string (e.g., "CCO" for ethanol)
        task: bbbp, clintox, tox21, or sider
        timeout: Timeout in seconds

    Returns:
        {"output": str} on success, or {"error": str} on failure
    """
    return _run("/opt/tools/ka_gnn", "ka_gnn", smiles, task, timeout)


def _run(path: str, env: str, smiles: str, task: str, timeout: int) -> dict:
    """Run prediction in micromamba environment."""
    cmd = f'cd {path} && micromamba run -n {env} python predict.py --task {task} --smiles "{smiles}"'

    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            return {"error": error}

        return {"output": result.stdout.strip()}

    except subprocess.TimeoutExpired:
        return {"error": f"Timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}
