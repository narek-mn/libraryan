import json
from pathlib import Path

import pytest

from libraryan import config, runtimes
from libraryan.runtimes import claude, codex, command, copilot, cursor, gemini, opencode, qwen


def test_claude_author_argv():
    cfg = {**config.DEFAULTS, "_bin": "/b/claude"}
    argv, env = claude.command("author", "the prompt", cfg, {"usd": 5, "turns": 60}, Path("x.md"))
    assert argv[:4] == ["/b/claude", "-p", "--agent", "libraryan"]
    assert argv[argv.index("--allowedTools") + 1] == claude.ALLOWED_TOOLS
    assert argv[argv.index("--max-budget-usd") + 1] == "5"
    assert argv[argv.index("--output-format") + 1] == "json" and argv[-1] == "the prompt"
    assert env == {"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"}


def test_claude_reviewer_argv():
    cfg = {**config.DEFAULTS, "_bin": "c", "model": "m-author", "reviewer_model": "m-review"}
    argv, _ = claude.command("reviewer", "p", cfg, {"usd": 2, "turns": 30}, Path("x.md"))
    assert argv[argv.index("--agent") + 1] == "libraryan-reviewer"
    assert argv[argv.index("--allowedTools") + 1] == claude.REVIEW_TOOLS
    assert argv[argv.index("--permission-mode") + 1] == "default" and argv[argv.index("--model") + 1] == "m-review"


def test_claude_parse_ok():
    out = json.dumps({"result": "hi", "total_cost_usd": 0.5, "num_turns": 4, "is_error": False})
    assert claude.parse(out, "", 0) == ("hi", {"cost_usd": 0.5, "tokens": None, "turns": 4, "is_error": False}, True)
    assert claude.parse(out, "", 1)[2] is False


def test_claude_parse_is_error():
    out = json.dumps({"subtype": "error_max_turns", "total_cost_usd": 0.3, "num_turns": 9, "is_error": True})
    text, usage, ok = claude.parse(out, "", 0)
    assert (text, ok, usage["is_error"], usage["cost_usd"]) == ("", False, True, 0.3)


def test_claude_parse_not_json():
    assert claude.parse("hello", "", 0)[::2] == ("hello", False)
    assert claude.parse("[1]", "", 0)[2] is False


def test_detect_missing_binary_is_none(tmp_path):
    assert runtimes.detect("claude", str(tmp_path / "nope")) is None
    script = tmp_path / "tool"
    script.write_text("#!/bin/sh\necho 'tool 1.2'\necho more\n")
    script.chmod(0o755)
    assert runtimes.detect("claude", str(script)) == "tool 1.2"


def test_get_unknown_raises():
    assert runtimes.get("claude") is claude
    with pytest.raises(ValueError):
        runtimes.get("nope")


def test_with_instructions(tmp_path):
    f = tmp_path / "i.md"
    assert runtimes.with_instructions("p", f) == "p"
    f.write_text("rules\n")
    assert runtimes.with_instructions("p", f) == "rules\n\n---\n\np"


def codex_out(*events):
    return "\n".join(json.dumps(e) for e in events)


MSG = {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}
DONE = {"type": "turn.completed", "usage": {"input_tokens": 200, "cached_input_tokens": 20, "output_tokens": 10}}


def test_codex_argv_roles(tmp_path):
    ins = tmp_path / "i.md"
    ins.write_text("NEUTRAL RULES\n")
    cfg = {**config.DEFAULTS, "_bin": "/b/codex", "model": "m-author", "reviewer_model": "m-review"}
    argv, env = codex.command("author", "the prompt", cfg, {"usd": 5, "turns": 60}, ins)
    assert argv[:3] == ["/b/codex", "exec", "--json"] and argv[argv.index("-s") + 1] == "workspace-write"
    assert argv[argv.index("-m") + 1] == "m-author" and env == {}
    assert argv[-1].startswith("NEUTRAL RULES") and argv[-1].endswith("the prompt")
    argv, _ = codex.command("reviewer", "p", cfg, {"usd": 2, "turns": 30}, ins)
    assert argv[argv.index("-s") + 1] == "read-only" and argv[argv.index("-m") + 1] == "m-review"
    assert "NEUTRAL RULES" in argv[-1]


def test_codex_parse_ok_counts_tokens():
    out = codex_out({"type": "turn.started"}, MSG, DONE, {"type": "turn.started"},
                    {"type": "item.completed", "item": {"type": "agent_message", "text": "last"}}, DONE)
    text, usage, ok = codex.parse(out, "", 0)
    assert (text, ok) == ("last", True)
    assert usage == {"cost_usd": None, "tokens": 420, "turns": 2, "is_error": False}
    assert codex.parse(out, "", 1)[2] is False


