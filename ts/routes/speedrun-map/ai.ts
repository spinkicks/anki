// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Desktop "Generate practice" bridge for The Map. The AI service is EXTERNAL and
// OFF-by-default: the Qt side (qt/aqt/speedrun.py) does the env check + /health
// probe and the /generate_batch POST OFF the UI thread; this module only fires
// the pycmd and awaits the JS callback the Qt side calls back with the result.
//
// On a plain preview / Android (no pycmd/bridgeCommand and no Qt handler) the
// probe simply never resolves "available", so the button stays DISABLED and
// there is ZERO behaviour change.

// The single bridge entry point (desktop aliases pycmd === bridgeCommand; fire
// via ONE only, or a shared command double-dispatches). Prefer pycmd.
type Bridge = (cmd: string) => void;

function bridge(): Bridge | null {
    const w = window as unknown as {
        pycmd?: Bridge;
        bridgeCommand?: Bridge;
    };
    if (typeof w.pycmd === "function") return w.pycmd;
    if (typeof w.bridgeCommand === "function") return w.bridgeCommand;
    return null;
}

/** How many verified problems a "Generate practice" click asks the AI for. */
export const GEN_BATCH_SIZE = 5;

/** Result of a generate round-trip, pushed back by the Qt callback. */
export interface GenResult {
    topic: string;
    added: number;
    // How many problems were REQUESTED (batch size). Lets the UI report a
    // partial batch honestly ("Added 2 of 5") instead of a bare success.
    requested: number;
    error: string;
}

/**
 * Ask the desktop whether AI is usable (env enabled + /health reports enabled).
 * Fires ``pycmd("speedrun:ai:probe")`` and resolves when Qt calls
 * ``window.speedrunAiAvailability(bool)``. Resolves ``false`` if there is no
 * bridge (preview/Android) or the probe doesn't answer within ``timeoutMs`` —
 * so the button defaults to DISABLED (safe, zero behaviour change).
 */
export function probeAiAvailability(timeoutMs = 4000): Promise<boolean> {
    const send = bridge();
    if (!send) return Promise.resolve(false);
    return new Promise<boolean>((resolve) => {
        let done = false;
        const finish = (v: boolean) => {
            if (done) return;
            done = true;
            delete (window as any).speedrunAiAvailability;
            resolve(v);
        };
        (window as any).speedrunAiAvailability = (available: boolean) =>
            finish(!!available);
        window.setTimeout(() => finish(false), timeoutMs);
        try {
            send("speedrun:ai:probe");
        } catch {
            finish(false);
        }
    });
}

/**
 * Request 5 verified practice problems for a covered leaf topic. Fires
 * ``pycmd("speedrun:gen:<topic>")`` and resolves when Qt calls
 * ``window.speedrunGenStatus({topic, added, error})``. On no bridge / timeout,
 * resolves an honest zero-added error so the UI never claims a false success.
 */
export function requestGenerate(topic: string, timeoutMs = 90000): Promise<GenResult> {
    const send = bridge();
    if (!send) {
        return Promise.resolve({
            topic,
            added: 0,
            requested: GEN_BATCH_SIZE,
            error: "AI not available",
        });
    }
    return new Promise<GenResult>((resolve) => {
        let done = false;
        const finish = (r: GenResult) => {
            if (done) return;
            done = true;
            delete (window as any).speedrunGenStatus;
            resolve(r);
        };
        (window as any).speedrunGenStatus = (r: Partial<GenResult>) =>
            finish({
                topic: r?.topic ?? topic,
                added: typeof r?.added === "number" ? r.added : 0,
                // Default to the batch size when Qt omits it, so the toast can
                // still frame a partial ("Added N of 5").
                requested:
                    typeof r?.requested === "number" ? r.requested : GEN_BATCH_SIZE,
                error: r?.error ?? "",
            });
        window.setTimeout(
            () =>
                finish({
                    topic,
                    added: 0,
                    requested: GEN_BATCH_SIZE,
                    error: "timed out",
                }),
            timeoutMs,
        );
        try {
            send("speedrun:gen:" + topic);
        } catch {
            finish({
                topic,
                added: 0,
                requested: GEN_BATCH_SIZE,
                error: "AI not available",
            });
        }
    });
}
