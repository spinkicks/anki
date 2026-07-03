// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { probeAiAvailability, requestGenerate } from "./ai";

// vitest runs in a node environment (no DOM), so stub the minimal window API the
// bridge module touches: pycmd, setTimeout/clearTimeout, and callback slots.
interface StubWindow {
    pycmd?: (cmd: string) => void;
    bridgeCommand?: (cmd: string) => void;
    speedrunAiAvailability?: (v: boolean) => void;
    speedrunGenStatus?: (r: unknown) => void;
    setTimeout: typeof setTimeout;
    clearTimeout: typeof clearTimeout;
}

let win: StubWindow;

beforeEach(() => {
    win = {
        setTimeout: ((fn: () => void, ms?: number) =>
            setTimeout(fn, ms)) as typeof setTimeout,
        clearTimeout: ((id: any) => clearTimeout(id)) as typeof clearTimeout,
    };
    (globalThis as any).window = win;
});

afterEach(() => {
    delete (globalThis as any).window;
    vi.restoreAllMocks();
});

describe("probeAiAvailability", () => {
    test("resolves false when there is no bridge (preview/Android)", async () => {
        // No pycmd/bridgeCommand => button must default to disabled.
        await expect(probeAiAvailability(50)).resolves.toBe(false);
    });

    test("resolves the boolean the Qt callback provides (available)", async () => {
        win.pycmd = () => {
            // Simulate Qt answering the probe on the next tick.
            setTimeout(() => win.speedrunAiAvailability?.(true), 0);
        };
        await expect(probeAiAvailability(1000)).resolves.toBe(true);
    });

    test("resolves false when Qt reports not enabled", async () => {
        win.pycmd = () => {
            setTimeout(() => win.speedrunAiAvailability?.(false), 0);
        };
        await expect(probeAiAvailability(1000)).resolves.toBe(false);
    });

    test("resolves false on timeout (probe never answers)", async () => {
        win.pycmd = () => {}; // never calls back
        await expect(probeAiAvailability(30)).resolves.toBe(false);
    });

    test("fires exactly one bridge command (no double-dispatch)", async () => {
        const pycmd = vi.fn();
        win.pycmd = (cmd: string) => {
            pycmd(cmd);
            setTimeout(() => win.speedrunAiAvailability?.(true), 0);
        };
        // bridgeCommand also present: pycmd must win, and only once.
        win.bridgeCommand = vi.fn();
        await probeAiAvailability(1000);
        expect(pycmd).toHaveBeenCalledTimes(1);
        expect(pycmd).toHaveBeenCalledWith("speedrun:ai:probe");
        expect(win.bridgeCommand).not.toHaveBeenCalled();
    });
});

describe("requestGenerate", () => {
    test("sends speedrun:gen:<topic> and resolves the Qt result", async () => {
        const pycmd = vi.fn();
        win.pycmd = (cmd: string) => {
            pycmd(cmd);
            setTimeout(
                () =>
                    win.speedrunGenStatus?.({
                        topic: "calc::limits",
                        added: 3,
                        error: "",
                    }),
                0,
            );
        };
        const res = await requestGenerate("calc::limits", 1000);
        expect(pycmd).toHaveBeenCalledWith("speedrun:gen:calc::limits");
        expect(res).toEqual({ topic: "calc::limits", added: 3, error: "" });
    });

    test("no bridge => honest zero-added result (never a false success)", async () => {
        const res = await requestGenerate("calc::limits", 50);
        expect(res.added).toBe(0);
        expect(res.error).toBeTruthy();
    });

    test("timeout => zero added", async () => {
        win.pycmd = () => {}; // never answers
        const res = await requestGenerate("calc::limits", 30);
        expect(res.added).toBe(0);
    });

    test("coerces a malformed callback payload to a safe result", async () => {
        win.pycmd = () => {
            setTimeout(() => win.speedrunGenStatus?.({} as unknown), 0);
        };
        const res = await requestGenerate("calc::limits", 1000);
        expect(res.added).toBe(0);
        expect(res.topic).toBe("calc::limits");
    });
});