def test_codex_parse_turn_failed():
    out = codex_out({"type": "turn.started"}, {"type": "error", "message": "x"},
                    {"type": "turn.failed", "error": {"message": "x"}})
    text, usage, ok = codex.parse(out, "", 1)
    assert (text, ok, usage["is_error"]) == ("", False, True)
    assert codex.parse(codex_out(MSG, {"type": "turn.failed"}), "", 0)[2] is False


def test_codex_warning_item_is_not_failure():
    warn = {"type": "item.completed", "item": {"type": "error", "message": "Model metadata not found"}}
    text, usage, ok = codex.parse(codex_out({"type": "turn.started"}, warn, MSG, DONE), "", 0)
    assert (text, ok, usage["is_error"]) == ("done", True, False)


def test_codex_parse_no_message_or_garbage_fails():
    assert codex.parse(codex_out({"type": "turn.started"}, DONE), "", 0)[2] is False
    assert codex.parse("not json\n[1]\n", "", 0)[2] is False


def test_command_substitutes_prompt_and_instructions_file():
    cfg = {"runtime_command": ["tool", "--sys", "{instructions_file}", "-m", "{prompt}"]}
    argv, env = command.command("author", "do it", cfg, {}, Path("a/x.md"))
    assert argv == ["tool", "--sys", "a/x.md", "-m", "do it"] and env == {}


def test_command_prepends_instructions_without_placeholder(tmp_path):
    (tmp_path / "x.md").write_text("RULES")
    argv, _ = command.command("author", "do it", {"runtime_command": ["tool", "{prompt}"]}, {}, tmp_path / "x.md")
    assert argv[0] == "tool" and argv[1].startswith("RULES") and argv[1].endswith("do it")


def test_command_empty_output_is_failure():
    assert command.parse("hi", "", 0)[0::2] == ("hi", True)
    assert command.parse("  \n", "", 0)[2] is False
    text, usage, ok = command.parse("x", "", 2)
    assert (ok, usage["is_error"]) == (False, True)


def test_gemini_reviewer_uses_policy_not_plan_mode(tmp_path):
    ins = tmp_path / "i.md"
    ins.write_text("NEUTRAL RULES\n")
    cfg = {**config.DEFAULTS, "_bin": "/b/gemini", "model": "m-a", "reviewer_model": "m-r"}
    argv, env = gemini.command("reviewer", "the prompt", cfg, {"usd": 2, "turns": 30}, ins)
    assert argv[0] == "/b/gemini" and argv[argv.index("-o") + 1] == "json" and argv[argv.index("-m") + 1] == "m-r"
    assert argv[argv.index("--approval-mode") + 1] == "default" and "plan" not in argv and "--yolo" not in argv
    assert argv[argv.index("--policy") + 1] == ".libraryan/policies/gemini-reviewer.toml"
    assert argv[-2] == "-p" and argv[-1].startswith("NEUTRAL RULES") and argv[-1].endswith("the prompt")
    assert env == {"GEMINI_CLI_TRUST_WORKSPACE": "true"}
    argv, _ = gemini.command("author", "p", cfg, {"usd": 5, "turns": 60}, ins)
    assert argv[argv.index("--approval-mode") + 1] == "auto_edit" and argv[argv.index("-m") + 1] == "m-a"
    assert argv[argv.index("--policy") + 1] == ".libraryan/policies/gemini-author.toml"


def test_gemini_parse_ok():
    out = json.dumps({"session_id": "s", "response": "hi", "stats": {"models": {
        "a": {"tokens": {"total": 100}}, "b": {"tokens": {"total": 20}}}}})
    assert gemini.parse(out, "", 0) == ("hi", {"cost_usd": None, "tokens": 120, "turns": None, "is_error": False}, True)
    assert gemini.parse(out, "", 1)[2] is False
    assert gemini.parse(json.dumps({"response": "hi", "error": {"type": "INVALID_STREAM"}}), "", 0)[2] is False
    assert gemini.parse(json.dumps({"response": ""}), "", 0)[2] is False
    assert gemini.parse("", "[ERROR] x", 41) == ("", {"cost_usd": None, "tokens": None, "turns": None, "is_error": False}, False)


