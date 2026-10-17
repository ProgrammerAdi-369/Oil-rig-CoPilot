"""Guarded auto-fix loop. Edits only copilot/prompt_addendum.txt (a sandbox file the agent appends to its system prompt).
   py -m copilot.eval.fix_loop [--max-iter 2] [--dry]      py -m copilot.eval.fix_loop --selftest
Guardrails against overfitting to the 18 questions:
  1. only failures the critic tags layer=prompt are eligible; tool / ingest / logic bugs are left for a human.
  2. the proposer may add ONE general behavioural rule; anything naming a well, id, person, area or number is rejected.
  3. a candidate is kept only if more steps PASS, no previously passing step regresses, and the oracle-generated hold-out
     questions (property mode) do not regress; otherwise the file is restored from the snapshot.
  4. bounded iterations; every attempt is appended to Docs/QA_FIXLOG.md."""
import re
import sys
from pathlib import Path

from copilot import agent

from . import critic
from .golden import GOLDEN
from .oracle import Oracle

LOG = critic.ROOT / "Docs" / "QA_FIXLOG.md"
SPECIFIC = re.compile(r"\d|WELL-|INS-|MNT-|REG-|CTX-|USR-|\bU-|Block|\b(NE|SW)\b|T200|T350|Michael|Jessica|Tyler|Jake|Laura|Ryan|Chris|Emily|Sarah",
                      re.I)


def valid_rule(rule):
    return bool(rule) and 20 <= len(rule) <= 220 and not SPECIFIC.search(rule)


def accept(base, cand, base_hold, cand_hold):
    """base/cand: {step: status}. Keep only a strict improvement where every previously passing step still passes
    (an ERROR counts against the patch: with no proof it is safe, revert)."""
    passed = lambda d: sum(s == "PASS" for s in d.values())
    regress = [k for k, s in base.items() if s == "PASS" and cand.get(k) != "PASS"]
    hold_regress = [k for k, s in base_hold.items() if s == "PASS" and cand_hold.get(k) != "PASS"]
    return passed(cand) > passed(base) and not regress and not hold_regress and passed(cand_hold) >= passed(base_hold)


def propose(fixable):
    notes = "\n".join(f"- [{v['key']}] " + "; ".join(f"{c['id']}: {c['detail'][:140]}" for c in v["violations"]) for v in fixable)
    prompt = ("The system prompt of an oil-field copilot makes it fail these QA checks (the data and tools are correct; only the answer "
              f"wording/behaviour is wrong):\n{notes}\n\nWrite ONE new general behavioural rule (max 200 characters) that would prevent this "
              "class of mistake. It must not mention any specific well, ID, person, area, number or question. Reply with the rule only.")
    key = agent.os.environ.get("LLM_API_KEY") or agent.os.environ.get("GEMINI_API_KEY")
    msg = agent.call_llm([{"role": "user", "content": prompt}], key, model=critic.JUDGE_MODEL, with_tools=False)
    return re.sub(r'^[\s\-*"]+|["\s]+$', "", (msg.get("content") or "").strip().splitlines()[0]) if msg.get("content") else ""


def evaluate_all():
    results, db = critic.run_session(GOLDEN)
    verdicts = critic.critique(GOLDEN, results, db)
    hold_steps = critic.prop_steps(Oracle(critic.ROOT / "sample-data"), 6)
    h_results, h_db = critic.run_session(hold_steps)
    hold = critic.critique(hold_steps, h_results, h_db)
    return verdicts, {v["key"]: v["status"] for v in verdicts}, {v["key"]: v["status"] for v in hold}


def log(line):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main(max_iter, dry):
    verdicts, base, base_hold = evaluate_all()
    print("baseline PASS", sum(s == "PASS" for s in base.values()), "of", len(base))
    for n in range(max_iter):
        fixable = [v for v in verdicts if v["status"] == "FAIL" and v.get("layer") == "prompt"]
        if not fixable:
            log(f"- iteration {n + 1}: no failure is tagged layer=prompt; nothing to auto-fix")
            break
        rule = propose(fixable)
        if not valid_rule(rule):
            log(f"- iteration {n + 1}: proposal rejected (not general / wrong size): {rule!r}")
            continue
        if dry:
            print("would add:", rule)
            break
        snap = agent.ADDENDUM.read_text(encoding="utf-8") if agent.ADDENDUM.exists() else None
        agent.ADDENDUM.write_text((snap or "") + f"\n- {rule}", encoding="utf-8")
        cand_verdicts, cand, cand_hold = evaluate_all()
        ok = accept(base, cand, base_hold, cand_hold)
        log(f"- iteration {n + 1}: rule {rule!r} -> PASS {sum(s == 'PASS' for s in base.values())} → {sum(s == 'PASS' for s in cand.values())}; "
            f"{'KEPT' if ok else 'REVERTED'}")
        if ok:
            verdicts, base, base_hold = cand_verdicts, cand, cand_hold
        elif snap is None:
            agent.ADDENDUM.unlink()
        else:
            agent.ADDENDUM.write_text(snap, encoding="utf-8")


def selftest():
    assert valid_rule("Always name the person behind a correction and quote the dates in their note when answering.")
    for bad in ("For WELL-0164 always say no reason is recorded.", "Mention Michael Turner's rule.", "State 5.4 bbl is reportable.", "Be nice", "x" * 300):
        assert not valid_rule(bad), bad
    base, hold = {"a": "PASS", "b": "FAIL", "c": "FAIL"}, {"h": "PASS"}
    assert accept(base, {"a": "PASS", "b": "PASS", "c": "FAIL"}, hold, {"h": "PASS"})
    assert not accept(base, {"a": "FAIL", "b": "PASS", "c": "PASS"}, hold, {"h": "PASS"}), "regression on a passing step"
    assert not accept(base, {"a": "PASS", "b": "FAIL", "c": "FAIL"}, hold, {"h": "PASS"}), "no improvement"
    assert not accept(base, {"a": "PASS", "b": "PASS", "c": "FAIL"}, hold, {"h": "FAIL"}), "hold-out regression"
    assert not accept(base, {"a": "ERROR", "b": "PASS", "c": "PASS"}, hold, {"h": "PASS"}), "a passing step that errors blocks the patch"
    assert accept(base, {"a": "PASS", "b": "PASS", "c": "ERROR"}, hold, {"h": "PASS"}), "an error on an already-failing step is harmless"
    print("fix_loop OK: proposal filter and accept/revert rule behave")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--selftest" in a:
        selftest()
    else:
        main(int(a[a.index("--max-iter") + 1]) if "--max-iter" in a else 2, "--dry" in a)
