# Confido Health — Data Lead Take-Home

## How we'll read this

We are not scoring polish. We are scoring whether you can think like the person who decides what Confido measures, and whether your judgment compounds beyond what an LLM alone would produce. LLMs are encouraged. Submissions that are clearly unedited LLM output will be rejected.

## What you'll receive

- **50 anonymized call transcripts.**
- **10 anonymized call recordings** (audio) — a separate set, not a subset of the 50 transcripts. Treat the transcripts and the recordings as two independent samples.

*NOTE: Places where audio recordings have been cut to ensure anonymity OR redaction done on transcripts should not be penalised in your evals.* 

## What to submit

1. **Your evaluation rubric** — the dimensions you'd score on Confido's calls, split into **agent performance** and **patient experience**. For each dimension: definition, scoring scale, and why it earned a place in the rubric. The metrics you chose *not* to include are as informative as the ones you did — tell us what you ruled out and why.
2. **LLM-as-judge prompts** — for every metric you'd automate, the exact prompt you'd send to the judge and the output schema you'd want back. One line per metric on which ones are low-confidence / wide-CI, where you'd want to periodically escalate a sample of calls to human review so the judge itself stays calibrated and the next round of error analysis has fresh ground truth to learn from. We are not looking for which metrics you'd keep fully human — at our scale that isn't possible — we're looking for which metrics you'd plan to *audit* humans-in-the-loop, and how often.
3. **Error analysis — show the loop** — Walk us through how you actually built the judges. Start with how you manually scored a subset of calls, what you learned from that marking, how that marking informed the LLM-as-judge prompt you wrote, and how you'd keep refining the judge over time.
4. **Top failure patterns** — six in total:
  - **Three systemic failure patterns with major impact on automation rate.**
  - **Three systemic failure patterns with major impact on patient experience.**
   For each: name the pattern, its prevalence in the sample (how many calls and which), why it impacts that specific metric, and the fix you'd propose. These are the six things you'd put in front of the product team in week one.
5. **Optional but highly recommended — a video recording** covering:
  - The approach you took
  - Why you chose those evals
  - Why you chose those systemic failure patterns as having major impact
   One take, no edits. Candidates who skip this should expect us to lean harder on the written submission.