def test_qwen_argv_has_turn_cap():
    cfg = {**config.DEFAULTS, "_bin": "/b/qwen", "model": "m-a", "reviewer_model": "m-r"}
    for role, turns in (("author", 60), ("author", 200), ("reviewer", 30)):
        argv, env = qwen.command(role, "p", cfg, {"usd": 5, "turns": turns}, Path("missing.md"))
        assert argv[argv.index("--max-session-turns") + 1] == str(turns) and argv[argv.index("-o") + 1] == "json"
        assert argv[-2:] == ["-p", "p"] and env == {}
    assert argv[argv.index("--approval-mode") + 1] == "default" and "run_shell_command" in argv[argv.index("--exclude-tools") + 1]
    assert argv[argv.index("-m") + 1] == "m-r"
    argv, _ = qwen.command("author", "p", cfg, {"usd": 5, "turns": 60}, Path("missing.md"))
    assert argv[argv.index("--approval-mode") + 1] == "auto-edit"


def test_qwen_parse():
    res = {"type": "result", "is_error": False, "num_turns": 3, "result": "hi", "usage": {"input_tokens": 90, "output_tokens": 10}}
    out = json.dumps([{"type": "system"}, res])
    assert qwen.parse(out, "", 0) == ("hi", {"cost_usd": None, "tokens": 100, "turns": 3, "is_error": False}, True)
    cap = json.dumps([{**res, "is_error": True, "subtype": "error_max_turns", "result": None}])
    text, usage, ok = qwen.parse(cap, "", 53)
    assert (text, ok, usage["is_error"]) == ("", False, True)
    assert qwen.parse("nope", "", 0)[2] is False


@pytest.mark.parametrize("mod,flags", [(qwen, ("--allowed-tools", "--exclude-tools")), (gemini, ("--policy",))])
@pytest.mark.parametrize("role", ["author", "reviewer"])
@pytest.mark.parametrize("model", [None, "m"])
def test_prompt_never_follows_list_flag(mod, flags, role, model):
    cfg = {**config.DEFAULTS, "_bin": "b", "model": model, "reviewer_model": None}
    argv, _ = mod.command(role, "PROMPT", cfg, {"usd": 1, "turns": 5}, Path("missing.md"))
    assert argv[-2] == "-p" and argv[-1] == "PROMPT"
    assert not any(a in flags for a in argv[argv.index("PROMPT") - 1:argv.index("PROMPT")])


CFG = {**config.DEFAULTS, "_bin": "/b/tool", "model": "m-a", "reviewer_model": "m-r"}
LIM = {"usd": 5, "turns": 60}


def test_copilot_denies_commit_and_push():
    argv, env = copilot.command("author", "p", CFG, LIM, Path("missing.md"))
    assert "--deny-tool=shell(git commit)" in argv and "--deny-tool=shell(git push)" in argv
    assert "--allow-all-tools" not in argv and "--allow-tool=write" in argv and argv[argv.index("--model") + 1] == "m-a"
    assert not any("max-ai-credits" in a for a in argv) and env["COPILOT_AUTO_UPDATE"] == "false"
    rargv, _ = copilot.command("reviewer", "p", CFG, LIM, Path("missing.md"))
    assert "--allow-tool=write" not in rargv and "--deny-tool=write" in rargv and "--allow-tool=read" in rargv
    assert rargv[rargv.index("--model") + 1] == "m-r"


def test_copilot_uses_agent_file_not_prepend(tmp_path):
    ins = tmp_path / "i.md"
    ins.write_text("PERSONA")
    for role, agent in (("author", "libraryan"), ("reviewer", "libraryan-reviewer")):
        argv, _ = copilot.command(role, "the prompt", CFG, LIM, ins)
        assert argv[argv.index("--agent") + 1] == agent and argv[-2:] == ["-p", "the prompt"]
        assert not any("PERSONA" in a for a in argv)


def test_copilot_parse():
    ev = [{"type": "assistant.turn_start"}, {"type": "assistant.message", "data": {"content": "mid"}},
          {"type": "assistant.turn_start"}, {"type": "assistant.message", "data": {"content": "done"}},
          {"type": "result", "exitCode": 0}]
    out = "\n".join(map(json.dumps, ev))
    assert copilot.parse(out, "", 0) == ("done", {"cost_usd": None, "tokens": None, "turns": 2, "is_error": False}, True)
    assert copilot.parse(out, "", 1)[2] is False
    assert copilot.parse(out.replace('"exitCode": 0', '"exitCode": 1'), "", 0)[2] is False
    err = out + "\n" + json.dumps({"type": "session.error", "data": {"message": "x"}})
    assert copilot.parse(err, "", 0)[2:] == (False,) and copilot.parse(err, "", 0)[1]["is_error"] is True
    assert copilot.parse("\n".join(out.splitlines()[:-1]), "", 0)[2] is False  # no result record
    assert copilot.parse("nope", "", 0)[2] is False


