import type { ModelRunOut } from "./control-plane";

export interface ScoreboardRow {
  taskClass: string;
  model: string;
  trials: number;
  repeats: number;
  correct: number;
  errors: number;
  correctRate: number | null;
  repeatsMistake: boolean | null;
  costUsd: number | null;
}

/** Mirrors controlplane/learn/scoreboard.py: errors are counted, never hidden. */
export function aggregate(runs: ModelRunOut[]): ScoreboardRow[] {
  const buckets = new Map<string, ModelRunOut[]>();
  for (const run of runs) {
    const key = `${run.output?.task_class ?? "flight_selection"}\u0000${run.model}`;
    buckets.set(key, [...(buckets.get(key) ?? []), run]);
  }
  return [...buckets.entries()]
    .map(([key, rows]) => {
      const [taskClass, model] = key.split("\u0000");
      const verdicts = rows.map((r) => r.verdict);
      const repeats = verdicts.filter((v) => v === "repeats_mistake").length;
      const correct = verdicts.filter((v) => v === "correct").length;
      const errors = verdicts.filter((v) => v === "error").length;
      const scored = repeats + correct;
      const costs = rows.map((r) => r.cost_usd).filter((c): c is number => c != null);
      return {
        taskClass,
        model,
        trials: rows.length,
        repeats,
        correct,
        errors,
        correctRate: scored ? correct / scored : null,
        repeatsMistake: scored ? repeats > 0 : null,
        costUsd: costs.length ? costs.reduce((a, b) => a + b, 0) : null,
      };
    })
    .sort((a, b) => a.taskClass.localeCompare(b.taskClass) || a.model.localeCompare(b.model));
}
