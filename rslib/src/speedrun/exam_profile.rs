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

impl Collection {
    /// Read the stored exam-profile JSON string, or empty string if unset.
    pub(crate) fn speedrun_exam_profile_json(&self, exam_id: &str) -> String {
        self.get_config_optional::<String, _>(exam_profile_key(exam_id).as_str())
            .unwrap_or_default()
    }
}
