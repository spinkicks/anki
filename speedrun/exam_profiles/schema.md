# Exam-profile JSON schema

One JSON object per exam, keyed by `exam_id`. Rides in the synced collection config later.

- `exam_id` (string): e.g. "gre_math".
- `name` (string): human title.
- `version` (int): bump on any topic/weight change.
- `topics` (array of objects):
  - `id` (string): hierarchical tag, e.g. "calc::single_var::integration". Uses `::`.
  - `name` (string): human label.
  - `ets_weight` (number): fraction of the exam (all weights sum to 1.0 +/- 0.001).
  - `prereqs` (array of string): topic ids that are prerequisites (DAG edges; must be acyclic and reference existing ids).

Invariants (enforced by tests/test_exam_profile.py):

1. All `id` values are unique.
2. Sum of `ets_weight` == 1.0 (within 1e-3).
3. Every `prereqs` entry references an existing topic `id`.
4. The prereq graph is acyclic (a DAG).