def test_opencode_sums_step_costs():
    def ev(t, **part):
        return json.dumps({"type": t, "part": part})
    out = "\n".join([ev("step_start"), ev("text", text="thinking"),
                     ev("step_finish", reason="tool-calls", cost=0.25, tokens={"input": 100, "output": 5}),
                     ev("step_start"), ev("text", text="final"),
                     ev("step_finish", reason="stop", cost=0.5, tokens={"input": 200, "output": 10})])
    assert opencode.parse(out, "", 0) == ("final", {"cost_usd": 0.75, "tokens": 315, "turns": 2, "is_error": False}, True)
    cut = out.replace('"reason": "stop"', '"reason": "length"')  # e.g. output limit: the work is not done
    assert opencode.parse(cut, "", 0)[2] is False
    assert opencode.parse(out.rsplit("\n", 1)[0], "", 0)[2] is False  # last step not finished
    assert opencode.parse(out, "", 1)[2] is False
    bad = out + "\n" + json.dumps({"type": "error", "error": {"name": "x"}})
    assert opencode.parse(bad, "", 0)[2] is False and opencode.parse(bad, "", 0)[1]["is_error"] is True
    assert opencode.parse("", "boom", 1) == ("", {"cost_usd": None, "tokens": None, "turns": None, "is_error": False}, False)


def test_opencode_command_permissions(tmp_path):
    ins = tmp_path / "i.md"
    ins.write_text("PERSONA")
    argv, env = opencode.command("author", "P", CFG, LIM, ins)
    perm = json.loads(env["OPENCODE_PERMISSION"])
    assert argv[:2] == ["/b/tool", "run"] and argv[argv.index("--format") + 1] == "json" and argv[argv.index("-m") + 1] == "m-a"
    assert perm["bash"]["git commit*"] == "deny" and perm["bash"]["git push*"] == "deny" and perm["edit"] == "allow"
    assert argv[-1].startswith("PERSONA") and argv[-1].endswith("P") and "--auto" not in argv
    rargv, renv = opencode.command("reviewer", "P", CFG, LIM, ins)
    rperm = json.loads(renv["OPENCODE_PERMISSION"])
    assert rargv[rargv.index("--agent") + 1] == "plan" and rperm["edit"] == "deny" and rperm["bash"]["*"] == "deny"
    assert list(rperm["bash"])[0] == "*" and rargv[rargv.index("-m") + 1] == "m-r"  # last matching rule wins: "*" first


def test_cursor_author_has_force_reviewer_ask():
    argv, _ = cursor.command("author", "P", CFG, LIM, Path("missing.md"))
    assert argv[:2] == ["/b/tool", "-p"] and "--force" in argv and "--mode" not in argv and argv[-1].endswith("P")
    assert argv[argv.index("--output-format") + 1] == "json" and argv[argv.index("--model") + 1] == "m-a"
    rargv, _ = cursor.command("reviewer", "P", CFG, LIM, Path("missing.md"))
    assert rargv[rargv.index("--mode") + 1] == "ask" and "--force" not in rargv and "--yolo" not in rargv
    assert rargv[rargv.index("--model") + 1] == "m-r"


def test_cursor_parse_ok():
    out = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "hi"})
    assert cursor.parse(out, "", 0) == ("hi", {"cost_usd": None, "tokens": None, "turns": None, "is_error": False}, True)
    assert cursor.parse(out, "", 1)[2] is False
    assert cursor.parse(out.replace("success", "error_during_execution"), "", 0)[2] is False


def test_cursor_non_json_exit0_is_failure():
    assert cursor.parse("all done, no json", "", 0) == ("all done, no json", {"cost_usd": None, "tokens": None, "turns": None, "is_error": False}, False)
    assert cursor.parse("", "", 0)[2] is False


def test_cursor_is_error_false_but_empty_result_fails():
    for res in ("", "  ", None):
        out = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": res})
        assert cursor.parse(out, "", 0)[2] is False


@pytest.mark.parametrize("mod", [copilot, opencode, cursor])
@pytest.mark.parametrize("role", ["author", "reviewer"])
def test_new_adapters_prompt_is_last_and_flags_are_single_valued(mod, role):
    argv, _ = mod.command(role, "PROMPT", {**CFG, "model": None, "reviewer_model": None}, LIM, Path("missing.md"))
    assert argv[-1].endswith("PROMPT")
    if mod is copilot:  # list-valued flags use --flag=value so nothing can swallow the prompt
        assert argv[-2] == "-p" and not any(a in ("--allow-tool", "--deny-tool") for a in argv)
