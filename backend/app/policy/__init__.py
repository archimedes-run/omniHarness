"""Permission policy engine (Feature 003).

Classifies every tool call into one of the constitution's three tiers before it
executes. Occupies the single dispatch chokepoint as an AgentMiddleware, where
a call can be inspected, allowed, or refused without running.
"""
