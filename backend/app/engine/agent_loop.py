"""Agent loop: match -> propose -> validate -> execute.

The V0 capture loop: match conditions against the Strategy JSON; on a match send a
proposal to Telegram with a hard 5-minute validity window; honor the circuit
breaker (invalidate past 50% of stop distance); on approval re-check the window,
then place the order via MetaApi with SL/TP at the broker; write the decision to
agent_logs. Scaffold stub — not implemented.
"""
