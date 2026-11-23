// TimerWorker.js — Web Worker backing window.setIntervalWorker /
// window.setTimeoutWorker (Scripts/Timer.js).
//
// TROY-FARM ?v=120: this file was MISSING from the GitHub copy, so the
// Worker failed to load and NO setIntervalWorker callback ever fired —
// the music never started on its own (AudioPlayToggle's interval),
// _AudioCurrentTime never advanced (the 500ms audio refresh), and the
// end-of-track fade-out / next-song handoff never ran. Restoring this
// worker restores all of those. The "ELASPED" spelling is the upstream
// protocol and must match Timer.js exactly.
//
// Protocol (from Timer.js):
//   main -> worker: { Action: "START", RunOnce, Id, TimeOut }
//   main -> worker: { Action: "STOP", Id }
//   worker -> main: { Action: "ELASPED", Id, RunOnce }
var timers = {};
self.onmessage = function (e)
{
    var m = e.data || {};
    if (m.Action === "START")
    {
        if (timers[m.Id] !== undefined)
        {
            clearInterval(timers[m.Id]);
            clearTimeout(timers[m.Id]);
        }
        var fire = function ()
        {
            self.postMessage({ Action: "ELASPED", Id: m.Id, RunOnce: m.RunOnce });
            if (m.RunOnce)
            {
                delete timers[m.Id];
            }
        };
        timers[m.Id] = m.RunOnce ? setTimeout(fire, m.TimeOut) : setInterval(fire, m.TimeOut);
    }
    else if (m.Action === "STOP")
    {
        if (timers[m.Id] !== undefined)
        {
            clearInterval(timers[m.Id]);
            clearTimeout(timers[m.Id]);
            delete timers[m.Id];
        }
    }
};
