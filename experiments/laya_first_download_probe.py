import os, time
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from laya import Router, decide

state = {
    "situation": (
        "It is 23:40 on a weekday night. The user has been typing with high "
        "intensity for the last 12 minutes; a code editor is in the foreground. "
        "CPU load is 68 percent."
    ),
    "feelings": "energy 0.22 low, boredom 0.55, mood 0.61, attachment 0.70, stress 0.30",
}

questions = {
    "action": {
        "type": "choice",
        "instructions": "Pick the single best next behaviour for a small pet otter living on this computer desktop, given `situation` and `feelings`.",
        "criteria": {
            "rest": "curls up and sleeps; picks this when tired, late night, or nothing is happening",
            "walk": "wanders left and right on the desktop; picks this when bored but energetic",
            "watch": "sits and watches the user quietly; picks this when the user is present and active",
            "mirror": "pretends to work alongside the user; picks this when the user is deep in flow",
            "cheer": "jumps happily; picks this when in a great mood",
            "seek": "waves to get the user attention; picks this when lonely and ignored",
            "overwhelmed": "dizzy and stressed; picks this when the machine is overloaded",
            "ponder": "stares thoughtfully into space; picks this when curious and calm",
        },
    },
    "intensity": {
        "type": "score",
        "instructions": "How strongly should this behaviour be expressed, from 0 low to 1 high?",
    },
}

t0 = time.time()
router = Router(device="cpu")
print("router ready in %.2fs" % (time.time() - t0), flush=True)
t1 = time.time()
result = decide(router, state, questions=questions, return_details=True)
print("first decide %.2fs" % (time.time() - t1), flush=True)
print("RESULT:", result, flush=True)
t2 = time.time()
result2 = decide(router, state, questions=questions)
print("second decide %.2fs" % (time.time() - t2), flush=True)
print("RESULT2:", result2, flush=True)
