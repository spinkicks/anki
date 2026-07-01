// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

use crate::collection::Collection;

/// Config key under which an exam profile JSON string is stored, per exam id.
pub(crate) fn exam_profile_key(exam_id: &str) -> String {
    let id = if exam_id.is_empty() {
        "gre_math"
    } else {
        exam_id
    };
    format!("speedrun:exam_profile:{id}")
}

/// Baked-in default exam profile (the canonical GRE-math exam DAG). Returned by
/// `speedrun_exam_profile_json` when the collection has no stored profile, so
/// fresh collections render on both platforms without a per-platform bootstrap.
const DEFAULT_GRE_MATH_PROFILE: &str =
    include_str!("../../../speedrun/exam_profiles/gre_math.json");

impl Collection {
    /// Read the stored exam-profile JSON string. Falls back to the baked-in
    /// default (gre_math) when unset, so a fresh collection still resolves a
    /// profile on both desktop and Android (fixes GetExamProfile == "" ).
    pub(crate) fn speedrun_exam_profile_json(&self, exam_id: &str) -> String {
        let stored = self
            .get_config_optional::<String, _>(exam_profile_key(exam_id).as_str())
            .unwrap_or_default();
        if !stored.is_empty() {
            return stored;
        }
        let id = if exam_id.is_empty() {
            "gre_math"
        } else {
            exam_id
        };
        if id == "gre_math" {
            return DEFAULT_GRE_MATH_PROFILE.to_string();
        }
        stored
    }
}
