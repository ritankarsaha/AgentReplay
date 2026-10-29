import assert from "node:assert/strict";
import test from "node:test";

import type { ModelRunOut } from "../control-plane.ts";
import { aggregate } from "../scoreboard.ts";

function run(model: string, verdict: string, cost: number | null = null, taskClass = "flight_selection"): ModelRunOut {
  return {
    id: `${model}-${verdict}-${Math.random()}`,
    source_run_id: "r",
    span_id: "s",
    model,
    verdict,
    cost_usd: cost,
    created_at: null,
    output: { task_class: taskClass },
  };
}

test("counts repeats, correct and errors per model, errors never hidden", () => {
  const rows = aggregate([
    run("a", "correct", 0.01),
    run("a", "correct", 0.02),
    run("a", "correct", 0.03),
    run("b", "repeats_mistake", 0.01),
    run("b", "correct"),
    run("b", "error"),
    run("c", "error"),
  ]);
  const byModel = Object.fromEntries(rows.map((r) => [r.model, r]));
  assert.equal(byModel.a.repeatsMistake, false);
  assert.equal(byModel.a.correctRate, 1);
  assert.ok(Math.abs((byModel.a.costUsd ?? 0) - 0.06) < 1e-9);
  assert.equal(byModel.b.repeatsMistake, true);
  assert.deepEqual([byModel.b.repeats, byModel.b.correct, byModel.b.errors, byModel.b.trials], [1, 1, 1, 3]);
  assert.equal(byModel.b.correctRate, 0.5);
  assert.equal(byModel.c.repeatsMistake, null);
  assert.equal(byModel.c.correctRate, null);
  assert.equal(byModel.c.costUsd, null);
});

test("groups by task class and sorts deterministically", () => {
  const rows = aggregate([run("z", "correct", null, "b_task"), run("a", "correct", null, "b_task"), run("m", "correct", null, "a_task")]);
  assert.deepEqual(rows.map((r) => `${r.taskClass}/${r.model}`), ["a_task/m", "b_task/a", "b_task/z"]);
});

test("defaults the task class and handles no runs", () => {
  assert.equal(aggregate([{ ...run("a", "correct"), output: null }])[0].taskClass, "flight_selection");
  assert.deepEqual(aggregate([]), []);
});
