"""One module per stage. A stage is `async def run(ctx: StageCtx) -> None`: it does its work, writes
files into the film folder, and raises StageFailed / PauseForApproval. Whether it is *complete* is
never its own say: checks.stage_complete looks at the folder (runner.py)."""
